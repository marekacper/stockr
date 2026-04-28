import yfinance as yf
import json
import os
from datetime import datetime, timedelta
from services.bonds import is_bond, estimate_bond_price


def get_prices(tickers: list) -> dict:
    if not tickers:
        return {}

    cache = load_cache()
    now = datetime.now()
    result = {}

    # Pobierz portfolio żeby mieć avg_price dla obligacji
    from services.portfolio import get_portfolio
    portfolio = get_portfolio()

    for ticker in tickers:
        if not isinstance(ticker, str):
            continue

        # Obligacje skarbowe — wyceniaj własnym modelem
        if is_bond(ticker):
            pos = portfolio.get(ticker)
            if pos:
                price = estimate_bond_price(ticker, pos["quantity"], pos["avg_price"])
                if price is not None:
                    # Przelicz na cenę jednostkową
                    unit_price = round(price / pos["quantity"], 2) if pos["quantity"] > 0 else pos["avg_price"]
                    result[ticker] = unit_price
                    continue

        # Reszta — yfinance jak dotychczas
        cached = cache.get(ticker)
        if cached:
            try:
                ts = datetime.fromisoformat(cached["timestamp"])
                if now - ts < timedelta(minutes=15):
                    result[ticker] = cached["price"]
                    continue
            except Exception:
                pass

        try:
            yf_ticker = to_yf_ticker(ticker)
            data = yf.Ticker(yf_ticker)
            price = data.fast_info.last_price
            if price is not None:
                result[ticker] = round(float(price), 2)
                cache[ticker] = {
                    "price": round(float(price), 2),
                    "timestamp": now.isoformat()
                }
            else:
                result[ticker] = None
        except Exception as e:
            print(f"Błąd kursu {ticker} ({to_yf_ticker(ticker)}): {e}")
            result[ticker] = None

    save_cache(cache)
    return result

CACHE_FILE = "data/prices_cache.json"


def to_yf_ticker(ticker: str) -> str:
    """Tłumaczy ticker z formatu XTB na format yfinance."""
    mapping = {
        # Giełda frankfurcka
        ".DE": ".DE",    # Frankfurt — zostawiamy bez zmian
        # GPW Warszawa
        ".PL": ".WA",
        # Londyn
        ".UK": ".L",
    }
    for suffix, replacement in mapping.items():
        if ticker.endswith(suffix):
            return ticker[:-len(suffix)] + replacement
    return ticker

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def get_prices(tickers: list) -> dict:
    if not tickers:
        return {}

    cache = load_cache()
    now = datetime.now()
    result = {}

    # Pobierz portfolio żeby mieć avg_price dla obligacji
    from services.portfolio import get_portfolio
    portfolio = get_portfolio()

    for ticker in tickers:
        if not isinstance(ticker, str):
            continue

        # Obligacje skarbowe — wyceniaj własnym modelem
        if is_bond(ticker):
            pos = portfolio.get(ticker)
            if pos:
                price = estimate_bond_price(ticker, pos["quantity"], pos["avg_price"])
                if price is not None:
                    # Przelicz na cenę jednostkową
                    unit_price = round(price / pos["quantity"], 2) if pos["quantity"] > 0 else pos["avg_price"]
                    result[ticker] = unit_price
                    continue

        # Reszta — yfinance jak dotychczas
        cached = cache.get(ticker)
        if cached:
            try:
                ts = datetime.fromisoformat(cached["timestamp"])
                if now - ts < timedelta(minutes=15):
                    result[ticker] = cached["price"]
                    continue
            except Exception:
                pass

        try:
            yf_ticker = to_yf_ticker(ticker)
            data = yf.Ticker(yf_ticker)
            price = data.fast_info.last_price
            if price is not None:
                result[ticker] = round(float(price), 2)
                cache[ticker] = {
                    "price": round(float(price), 2),
                    "timestamp": now.isoformat()
                }
            else:
                result[ticker] = None
        except Exception as e:
            print(f"Błąd kursu {ticker} ({to_yf_ticker(ticker)}): {e}")
            result[ticker] = None

    save_cache(cache)
    return result