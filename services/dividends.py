import json
import os
import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.prices import to_yf_ticker

DIVIDENDS_FILE = "data/dividends.json"
DIV_CACHE_DIR = "data/div_cache"
DIV_CACHE_TTL = 60 * 60 * 24  # 24 godziny


# --- Cache dywidend per ticker ---

def _cache_path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace(".", "_")
    return os.path.join(DIV_CACHE_DIR, f"{safe}.json")


def _load_div_cache(ticker: str) -> dict | None:
    os.makedirs(DIV_CACHE_DIR, exist_ok=True)
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    if datetime.now().timestamp() - os.path.getmtime(path) > DIV_CACHE_TTL:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_div_cache(ticker: str, data: dict):
    os.makedirs(DIV_CACHE_DIR, exist_ok=True)
    try:
        with open(_cache_path(ticker), "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def clear_div_cache():
    """Usuwa cały cache dywidend — wywołaj po imporcie nowych transakcji."""
    import glob
    if os.path.exists(DIV_CACHE_DIR):
        for f in glob.glob(os.path.join(DIV_CACHE_DIR, "*.json")):
            try:
                os.remove(f)
            except Exception:
                pass


# --- Manualne dywidendy ---

def load_dividends(portfolio_id: str) -> list:
    if not os.path.exists(DIVIDENDS_FILE):
        return []
    with open(DIVIDENDS_FILE) as f:
        data = json.load(f)
    return data.get(portfolio_id, [])


def save_dividends(portfolio_id: str, dividends: list):
    data = {}
    if os.path.exists(DIVIDENDS_FILE):
        with open(DIVIDENDS_FILE) as f:
            data = json.load(f)
    data[portfolio_id] = dividends
    with open(DIVIDENDS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_manual_dividend(portfolio_id: str, ticker: str, amount: float, date_str: str, currency: str = "PLN"):
    dividends = load_dividends(portfolio_id)
    dividends.append({
        "ticker": ticker,
        "amount": round(amount, 2),
        "date": date_str,
        "currency": currency,
        "source": "manual",
    })
    dividends.sort(key=lambda x: x["date"], reverse=True)
    save_dividends(portfolio_id, dividends)


# --- Pobieranie danych z yfinance (z cache) ---

def _fetch_raw_ticker_data(ticker: str) -> dict:
    """
    Pobiera surowe dane z yfinance dla tickera i zapisuje do cache.
    Zwraca: {div_yield, dividends: [{date, amount_per_share}]}
    Cache TTL: 24h — dywidendy zmieniają się rzadko.
    """
    cached = _load_div_cache(ticker)
    if cached is not None:
        return cached

    result = {"div_yield": 0.0, "dividends": []}
    try:
        yf_ticker = to_yf_ticker(ticker)
        t = yf.Ticker(yf_ticker)

        try:
            info = t.fast_info
            result["div_yield"] = float(getattr(info, 'dividend_yield', None) or 0)
        except Exception:
            pass

        try:
            divs = t.dividends
            if not divs.empty:
                divs.index = divs.index.tz_localize(None)
                result["dividends"] = [
                    {"date": d.strftime("%Y-%m-%d"), "amount_per_share": round(float(v), 4)}
                    for d, v in zip(divs.index, divs.values)
                ]
        except Exception:
            pass

    except Exception:
        pass

    _save_div_cache(ticker, result)
    return result


def _process_ticker_dividends(ticker: str, pos: dict, prices: dict, get_holding_at_date) -> dict:
    """Przetwarza dane dywidend dla jednego tickera (z cache)."""
    result = {"annual_forecast": 0.0, "dividends": []}

    raw = _fetch_raw_ticker_data(ticker)

    current_price = prices.get(ticker)
    if current_price and raw["div_yield"]:
        result["annual_forecast"] = current_price * raw["div_yield"] * pos["quantity"]

    for entry in raw["dividends"]:
        date_str = entry["date"]
        qty_at_date = get_holding_at_date(ticker, date_str)
        if qty_at_date <= 0:
            continue
        amount = round(entry["amount_per_share"] * qty_at_date, 2)
        result["dividends"].append({
            "ticker": ticker,
            "date": date_str,
            "amount": amount,
            "amount_per_share": entry["amount_per_share"],
            "quantity": qty_at_date,
            "source": "auto",
        })

    return result


# --- Główna funkcja ---

def get_dividend_summary(portfolio_id: str, portfolio: dict, prices: dict) -> dict:
    from services.portfolios import get_transactions_for

    transactions = get_transactions_for(portfolio_id)
    sorted_txs = sorted(transactions, key=lambda x: x["date"])

    def get_holding_at_date(ticker: str, date_str: str) -> float:
        qty = 0.0
        for tx in sorted_txs:
            if tx["ticker"] != ticker:
                continue
            if tx["date"] > date_str:
                break
            if tx["type"] == "buy":
                qty += float(tx["quantity"])
            elif tx["type"] == "sell":
                qty -= float(tx["quantity"])
        return max(0.0, qty)

    manual = load_dividends(portfolio_id)
    active_tickers = {t: pos for t, pos in portfolio.items() if pos["quantity"] > 0}

    auto_dividends = []
    annual_forecast = 0.0

    with ThreadPoolExecutor(max_workers=min(len(active_tickers), 8)) as executor:
        futures = {
            executor.submit(_process_ticker_dividends, ticker, pos, prices, get_holding_at_date): ticker
            for ticker, pos in active_tickers.items()
        }
        for future in as_completed(futures):
            try:
                res = future.result()
                annual_forecast += res["annual_forecast"]
                auto_dividends.extend(res["dividends"])
            except Exception:
                pass

    all_dividends = manual + auto_dividends
    all_dividends.sort(key=lambda x: x["date"], reverse=True)

    heatmap = {}
    for d in all_dividends:
        key = d["date"][:7]
        heatmap[key] = heatmap.get(key, 0) + d["amount"]

    by_year = {}
    for d in all_dividends:
        year = d["date"][:4]
        by_year[year] = by_year.get(year, 0) + d["amount"]

    total_received = sum(d["amount"] for d in all_dividends)

    return {
        "dividends": all_dividends[:50],
        "by_year": {k: round(v, 2) for k, v in by_year.items()},
        "heatmap": {k: round(v, 2) for k, v in heatmap.items()},
        "total_received": round(total_received, 2),
        "annual_forecast": round(annual_forecast, 2),
        "monthly_forecast": round(annual_forecast / 12, 2),
    }