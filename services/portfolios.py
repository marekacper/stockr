

import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "data/stockr.db"


# ---------------------------------------------------------------------------
# Połączenie z bazą
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # lepsza wydajność przy wielu odczytach
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inicjalizacja schematu
# ---------------------------------------------------------------------------

def ensure_setup():
    """Tworzy tabele jeśli nie istnieją i dodaje domyślny portfel."""
    os.makedirs("data", exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolios (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id TEXT NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                ticker      TEXT NOT NULL,
                date        TEXT NOT NULL,
                type        TEXT NOT NULL CHECK(type IN ('buy','sell')),
                quantity    REAL NOT NULL,
                price       REAL NOT NULL,
                commission  REAL NOT NULL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_tx_portfolio ON transactions(portfolio_id);
            CREATE INDEX IF NOT EXISTS idx_tx_date      ON transactions(portfolio_id, date);
            CREATE INDEX IF NOT EXISTS idx_tx_ticker    ON transactions(portfolio_id, ticker);
        """)

        # Domyślny portfel
        exists = conn.execute(
            "SELECT 1 FROM portfolios WHERE id = 'default'"
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO portfolios (id, name, description, created_at) VALUES (?,?,?,?)",
                ("default", "Główny portfel", "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )


# ---------------------------------------------------------------------------
# Portfele
# ---------------------------------------------------------------------------

def load_portfolios() -> list[dict]:
    ensure_setup()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, description, created_at FROM portfolios ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def save_portfolios(portfolios: list[dict]):
    """Kompatybilność wsteczna — nie używana bezpośrednio w nowym kodzie."""
    pass


def create_portfolio(name: str, description: str = "") -> dict:
    ensure_setup()
    base_id = name.lower().replace(" ", "_").replace("/", "_")
    base_id = "".join(c for c in base_id if c.isalnum() or c == "_")
    portfolio_id = base_id

    with get_db() as conn:
        existing = {r[0] for r in conn.execute("SELECT id FROM portfolios").fetchall()}
        counter = 2
        while portfolio_id in existing:
            portfolio_id = f"{base_id}_{counter}"
            counter += 1

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO portfolios (id, name, description, created_at) VALUES (?,?,?,?)",
            (portfolio_id, name, description, created_at)
        )

    return {"id": portfolio_id, "name": name, "description": description, "created_at": created_at}


def delete_portfolio(portfolio_id: str) -> bool:
    if portfolio_id == "default":
        return False
    with get_db() as conn:
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
    return True


# ---------------------------------------------------------------------------
# Transakcje
# ---------------------------------------------------------------------------

def get_transactions_for(portfolio_id: str) -> list[dict]:
    ensure_setup()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT ticker, date, type,
                      ROUND(quantity, 4)   AS quantity,
                      ROUND(price, 4)      AS price,
                      ROUND(commission, 4) AS commission
               FROM transactions
               WHERE portfolio_id = ?
               ORDER BY date DESC, id DESC""",
            (portfolio_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_transaction_to(portfolio_id: str, ticker, date, type, quantity, price, commission):
    ensure_setup()
    with get_db() as conn:
        # Upewnij się że portfel istnieje
        exists = conn.execute(
            "SELECT 1 FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO portfolios (id, name, description, created_at) VALUES (?,?,?,?)",
                (portfolio_id, portfolio_id, "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        conn.execute(
            """INSERT INTO transactions (portfolio_id, ticker, date, type, quantity, price, commission)
               VALUES (?,?,?,?,?,?,?)""",
            (portfolio_id, ticker, date, type, float(quantity), float(price), float(commission))
        )


def merge_transactions_to(portfolio_id: str, new_rows: list[dict]) -> dict:
    """Scala nowe transakcje z istniejącymi, pomija duplikaty."""
    ensure_setup()
    existing = get_transactions_for(portfolio_id)

    def make_key(t):
        return (
            t["ticker"], t["date"], t["type"],
            round(float(t["quantity"]), 4),
            round(float(t["price"]), 4),
        )

    existing_keys = {make_key(t) for t in existing}
    added = 0
    skipped = 0

    with get_db() as conn:
        # Upewnij się że portfel istnieje
        exists = conn.execute(
            "SELECT 1 FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO portfolios (id, name, description, created_at) VALUES (?,?,?,?)",
                (portfolio_id, portfolio_id, "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

        for row in new_rows:
            key = make_key(row)
            if key not in existing_keys:
                conn.execute(
                    """INSERT INTO transactions (portfolio_id, ticker, date, type, quantity, price, commission)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        portfolio_id,
                        row["ticker"],
                        row["date"],
                        row["type"],
                        float(row["quantity"]),
                        float(row["price"]),
                        float(row.get("commission", 0.0)),
                    )
                )
                existing_keys.add(key)
                added += 1
            else:
                skipped += 1

    return {"added": added, "skipped": skipped}


# ---------------------------------------------------------------------------
# Holdings (stan portfela)
# ---------------------------------------------------------------------------

def get_portfolio_holdings(portfolio_id: str) -> dict:
    """Oblicza aktualny stan portfela na podstawie transakcji."""
    from collections import defaultdict
    transactions = get_transactions_for(portfolio_id)
    holdings = defaultdict(lambda: {"quantity": 0.0, "cost": 0.0})

    for t in reversed(transactions):   # od najstarszej
        ticker     = t["ticker"]
        qty        = float(t["quantity"])
        price      = float(t["price"])
        commission = float(t["commission"])

        if t["type"] == "buy":
            holdings[ticker]["quantity"] += qty
            holdings[ticker]["cost"]     += qty * price + commission
        elif t["type"] == "sell":
            if holdings[ticker]["quantity"] > 0:
                avg = holdings[ticker]["cost"] / holdings[ticker]["quantity"]
                holdings[ticker]["quantity"] -= qty
                holdings[ticker]["cost"]     -= avg * qty

    return {
        k: {
            "quantity":  round(v["quantity"], 4),
            "avg_price": round(v["cost"] / v["quantity"], 4) if v["quantity"] > 0 else 0,
            "cost":      round(v["cost"], 2),
        }
        for k, v in holdings.items()
        if v["quantity"] > 0.0001
    }