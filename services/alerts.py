"""
alerts.py — alerty cenowe przechowywane w SQLite.
Tabela: alerts (id, portfolio_id, type, ticker, condition, value, name, active, triggered, ...)
"""

from datetime import datetime
from services.portfolios import get_db, ensure_setup


def _ensure_table():
    ensure_setup()
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id           TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                type         TEXT NOT NULL,
                ticker       TEXT,
                condition    TEXT NOT NULL,
                value        REAL NOT NULL,
                name         TEXT NOT NULL,
                active       INTEGER DEFAULT 1,
                triggered    INTEGER DEFAULT 0,
                triggered_at TEXT,
                current_value REAL,
                created_at   TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_portfolio ON alerts(portfolio_id)")


def load_alerts(portfolio_id: str) -> list:
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, type, ticker, condition, value, name, active, triggered, "
            "triggered_at, current_value, created_at "
            "FROM alerts WHERE portfolio_id = ? ORDER BY created_at DESC",
            (portfolio_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_alert(portfolio_id: str, alert_type: str, ticker: str = None,
              condition: str = "below", value: float = 0, name: str = "") -> dict:
    _ensure_table()
    alert = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "type": alert_type,
        "ticker": ticker,
        "condition": condition,
        "value": value,
        "name": name or f"{ticker or 'Portfel'} {condition} {value}",
        "active": 1,
        "triggered": 0,
        "triggered_at": None,
        "current_value": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO alerts (id, portfolio_id, type, ticker, condition, value, name, active, triggered, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (alert["id"], portfolio_id, alert["type"], alert["ticker"],
             alert["condition"], alert["value"], alert["name"],
             alert["active"], alert["triggered"], alert["created_at"])
        )
    return alert


def delete_alert(portfolio_id: str, alert_id: str):
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM alerts WHERE id = ? AND portfolio_id = ?", (alert_id, portfolio_id))


def check_alerts(portfolio_id: str, portfolio: dict, prices: dict,
                 total_value: float, total_pnl_pct: float) -> list:
    _ensure_table()
    alerts = load_alerts(portfolio_id)
    triggered = []

    with get_db() as conn:
        for alert in alerts:
            if not alert.get("active"):
                continue

            current_val = None
            if alert["type"] == "price" and alert.get("ticker"):
                current_val = prices.get(alert["ticker"])
            elif alert["type"] == "portfolio_value":
                current_val = total_value
            elif alert["type"] == "portfolio_pnl_pct":
                current_val = total_pnl_pct

            if current_val is None:
                continue

            fired = (
                (alert["condition"] == "below" and current_val <= alert["value"]) or
                (alert["condition"] == "above" and current_val >= alert["value"])
            )

            if fired:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                conn.execute(
                    "UPDATE alerts SET triggered=1, triggered_at=?, current_value=? WHERE id=?",
                    (now, round(current_val, 2), alert["id"])
                )
                alert["triggered"] = 1
                alert["triggered_at"] = now
                alert["current_value"] = round(current_val, 2)
                triggered.append(alert)

    return triggered