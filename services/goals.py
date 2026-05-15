"""
goals.py — cele inwestycyjne przechowywane w SQLite.
Tabela: goals (id, portfolio_id, name, target, deadline, monthly_investment, created_at)
"""

import math
from datetime import datetime
from services.portfolios import get_db, ensure_setup


def _ensure_table():
    ensure_setup()
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id                TEXT PRIMARY KEY,
                portfolio_id      TEXT NOT NULL,
                name              TEXT NOT NULL,
                target            REAL NOT NULL,
                deadline          TEXT NOT NULL,
                monthly_investment REAL DEFAULT 0.0,
                created_at        TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_portfolio ON goals(portfolio_id)")


def load_goals(portfolio_id: str) -> list:
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, target, deadline, monthly_investment, created_at "
            "FROM goals WHERE portfolio_id = ? ORDER BY created_at",
            (portfolio_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_goals(portfolio_id: str, goals: list):
    """Zastępuje wszystkie cele portfela — używane przy usuwaniu."""
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM goals WHERE portfolio_id = ?", (portfolio_id,))
        for g in goals:
            conn.execute(
                "INSERT INTO goals (id, portfolio_id, name, target, deadline, monthly_investment, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (g["id"], portfolio_id, g["name"], float(g["target"]),
                 g["deadline"], float(g.get("monthly_investment", 0)),
                 g.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            )


def add_goal(portfolio_id: str, name: str, target: float, deadline: str, monthly_investment: float = 0) -> dict:
    _ensure_table()
    goal = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "portfolio_id": portfolio_id,
        "name": name,
        "target": float(target),
        "deadline": deadline,
        "monthly_investment": float(monthly_investment),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO goals (id, portfolio_id, name, target, deadline, monthly_investment, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (goal["id"], portfolio_id, goal["name"], goal["target"],
             goal["deadline"], goal["monthly_investment"], goal["created_at"])
        )
    return goal


def delete_goal(portfolio_id: str, goal_id: str):
    _ensure_table()
    with get_db() as conn:
        conn.execute("DELETE FROM goals WHERE id = ? AND portfolio_id = ?", (goal_id, portfolio_id))


def calculate_goal_progress(goal: dict, current_value: float, annual_return: float) -> dict:
    target = float(goal["target"])
    deadline = datetime.strptime(goal["deadline"], "%Y-%m-%d")
    now = datetime.now()
    years_left = max(0.01, (deadline - now).days / 365.25)

    progress_pct = round(current_value / target * 100, 1) if target > 0 else 0
    r = annual_return / 100 if annual_return else 0.07

    projected_value = current_value * ((1 + r) ** years_left)

    monthly_investment = float(goal.get("monthly_investment", 0))
    if monthly_investment > 0 and r > 0:
        monthly_r = r / 12
        months = years_left * 12
        fv_contributions = monthly_investment * ((1 + monthly_r) ** months - 1) / monthly_r
        projected_with_contributions = projected_value + fv_contributions
    else:
        projected_with_contributions = projected_value

    if r > 0 and years_left > 0:
        months = years_left * 12
        monthly_r = r / 12
        shortfall = max(0, target - projected_value)
        required_monthly = (shortfall * monthly_r / ((1 + monthly_r) ** months - 1)) if monthly_r > 0 else shortfall / months
    else:
        required_monthly = 0

    will_achieve = projected_with_contributions >= target

    years_to_goal = None
    if r > 0 and current_value > 0:
        if current_value >= target:
            years_to_goal = 0
        else:
            try:
                years_to_goal = math.log(target / current_value) / math.log(1 + r)
            except Exception:
                pass

    return {
        "progress_pct": progress_pct,
        "projected_value": round(projected_value, 2),
        "projected_with_contributions": round(projected_with_contributions, 2),
        "will_achieve": will_achieve,
        "required_monthly": round(required_monthly, 2),
        "years_left": round(years_left, 1),
        "years_to_goal": round(years_to_goal, 1) if years_to_goal is not None else None,
    }