import csv
import os
from collections import defaultdict
from datetime import datetime

TRANSACTIONS_FILE = "data/transactions.csv"
FIELDNAMES = ["ticker", "date", "type", "quantity", "price", "commission"]


def ensure_file():
    if not os.path.exists(TRANSACTIONS_FILE):
        with open(TRANSACTIONS_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def get_transactions() -> list[dict]:
    ensure_file()
    with open(TRANSACTIONS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return sorted(rows, key=lambda x: x["date"], reverse=True)


def add_transaction(ticker, date, type, quantity, price, commission):
    ensure_file()
    with open(TRANSACTIONS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow({
            "ticker": ticker,
            "date": date,
            "type": type,
            "quantity": float(quantity),
            "price": float(price),
            "commission": float(commission),
        })


def get_portfolio() -> dict:
    """Zwraca aktualny stan portfela (po uwzględnieniu kupna/sprzedaży)."""
    transactions = get_transactions()
    holdings = defaultdict(lambda: {"quantity": 0.0, "cost": 0.0})

    for t in reversed(transactions):  # od najstarszej
        ticker = t["ticker"]
        qty = float(t["quantity"])
        price = float(t["price"])
        commission = float(t["commission"])

        if t["type"] == "buy":
            holdings[ticker]["quantity"] += qty
            holdings[ticker]["cost"] += qty * price + commission
        elif t["type"] == "sell":
            if holdings[ticker]["quantity"] > 0:
                avg = holdings[ticker]["cost"] / holdings[ticker]["quantity"]
                holdings[ticker]["quantity"] -= qty
                holdings[ticker]["cost"] -= avg * qty

    # Usuń pozycje z zerową ilością
    return {
        k: {
            "quantity": round(v["quantity"], 4),
            "avg_price": round(v["cost"] / v["quantity"], 4) if v["quantity"] > 0 else 0,
            "cost": round(v["cost"], 2),
        }
        for k, v in holdings.items()
        if v["quantity"] > 0.0001
    }