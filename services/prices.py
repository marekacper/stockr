import yfinance as yf
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from services.bonds import is_bond, estimate_bond_price

CACHE_FILE = "data/prices_cache.json"
CACHE_MINUTES = 15


def to_yf_ticker(ticker: str) -> str:
    mapping = {".PL": ".WA", ".UK": ".L"}
    for suffix, replacement in mapping.items():
        if ticker.endswith(suffix):
            return ticker[:-len(suffix)] + replacement
    return ticker


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _fetch_single_price(ticker: str) -> tuple[str, float | None]:
    """Pobiera cenę jednego tickera."""
    try:
        yft = to_yf_ticker(ticker)
        data = yf.Ticker(yft)
        price = data.fast_info.last_price
        if price is not None:
            return ticker, round(float(price), 2)
        return ticker, None
    except Exception as e:
        print(f"Błąd kursu {ticker}: {e}")
        return ticker, None


def get_prices(tickers: list) -> dict:
    if not tickers:
        return {}

    cache = load_cache()
    now = datetime.now()
    result = {}
    to_fetch = []

    for ticker in tickers:
        if not isinstance(ticker, str):
            continue

        # Obligacje — własny model
        if is_bond(ticker):
            try:
                from services.portfolio import get_portfolio
                portfolio = get_portfolio()
                pos = portfolio.get(ticker)
                if pos:
                    price = estimate_bond_price(ticker, pos["quantity"], pos["avg_price"])
                    if price is not None:
                        unit_price = round(price / pos["quantity"], 2) if pos["quantity"] > 0 else pos["avg_price"]
                        result[ticker] = unit_price
                        continue
            except Exception:
                pass
            result[ticker] = None
            continue

        # Sprawdź cache
        cached = cache.get(ticker)
        if cached:
            try:
                ts = datetime.fromisoformat(cached["timestamp"])
                if now - ts < timedelta(minutes=CACHE_MINUTES):
                    result[ticker] = cached["price"]
                    continue
            except Exception:
                pass

        to_fetch.append(ticker)

    # Pobierz brakujące równolegle przez ThreadPoolExecutor
    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(len(to_fetch), 8)) as executor:
            futures = {executor.submit(_fetch_single_price, t): t for t in to_fetch}
            for future in as_completed(futures):
                ticker, price = future.result()
                result[ticker] = price
                if price is not None:
                    cache[ticker] = {"price": price, "timestamp": now.isoformat()}

    save_cache(cache)
    return result