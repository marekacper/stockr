"""
rebalancing.py — cele rebalancingu przechowywane w SQLite.
Tabela: rebalancing_targets (portfolio_id, category, target_pct)
"""

from services.portfolios import get_db, ensure_setup


def _ensure_table():
    ensure_setup()
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rebalancing_targets (
                portfolio_id TEXT NOT NULL,
                category     TEXT NOT NULL,
                target_pct   REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (portfolio_id, category)
            )
        """)


def load_targets(portfolio_id: str) -> dict:
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT category, target_pct FROM rebalancing_targets WHERE portfolio_id = ?",
            (portfolio_id,)
        ).fetchall()
    return {r["category"]: r["target_pct"] for r in rows}


def save_targets(portfolio_id: str, targets: dict):
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM rebalancing_targets WHERE portfolio_id = ?", (portfolio_id,))
        for category, pct in targets.items():
            conn.execute(
                "INSERT INTO rebalancing_targets (portfolio_id, category, target_pct) VALUES (?,?,?)",
                (portfolio_id, category, float(pct))
            )


def calculate_rebalancing(portfolio: dict, prices: dict, targets: dict) -> dict:
    from services.categories import get_category

    current = {}
    total_value = 0.0

    for ticker, pos in portfolio.items():
        price = prices.get(ticker)
        if not price:
            continue
        value = price * pos["quantity"]
        cat = get_category(ticker)
        current[cat] = current.get(cat, 0) + value
        total_value += value

    if total_value == 0:
        return {}

    current_pct = {cat: round(val / total_value * 100, 2) for cat, val in current.items()}

    suggestions = []
    all_cats = set(list(targets.keys()) + list(current.keys()))
    for cat in all_cats:
        target_pct = targets.get(cat, 0)
        actual_pct = current_pct.get(cat, 0)
        actual_value = current.get(cat, 0)
        target_value = total_value * target_pct / 100
        diff_pct = round(actual_pct - target_pct, 2)
        diff_value = round(actual_value - target_value, 2)
        suggestions.append({
            "category": cat,
            "target_pct": target_pct,
            "actual_pct": actual_pct,
            "diff_pct": diff_pct,
            "diff_value": diff_value,
            "action": "sprzedaj" if diff_value > 50 else "kup" if diff_value < -50 else "ok",
        })

    suggestions.sort(key=lambda x: abs(x["diff_value"]), reverse=True)

    return {
        "total_value": round(total_value, 2),
        "suggestions": suggestions,
        "current": current_pct,
    }