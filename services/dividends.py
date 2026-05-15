"""
dividends.py — manualne dywidendy w SQLite, auto-dywidendy z yfinance z cache na dysku.
Tabela: dividends (id, portfolio_id, ticker, amount, date, currency, source)
"""

import json
import os
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.prices import to_yf_ticker
from services.portfolios import get_db, ensure_setup

DIV_CACHE_DIR = "data/div_cache"
DIV_CACHE_TTL = 60 * 60 * 24  # 24 godziny


# ---------------------------------------------------------------------------
# Tabela SQLite
# ---------------------------------------------------------------------------

def _ensure_table():
    ensure_setup()
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dividends (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id TEXT NOT NULL,
                ticker       TEXT NOT NULL,
                amount       REAL NOT NULL,
                date         TEXT NOT NULL,
                currency     TEXT DEFAULT 'PLN',
                source       TEXT DEFAULT 'manual'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_div_portfolio ON dividends(portfolio_id)")


def load_dividends(portfolio_id: str) -> list:
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker, amount, date, currency, source "
            "FROM dividends WHERE portfolio_id = ? ORDER BY date DESC",
            (portfolio_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_dividends(portfolio_id: str, dividends: list):
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM dividends WHERE portfolio_id = ? AND source = 'manual'", (portfolio_id,))
        for d in dividends:
            conn.execute(
                "INSERT INTO dividends (portfolio_id, ticker, amount, date, currency, source) VALUES (?,?,?,?,?,?)",
                (portfolio_id, d["ticker"], float(d["amount"]), d["date"],
                 d.get("currency", "PLN"), "manual")
            )


def add_manual_dividend(portfolio_id: str, ticker: str, amount: float, date_str: str, currency: str = "PLN"):
    _ensure_table()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO dividends (portfolio_id, ticker, amount, date, currency, source) VALUES (?,?,?,?,?,?)",
            (portfolio_id, ticker, round(amount, 2), date_str, currency, "manual")
        )


# ---------------------------------------------------------------------------
# Cache dywidend per ticker
# ---------------------------------------------------------------------------

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
    import glob
    if os.path.exists(DIV_CACHE_DIR):
        for f in glob.glob(os.path.join(DIV_CACHE_DIR, "*.json")):
            try:
                os.remove(f)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Pobieranie z yfinance
# ---------------------------------------------------------------------------

def _fetch_raw_ticker_data(ticker: str) -> dict:
    cached = _load_div_cache(ticker)
    if cached is not None:
        return cached

    result = {"div_yield": 0.0, "dividends": []}
    try:
        yf_ticker = to_yf_ticker(ticker)
        t = yf.Ticker(yf_ticker)
        try:
            result["div_yield"] = float(getattr(t.fast_info, "dividend_yield", None) or 0)
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
    result = {"annual_forecast": 0.0, "dividends": [], "tracker": None}
    raw = _fetch_raw_ticker_data(ticker)

    current_price = prices.get(ticker)
    
    # USUNIĘTE: div_yield z yfinance (nie działa dla GPW)

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

    # Tracker — szacuj następną dywidendę na podstawie historii
    tracker = _estimate_next_dividend(ticker, raw["dividends"], pos["quantity"], current_price)
    result["tracker"] = tracker

    # Prognoza roczna — na podstawie trackera (średnia kwota × częstotliwość w roku)
    if tracker:
        freq_per_year = {
            "miesięcznie": 12,
            "kwartalnie": 4,
            "półrocznie": 2,
            "rocznie": 1,
        }.get(tracker["frequency"], 1)
        result["annual_forecast"] = round(tracker["estimated_amount"] * freq_per_year, 2)

    return result

def _estimate_next_dividend(ticker: str, div_history: list, current_qty: float, current_price: float) -> dict | None:
    """
    Szacuje następną dywidendę na podstawie historycznej częstotliwości wypłat.
    Zwraca None jeśli za mało danych.
    """
    if len(div_history) < 2:
        return None

    # Posortuj rosnąco
    sorted_divs = sorted(div_history, key=lambda x: x["date"])
    last = sorted_divs[-1]
    last_date = datetime.strptime(last["date"], "%Y-%m-%d")

    # Oblicz średnią liczbę dni między dywidendami (ostatnie 4 wypłaty)
    recent = sorted_divs[-5:]
    if len(recent) < 2:
        return None

    intervals = []
    for i in range(1, len(recent)):
        d1 = datetime.strptime(recent[i-1]["date"], "%Y-%m-%d")
        d2 = datetime.strptime(recent[i]["date"], "%Y-%m-%d")
        intervals.append((d2 - d1).days)

    avg_interval = sum(intervals) / len(intervals)

    # Klasyfikuj częstotliwość
    if avg_interval <= 40:
        frequency = "miesięcznie"
        freq_days = 30
    elif avg_interval <= 100:
        frequency = "kwartalnie"
        freq_days = 91
    elif avg_interval <= 200:
        frequency = "półrocznie"
        freq_days = 182
    else:
        frequency = "rocznie"
        freq_days = 365

    # Szacowana data następnej dywidendy
    next_date = last_date + timedelta(days=avg_interval)
    today = datetime.now()

    # Jeśli szacowana data już minęła, dodaj kolejny interwał
    while next_date < today - timedelta(days=7):
        next_date += timedelta(days=avg_interval)

    # Szacowana kwota — średnia z ostatnich 2 wypłat
    recent_amounts = [d["amount_per_share"] for d in sorted_divs[-2:]]
    avg_amount_per_share = sum(recent_amounts) / len(recent_amounts)
    estimated_amount = round(avg_amount_per_share * current_qty, 2)

    days_until = (next_date - today).days

    return {
        "ticker": ticker,
        "next_date": next_date.strftime("%Y-%m-%d"),
        "days_until": days_until,
        "estimated_amount": estimated_amount,
        "amount_per_share": round(avg_amount_per_share, 4),
        "frequency": frequency,
        "last_date": last["date"],
    }


# ---------------------------------------------------------------------------
# Główna funkcja
# ---------------------------------------------------------------------------

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
    tracker_items = []

    if active_tickers:
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
                    if res["tracker"]:
                        tracker_items.append(res["tracker"])
                except Exception:
                    pass

    all_dividends = manual + auto_dividends
    all_dividends.sort(key=lambda x: x["date"], reverse=True)

    # Heatmapa miesięczna
    heatmap = {}
    for d in all_dividends:
        key = d["date"][:7]
        heatmap[key] = heatmap.get(key, 0) + d["amount"]

    # Historia roczna
    by_year = {}
    for d in all_dividends:
        year = d["date"][:4]
        by_year[year] = by_year.get(year, 0) + d["amount"]

    # Tracker — posortuj wg daty następnej wypłaty
    tracker_items.sort(key=lambda x: x["next_date"])

    total_received = sum(d["amount"] for d in all_dividends)

    return {
        "dividends": all_dividends[:50],
        "by_year": {k: round(v, 2) for k, v in sorted(by_year.items())},
        "heatmap": {k: round(v, 2) for k, v in heatmap.items()},
        "total_received": round(total_received, 2),
        "annual_forecast": round(annual_forecast, 2),
        "monthly_forecast": round(annual_forecast / 12, 2),
        "tracker": tracker_items,
    }