import json
import os
from datetime import datetime

ALERTS_FILE = "data/alerts.json"


def load_alerts(portfolio_id: str) -> list:
    if not os.path.exists(ALERTS_FILE):
        return []
    with open(ALERTS_FILE) as f:
        data = json.load(f)
    return data.get(portfolio_id, [])


def save_alerts(portfolio_id: str, alerts: list):
    data = {}
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE) as f:
            data = json.load(f)
    data[portfolio_id] = alerts
    with open(ALERTS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_alert(portfolio_id: str, alert_type: str, ticker: str = None,
              condition: str = "below", value: float = 0, name: str = "") -> dict:
    alerts = load_alerts(portfolio_id)
    alert = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "type": alert_type,
        "ticker": ticker,
        "condition": condition,
        "value": value,
        "name": name or f"{ticker or 'Portfel'} {condition} {value}",
        "active": True,
        "triggered": False,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    alerts.append(alert)
    save_alerts(portfolio_id, alerts)
    return alert


def delete_alert(portfolio_id: str, alert_id: str):
    alerts = load_alerts(portfolio_id)
    alerts = [a for a in alerts if a["id"] != alert_id]
    save_alerts(portfolio_id, alerts)


def check_alerts(portfolio_id: str, portfolio: dict, prices: dict,
                 total_value: float, total_pnl_pct: float) -> list:
    alerts = load_alerts(portfolio_id)
    triggered = []
    changed = False

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

        fired = False
        if alert["condition"] == "below" and current_val <= alert["value"]:
            fired = True
        elif alert["condition"] == "above" and current_val >= alert["value"]:
            fired = True

        if fired:
            alert["triggered"] = True
            alert["triggered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            alert["current_value"] = round(current_val, 2)
            triggered.append(alert)
            changed = True

    if changed:
        save_alerts(portfolio_id, alerts)

    return triggered