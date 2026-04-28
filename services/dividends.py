import json
import os
import yfinance as yf
from datetime import datetime, date
from services.prices import to_yf_ticker

DIVIDENDS_FILE = "data/dividends.json"


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


def fetch_dividend_history(ticker: str, start_date: str) -> list:
    """Pobiera historię dywidend z yfinance."""
    try:
        yf_ticker = to_yf_ticker(ticker)
        t = yf.Ticker(yf_ticker)
        divs = t.dividends
        if divs.empty:
            return []
        divs.index = divs.index.tz_localize(None)
        divs = divs[divs.index >= start_date]
        return [
            {
                "date": d.strftime("%Y-%m-%d"),
                "amount_per_share": round(float(v), 4),
            }
            for d, v in zip(divs.index, divs.values)
        ]
    except Exception:
        return []


def get_dividend_summary(portfolio_id: str, portfolio: dict, prices: dict) -> dict:
    from services.portfolios import get_transactions_for
    from collections import defaultdict

    transactions = get_transactions_for(portfolio_id)

    # Buduj historię posiadanych akcji per ticker per dzień
    # Dla każdego tickera: lista (data_od, data_do, ilość)
    def get_holding_at_date(ticker: str, date_str: str) -> float:
        """Zwraca ile akcji tickera miałem w danym dniu."""
        qty = 0.0
        for tx in sorted(transactions, key=lambda x: x["date"]):
            if tx["ticker"] != ticker:
                continue
            if tx["date"] > date_str:
                break
            if tx["type"] == "buy":
                qty += float(tx["quantity"])
            elif tx["type"] == "sell":
                qty -= float(tx["quantity"])
        return max(0.0, qty)

    auto_dividends = []
    annual_forecast = 0.0
    manual = load_dividends(portfolio_id)

    for ticker, pos in portfolio.items():
        if pos["quantity"] <= 0:
            continue
        try:
            yf_ticker = to_yf_ticker(ticker)
            t = yf.Ticker(yf_ticker)

            # Prognoza roczna
            info = t.fast_info
            div_yield = getattr(info, 'dividend_yield', None) or 0
            current_price = prices.get(ticker)
            if current_price and div_yield:
                annual_forecast += current_price * div_yield * pos["quantity"]

            # Historia dywidend — tylko te gdy miałem spółkę
            divs = t.dividends
            if divs.empty:
                continue
            divs.index = divs.index.tz_localize(None)

            for div_date, div_per_share in zip(divs.index, divs.values):
                date_str = div_date.strftime("%Y-%m-%d")
                qty_at_date = get_holding_at_date(ticker, date_str)
                if qty_at_date <= 0:
                    continue  # nie miałem spółki w tym dniu
                amount = round(float(div_per_share) * qty_at_date, 2)
                auto_dividends.append({
                    "ticker": ticker,
                    "date": date_str,
                    "amount": amount,
                    "amount_per_share": round(float(div_per_share), 4),
                    "quantity": qty_at_date,
                    "source": "auto",
                })
        except Exception:
            pass

    all_dividends = manual + auto_dividends
    all_dividends.sort(key=lambda x: x["date"], reverse=True)

    by_year = {}
    for d in all_dividends:
        year = d["date"][:4]
        by_year[year] = by_year.get(year, 0) + d["amount"]

    heatmap = {}
    for d in all_dividends:
        key = d["date"][:7]
        heatmap[key] = heatmap.get(key, 0) + d["amount"]

    total_received = sum(d["amount"] for d in all_dividends)

    return {
        "dividends": all_dividends[:50],
        "by_year": {k: round(v, 2) for k, v in by_year.items()},
        "heatmap": {k: round(v, 2) for k, v in heatmap.items()},
        "total_received": round(total_received, 2),
        "annual_forecast": round(annual_forecast, 2),
        "monthly_forecast": round(annual_forecast / 12, 2),
    }