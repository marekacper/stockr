import pandas as pd
import numpy as np
import json
import os
import hashlib
from datetime import datetime, timedelta
import yfinance as yf
from services.prices import to_yf_ticker
from services.bonds import is_bond, BOND_PARAMS

HISTORY_CACHE_DIR = "data/history_cache"


def _get_cache_key(portfolio_id: str, transactions: list) -> str:
    if not transactions:
        return f"{portfolio_id}_empty"
    last_tx = max(t["date"] for t in transactions)
    count = len(transactions)
    raw = f"{portfolio_id}_{count}_{last_tx}"
    return hashlib.md5(raw.encode()).hexdigest()


def _load_cache(cache_key: str):
    os.makedirs(HISTORY_CACHE_DIR, exist_ok=True)
    path = os.path.join(HISTORY_CACHE_DIR, f"{cache_key}.json")
    if not os.path.exists(path):
        return None
    if datetime.now().timestamp() - os.path.getmtime(path) > 900:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(cache_key: str, data: dict):
    os.makedirs(HISTORY_CACHE_DIR, exist_ok=True)
    path = os.path.join(HISTORY_CACHE_DIR, f"{cache_key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def _download_prices(yf_tickers: list, start_date, end_date) -> dict:
    """
    Pobiera historię cen dla listy tickerów.
    Obsługuje nowy format yfinance gdzie MultiIndex to (Price, Ticker).
    Zwraca dict: {yf_ticker: pd.Series}
    """
    try:
        df = yf.download(
            yf_tickers,
            start=start_date,
            end=end_date + timedelta(days=1),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return {}

        result = {}

        if len(yf_tickers) == 1:
            # Pojedynczy ticker — płaski DataFrame
            series = df["Close"].squeeze()
            series.index = pd.DatetimeIndex(series.index).tz_localize(None)
            result[yf_tickers[0]] = series
        else:
            # Wiele tickerów — sprawdź format MultiIndex
            close = df["Close"] if "Close" in df.columns.get_level_values(0) else df.xs("Close", axis=1, level=0)

            for yft in yf_tickers:
                try:
                    if yft in close.columns:
                        series = close[yft].squeeze()
                    else:
                        continue
                    series.index = pd.DatetimeIndex(series.index).tz_localize(None)
                    result[yft] = series
                except Exception as e:
                    print(f"Błąd ekstrakcji {yft}: {e}")

        return result

    except Exception as e:
        print(f"Błąd zbiorczego pobierania: {e}")
        return {}


def build_portfolio_history(portfolio_id: str = "default") -> dict:
    from services.portfolios import get_transactions_for
    transactions = get_transactions_for(portfolio_id)
    if not transactions:
        return {}

    cache_key = _get_cache_key(portfolio_id, transactions)
    cached = _load_cache(cache_key)
    if cached:
        return cached

    transactions = sorted(transactions, key=lambda x: x["date"])
    start_date = datetime.strptime(transactions[0]["date"], "%Y-%m-%d")
    end_date = datetime.now()
    dates = pd.date_range(start=start_date, end=end_date, freq="D")

    tickers = list({t["ticker"] for t in transactions})
    regular_tickers = [t for t in tickers if not is_bond(t)]
    bond_tickers = [t for t in tickers if is_bond(t)]

    prices_hist = {}

    # Pobierz zwykłe tickery zbiorczo
    if regular_tickers:
        yf_tickers = [to_yf_ticker(t) for t in regular_tickers]
        ticker_map = {to_yf_ticker(t): t for t in regular_tickers}

        downloaded = _download_prices(yf_tickers, start_date, end_date)

        if downloaded:
            for yft, series in downloaded.items():
                orig = ticker_map.get(yft)
                if orig:
                    prices_hist[orig] = series.reindex(dates, method="ffill")
        else:
            # Fallback — pobierz każdy ticker osobno
            print("Fallback: pobieranie tickerów osobno")
            for ticker in regular_tickers:
                try:
                    yft = to_yf_ticker(ticker)
                    df_s = yf.download(
                        yft,
                        start=start_date,
                        end=end_date + timedelta(days=1),
                        progress=False,
                        auto_adjust=True,
                    )
                    if not df_s.empty:
                        series = df_s["Close"].squeeze()
                        series.index = pd.DatetimeIndex(series.index).tz_localize(None)
                        prices_hist[ticker] = series.reindex(dates, method="ffill")
                except Exception as e:
                    print(f"Błąd fallback {ticker}: {e}")

    # Obligacje — własny model
    for ticker in bond_tickers:
        params = BOND_PARAMS.get(ticker.upper())
        if params:
            maturity, coupon_rate, bond_type = params
            approx_inflation = 4.5
            effective_rate = (
                (coupon_rate + approx_inflation) / 100
                if bond_type == "indexed"
                else coupon_rate / 100
            )
            prices = []
            for d in dates:
                days_held = (d - start_date).days
                accrued = 100 * effective_rate * (days_held / 365)
                prices.append(round(100 + accrued, 4))
            prices_hist[ticker] = pd.Series(prices, index=dates)

    if not prices_hist:
        return {}

    result = {ticker: [] for ticker in tickers}
    result["total"] = []
    result["invested"] = []
    result["dates"] = []

    holdings = {t: 0.0 for t in tickers}
    costs = {t: 0.0 for t in tickers}
    total_invested = 0.0
    tx_index = 0

    for date in dates:
        date_str = date.strftime("%Y-%m-%d")

        while tx_index < len(transactions) and transactions[tx_index]["date"] <= date_str:
            tx = transactions[tx_index]
            qty = float(tx["quantity"])
            price = float(tx["price"])
            comm = float(tx["commission"])
            if tx["type"] == "buy":
                holdings[tx["ticker"]] += qty
                costs[tx["ticker"]] += qty * price + comm
                total_invested += qty * price + comm
            elif tx["type"] == "sell":
                if holdings[tx["ticker"]] > 0:
                    avg = costs[tx["ticker"]] / holdings[tx["ticker"]]
                    holdings[tx["ticker"]] -= qty
                    costs[tx["ticker"]] -= avg * qty
                    total_invested -= avg * qty
            tx_index += 1

        total_value = 0.0
        for ticker in tickers:
            if ticker in prices_hist and date in prices_hist[ticker].index:
                price_today = prices_hist[ticker][date]
                if pd.notna(price_today) and holdings[ticker] > 0:
                    value = holdings[ticker] * float(price_today)
                    result[ticker].append(round(value, 2))
                    total_value += value
                else:
                    result[ticker].append(0)
            else:
                result[ticker].append(0)

        result["total"].append(round(total_value, 2))
        result["invested"].append(round(total_invested, 2))
        result["dates"].append(date_str)

    _save_cache(cache_key, result)
    return result


def get_benchmark_history(ticker: str, start_date: str, end_date: str) -> dict:
    TICKER_MAP = {"^WIG20": "WIG20.WA", "^WIG": "WIG.WA"}
    yf_ticker = TICKER_MAP.get(ticker, ticker)
    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        df = yf.download(
            yf_ticker,
            start=start_date,
            end=end_dt.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return {}
        series = df["Close"].squeeze()
        series.index = pd.DatetimeIndex(series.index).tz_localize(None)
        first_val = series.iloc[0]
        if first_val == 0:
            return {}
        normalized = (series / first_val * 100).round(2)
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in series.index],
            "values": normalized.tolist(),
        }
    except Exception as e:
        print(f"Błąd benchmarku {ticker}: {e}")
        return {}