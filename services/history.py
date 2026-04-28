import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from services.portfolio import get_transactions
import yfinance as yf
from services.prices import to_yf_ticker
from services.bonds import is_bond, BOND_PARAMS


def get_deposit_history() -> list[dict]:
    from services.portfolio import TRANSACTIONS_FILE
    import csv, os
    if not os.path.exists(TRANSACTIONS_FILE):
        return []
    with open(TRANSACTIONS_FILE) as f:
        rows = list(csv.DictReader(f))
    return rows


def build_portfolio_history(portfolio_id: str = "default") -> dict:
    from services.portfolios import get_transactions_for
    transactions = get_transactions_for(portfolio_id)
    if not transactions:
        return {}

    transactions = sorted(transactions, key=lambda x: x["date"])
    start_date = datetime.strptime(transactions[0]["date"], "%Y-%m-%d")
    end_date = datetime.now()

    tickers = list({t["ticker"] for t in transactions})
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    prices_hist = {}

    for ticker in tickers:
        try:
            if is_bond(ticker):
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
                        if days_held < 0:
                            prices.append(np.nan)
                        else:
                            accrued = 100 * effective_rate * (days_held / 365)
                            prices.append(round(100 + accrued, 4))
                    prices_hist[ticker] = pd.Series(prices, index=dates)
                continue

            yf_ticker = to_yf_ticker(ticker)
            df = yf.download(
                yf_ticker,
                start=start_date,
                end=end_date + timedelta(days=1),
                progress=False,
                auto_adjust=True,
            )
            if not df.empty:
                series = df["Close"].squeeze()
                series.index = pd.DatetimeIndex(series.index).tz_localize(None)
                prices_hist[ticker] = series.reindex(dates, method="ffill")
        except Exception as e:
            print(f"Błąd historii {ticker}: {e}")

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

    return result


def get_benchmark_history(ticker: str, start_date: str, end_date: str) -> dict:
    TICKER_MAP = {
        "^WIG20": "WIG20.WA",
        "^WIG": "WIG.WA",
    }
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
        print(f"Błąd benchmarku {ticker} ({yf_ticker}): {e}")
        return {}