import json
import os
from datetime import datetime

GOALS_FILE = "data/goals.json"


def load_goals(portfolio_id: str) -> list:
    if not os.path.exists(GOALS_FILE):
        return []
    with open(GOALS_FILE) as f:
        data = json.load(f)
    return data.get(portfolio_id, [])


def save_goals(portfolio_id: str, goals: list):
    data = {}
    if os.path.exists(GOALS_FILE):
        with open(GOALS_FILE) as f:
            data = json.load(f)
    data[portfolio_id] = goals
    with open(GOALS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def calculate_goal_progress(goal: dict, current_value: float, annual_return: float, monthly_investment: float = 0) -> dict:
    """
    Liczy postęp do celu i czy go osiągniesz w terminie.
    goal: {"name": "...", "target": 500000, "deadline": "2035-01-01"}
    """
    target = goal["target"]
    deadline = datetime.strptime(goal["deadline"], "%Y-%m-%d")
    now = datetime.now()

    years_left = (deadline - now).days / 365.25
    if years_left <= 0:
        years_left = 0.01

    progress_pct = round(current_value / target * 100, 1) if target > 0 else 0

    # Prognoza przy obecnym tempie (bez dodatkowych wpłat)
    r = annual_return / 100 if annual_return else 0.07  # domyślnie 7% jeśli brak danych
    projected_value = current_value * ((1 + r) ** years_left)

    # Z miesięcznymi wpłatami (wzór FV annuity)
    if monthly_investment > 0 and r > 0:
        monthly_r = r / 12
        months = years_left * 12
        fv_contributions = monthly_investment * ((1 + monthly_r) ** months - 1) / monthly_r
        projected_with_contributions = projected_value + fv_contributions
    else:
        projected_with_contributions = projected_value

    # Ile miesięcznie trzeba dokładać żeby osiągnąć cel
    if r > 0 and years_left > 0:
        months = years_left * 12
        monthly_r = r / 12
        shortfall = max(0, target - projected_value)
        if monthly_r > 0:
            required_monthly = shortfall * monthly_r / ((1 + monthly_r) ** months - 1)
        else:
            required_monthly = shortfall / months
    else:
        required_monthly = 0

    will_achieve = projected_with_contributions >= target

    # Kiedy osiągniesz cel przy obecnym tempie
    if r > 0 and current_value > 0:
        if current_value >= target:
            years_to_goal = 0
        else:
            import math
            try:
                years_to_goal = math.log(target / current_value) / math.log(1 + r)
            except Exception:
                years_to_goal = None
    else:
        years_to_goal = None

    return {
        "progress_pct": progress_pct,
        "projected_value": round(projected_value, 2),
        "projected_with_contributions": round(projected_with_contributions, 2),
        "will_achieve": will_achieve,
        "required_monthly": round(required_monthly, 2),
        "years_left": round(years_left, 1),
        "years_to_goal": round(years_to_goal, 1) if years_to_goal else None,
    }