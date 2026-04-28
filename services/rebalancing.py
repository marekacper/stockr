import json
import os

TARGETS_FILE = "data/rebalancing_targets.json"


def load_targets(portfolio_id: str) -> dict:
    if not os.path.exists(TARGETS_FILE):
        return {}
    with open(TARGETS_FILE) as f:
        all_targets = json.load(f)
    return all_targets.get(portfolio_id, {})


def save_targets(portfolio_id: str, targets: dict):
    all_targets = {}
    if os.path.exists(TARGETS_FILE):
        with open(TARGETS_FILE) as f:
            all_targets = json.load(f)
    all_targets[portfolio_id] = targets
    with open(TARGETS_FILE, "w") as f:
        json.dump(all_targets, f, ensure_ascii=False, indent=2)


def calculate_rebalancing(portfolio: dict, prices: dict, targets: dict) -> dict:
    """
    Liczy odchylenia od docelowych wag i co kupić/sprzedać.
    targets: {"Akcje GPW": 40, "ETF": 40, "Obligacje": 20}  (sumy do 100)
    """
    from services.categories import get_category

    # Aktualne wartości per kategoria
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

    # Aktualne wagi %
    current_pct = {cat: round(val / total_value * 100, 2) for cat, val in current.items()}

    # Odchylenia i sugestie
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