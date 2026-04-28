import json
import os
import csv
import shutil
from datetime import datetime

PORTFOLIOS_FILE = "data/portfolios.json"
PORTFOLIOS_DIR = "data/portfolios"
LEGACY_FILE = "data/transactions.csv"
FIELDNAMES = ["ticker", "date", "type", "quantity", "price", "commission"]


def ensure_setup():
    """Tworzy strukturę folderów i migruje stare transakcje."""
    os.makedirs(PORTFOLIOS_DIR, exist_ok=True)

    # Migracja: przenieś stary transactions.csv do portfolios/default.csv
    default_path = os.path.join(PORTFOLIOS_DIR, "default.csv")
    if os.path.exists(LEGACY_FILE) and not os.path.exists(default_path):
        shutil.copy(LEGACY_FILE, default_path)

    # Utwórz domyślny portfel jeśli brak
    if not os.path.exists(PORTFOLIOS_FILE):
        portfolios = [{"id": "default", "name": "Główny portfel", "description": "", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]
        save_portfolios(portfolios)

    # Utwórz plik CSV dla domyślnego portfela jeśli brak
    if not os.path.exists(default_path):
        with open(default_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def load_portfolios() -> list[dict]:
    ensure_setup()
    with open(PORTFOLIOS_FILE) as f:
        return json.load(f)


def save_portfolios(portfolios: list[dict]):
    os.makedirs("data", exist_ok=True)
    with open(PORTFOLIOS_FILE, "w") as f:
        json.dump(portfolios, f, ensure_ascii=False, indent=2)


def get_portfolio_path(portfolio_id: str) -> str:
    return os.path.join(PORTFOLIOS_DIR, f"{portfolio_id}.csv")


def create_portfolio(name: str, description: str = "") -> dict:
    portfolios = load_portfolios()
    # Generuj unikalne ID ze nazwy
    base_id = name.lower().replace(" ", "_").replace("/", "_")
    base_id = "".join(c for c in base_id if c.isalnum() or c == "_")
    portfolio_id = base_id
    existing_ids = {p["id"] for p in portfolios}
    counter = 2
    while portfolio_id in existing_ids:
        portfolio_id = f"{base_id}_{counter}"
        counter += 1

    new_portfolio = {
        "id": portfolio_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    portfolios.append(new_portfolio)
    save_portfolios(portfolios)

    # Utwórz pusty plik CSV
    path = get_portfolio_path(portfolio_id)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

    return new_portfolio


def delete_portfolio(portfolio_id: str) -> bool:
    if portfolio_id == "default":
        return False  # Nie można usunąć domyślnego
    portfolios = load_portfolios()
    portfolios = [p for p in portfolios if p["id"] != portfolio_id]
    save_portfolios(portfolios)
    path = get_portfolio_path(portfolio_id)
    if os.path.exists(path):
        os.remove(path)
    return True


def get_transactions_for(portfolio_id: str) -> list[dict]:
    ensure_setup()
    path = get_portfolio_path(portfolio_id)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda x: x["date"], reverse=True)


def add_transaction_to(portfolio_id: str, ticker, date, type, quantity, price, commission):
    ensure_setup()
    path = get_portfolio_path(portfolio_id)
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow({
            "ticker": ticker,
            "date": date,
            "type": type,
            "quantity": float(quantity),
            "price": float(price),
            "commission": float(commission),
        })


def get_portfolio_holdings(portfolio_id: str) -> dict:
    from collections import defaultdict
    transactions = get_transactions_for(portfolio_id)
    holdings = defaultdict(lambda: {"quantity": 0.0, "cost": 0.0})

    for t in reversed(transactions):
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

    return {
        k: {
            "quantity": round(v["quantity"], 4),
            "avg_price": round(v["cost"] / v["quantity"], 4) if v["quantity"] > 0 else 0,
            "cost": round(v["cost"], 2),
        }
        for k, v in holdings.items()
        if v["quantity"] > 0.0001
    }


def merge_transactions_to(portfolio_id: str, new_rows: list[dict]) -> dict:
    existing = get_transactions_for(portfolio_id)

    def make_key(t):
        return (t["ticker"], t["date"], t["type"], str(t["quantity"]), str(t["price"]))

    existing_keys = {make_key(t) for t in existing}
    added = 0
    skipped = 0

    path = get_portfolio_path(portfolio_id)
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        for row in new_rows:
            key = make_key(row)
            if key not in existing_keys:
                writer.writerow(row)
                existing_keys.add(key)
                added += 1
            else:
                skipped += 1

    return {"added": added, "skipped": skipped}