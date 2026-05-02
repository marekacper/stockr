from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from typing import List
import tempfile, os, shutil, json
import uvicorn
from datetime import datetime
import numpy as np

from services.portfolios import (
    load_portfolios, create_portfolio, delete_portfolio,
    get_transactions_for, get_portfolio_holdings,
    merge_transactions_to, add_transaction_to, ensure_setup
)
from services.prices import get_prices, to_yf_ticker
from services.importer import parse_xtb_xlsx
from services.history import build_portfolio_history, get_benchmark_history

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- Pomocnicze ---

def _portfolio_context(portfolio_id: str):
    """Zwraca portfolio, ceny i podstawowe obliczenia. Wywołuj raz per request."""
    portfolio = get_portfolio_holdings(portfolio_id)
    tickers = list(portfolio.keys())
    prices = get_prices(tickers) if tickers else {}
    total_value = sum(prices[t] * portfolio[t]["quantity"] for t in tickers if prices.get(t))
    total_cost = sum(portfolio[t]["cost"] for t in tickers)
    return portfolio, tickers, prices, total_value, total_cost


# --- Strony ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, portfolio_id: str = "default"):
    ensure_setup()
    portfolios = load_portfolios()
    portfolio, tickers, prices, total_value, total_cost = _portfolio_context(portfolio_id)
    total_pnl = total_value - total_cost
    current = next((p for p in portfolios if p["id"] == portfolio_id), portfolios[0])

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "portfolio": portfolio,
            "prices": prices,
            "tickers": tickers,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "portfolios": portfolios,
            "current_portfolio": current,
            "portfolio_id": portfolio_id,
        }
    )


@app.get("/table", response_class=HTMLResponse)
async def table(request: Request, portfolio_id: str = "default"):
    ensure_setup()
    portfolios = load_portfolios()
    portfolio, tickers, prices, _, _ = _portfolio_context(portfolio_id)
    transactions = get_transactions_for(portfolio_id)
    current = next((p for p in portfolios if p["id"] == portfolio_id), portfolios[0])

    return templates.TemplateResponse(
        request=request,
        name="portfolio.html",
        context={
            "portfolio": portfolio,
            "prices": prices,
            "transactions": transactions,
            "portfolios": portfolios,
            "current_portfolio": current,
            "portfolio_id": portfolio_id,
        }
    )


@app.get("/add", response_class=HTMLResponse)
async def add_form(request: Request, portfolio_id: str = "default"):
    ensure_setup()
    portfolios = load_portfolios()
    return templates.TemplateResponse(
        request=request,
        name="add_transaction.html",
        context={"portfolio_id": portfolio_id, "portfolios": portfolios}
    )


@app.post("/add")
async def add(
    ticker: str = Form(...),
    date: str = Form(...),
    type: str = Form(...),
    quantity: float = Form(...),
    price: float = Form(...),
    commission: float = Form(0.0),
    portfolio_id: str = Form("default"),
):
    add_transaction_to(portfolio_id, ticker.upper(), date, type, quantity, price, commission)
    return RedirectResponse(f"/dashboard?portfolio_id={portfolio_id}", status_code=303)


@app.get("/upload", response_class=HTMLResponse)
async def upload_form(request: Request):
    ensure_setup()
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"result": None, "portfolios": load_portfolios()}
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    portfolio_id: str = Form("default")
):
    IMPORTS_DIR = "data/imports"
    IMPORTS_META = "data/imports_meta.json"
    os.makedirs(IMPORTS_DIR, exist_ok=True)

    meta = []
    if os.path.exists(IMPORTS_META):
        with open(IMPORTS_META) as f:
            meta = json.load(f)

    portfolios = load_portfolios()
    portfolio_name = next((p["name"] for p in portfolios if p["id"] == portfolio_id), portfolio_id)

    result = []
    for file in files:
        tmp_path = None
        try:
            suffix = os.path.splitext(file.filename)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await file.read())
                tmp_path = tmp.name

            if suffix == '.xlsx':
                rows = parse_xtb_xlsx(tmp_path)
                file_type = "XTB"
            elif suffix == '.xls':
                from services.importer import parse_obligacje_xls
                rows = parse_obligacje_xls(tmp_path)
                file_type = "Obligacje"
            else:
                raise ValueError(f"Nieobsługiwany format: {suffix}")

            stats = merge_transactions_to(portfolio_id, rows)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{timestamp}_{file.filename}"
            shutil.copy(tmp_path, os.path.join(IMPORTS_DIR, archive_name))

            meta.append({
                "id": timestamp,
                "filename": file.filename,
                "archive": archive_name,
                "added": stats["added"],
                "skipped": stats["skipped"],
                "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type": file_type,
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio_name,
            })
            result.append({"filename": file.filename, **stats})
        except Exception as e:
            result.append({"filename": file.filename, "added": 0, "skipped": 0, "error": str(e)})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    with open(IMPORTS_META, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Wyczyść cache historii po imporcie
    _clear_history_cache(portfolio_id)

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"result": result, "portfolios": load_portfolios()}
    )


def _clear_history_cache(portfolio_id: str):
    import glob
    cache_dir = "data/history_cache"
    if os.path.exists(cache_dir):
        for f in glob.glob(os.path.join(cache_dir, "*.json")):
            try:
                os.remove(f)
            except Exception:
                pass
    # Wyczyść też cache dywidend
    from services.dividends import clear_div_cache
    clear_div_cache()


# --- API ---

@app.get("/api/history")
async def api_history(portfolio_id: str = "default"):
    return build_portfolio_history(portfolio_id)


@app.get("/api/benchmark")
async def api_benchmark(ticker: str, start: str, end: str):
    return get_benchmark_history(ticker, start, end)


@app.get("/api/daily")
async def api_daily(portfolio_id: str = "default"):
    """Zwraca dzienny stan portfela. Używa cache cen."""
    portfolio, tickers, prices, _, _ = _portfolio_context(portfolio_id)
    result = []
    for ticker, pos in portfolio.items():
        current = prices.get(ticker)
        value = round(current * pos["quantity"], 2) if current else None
        pnl = round(value - pos["cost"], 2) if value else None
        result.append({
            "ticker": ticker,
            "quantity": pos["quantity"],
            "avg_price": pos["avg_price"],
            "current_price": current,
            "value": value,
            "cost": pos["cost"],
            "pnl": pnl,
            "daily_change": None,  # obliczane osobno jeśli potrzebne
        })
    result.sort(key=lambda x: x["value"] or 0, reverse=True)
    return result


@app.get("/api/transactions")
async def api_transactions(portfolio_id: str = "default"):
    return get_transactions_for(portfolio_id)


@app.get("/api/portfolios")
async def api_portfolios():
    ensure_setup()
    return load_portfolios()


@app.post("/api/portfolios")
async def api_create_portfolio(request: Request):
    data = await request.json()
    p = create_portfolio(data.get("name", "Nowy portfel"), data.get("description", ""))
    return p


@app.delete("/api/portfolios/{portfolio_id}")
async def api_delete_portfolio(portfolio_id: str):
    ok = delete_portfolio(portfolio_id)
    return {"ok": ok, "error": "Nie można usunąć domyślnego portfela" if not ok else None}


@app.get("/api/imports")
async def api_imports():
    IMPORTS_META = "data/imports_meta.json"
    if not os.path.exists(IMPORTS_META):
        return []
    with open(IMPORTS_META) as f:
        return json.load(f)


@app.delete("/api/imports/{import_id}")
async def delete_import(import_id: str):
    IMPORTS_META = "data/imports_meta.json"
    IMPORTS_DIR = "data/imports"
    if not os.path.exists(IMPORTS_META):
        return {"ok": False}
    with open(IMPORTS_META) as f:
        meta = json.load(f)
    entry = next((m for m in meta if m["id"] == import_id), None)
    if not entry:
        return {"ok": False, "error": "Nie znaleziono"}
    archive_path = os.path.join(IMPORTS_DIR, entry["archive"])
    if os.path.exists(archive_path):
        os.remove(archive_path)
    meta = [m for m in meta if m["id"] != import_id]
    with open(IMPORTS_META, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return {"ok": True}


@app.get("/api/categories")
async def api_categories(portfolio_id: str = "default"):
    from services.categories import get_categories_summary
    portfolio, tickers, prices, _, _ = _portfolio_context(portfolio_id)
    return get_categories_summary(portfolio, prices)


@app.get("/api/analytics")
async def api_analytics(portfolio_id: str = "default"):
    from services.analytics import calculate_drawdown, calculate_risk_metrics
    data = build_portfolio_history(portfolio_id)
    if not data or not data.get("total"):
        return {}
    dd = calculate_drawdown(data["total"])
    metrics = calculate_risk_metrics(data["total"], data["invested"], data["dates"])
    return {
        "dates": data["dates"],
        "drawdown": dd["drawdown"],
        "max_drawdown": dd["max_drawdown"],
        "peak_idx": dd["peak_idx"],
        "trough_idx": dd["trough_idx"],
        "metrics": metrics,
    }


@app.get("/api/ticker/{ticker}")
async def api_ticker_history(ticker: str, portfolio_id: str = "default"):
    import yfinance as yf
    from datetime import timedelta

    transactions = get_transactions_for(portfolio_id)
    ticker_txs = [t for t in transactions if t["ticker"] == ticker]

    if not ticker_txs:
        return {"error": "Brak transakcji dla tego tickera"}

    start = min(t["date"] for t in ticker_txs)
    start_dt = datetime.strptime(start, "%Y-%m-%d") - timedelta(days=7)

    try:
        df = yf.download(
            to_yf_ticker(ticker),
            start=start_dt.strftime("%Y-%m-%d"),
            end=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True
        )
        if df.empty:
            return {"error": "Brak danych cenowych"}

        series = df["Close"].squeeze()
        prices_hist = [
            {"date": d.strftime("%Y-%m-%d"), "price": round(float(p), 2)}
            for d, p in zip(series.index, series.values)
            if not np.isnan(p)
        ]
    except Exception as e:
        return {"error": str(e)}

    return {
        "ticker": ticker,
        "prices": prices_hist,
        "transactions": [
            {
                "date": t["date"],
                "type": t["type"],
                "quantity": float(t["quantity"]),
                "price": float(t["price"]),
            }
            for t in sorted(ticker_txs, key=lambda x: x["date"])
        ]
    }


@app.get("/api/correlation")
async def api_correlation(portfolio_id: str = "default"):
    from services.analytics import calculate_correlation
    data = build_portfolio_history(portfolio_id)
    if not data:
        return {}
    return calculate_correlation(data)


@app.get("/api/rebalancing")
async def api_rebalancing(portfolio_id: str = "default"):
    from services.rebalancing import load_targets, calculate_rebalancing
    portfolio, tickers, prices, _, _ = _portfolio_context(portfolio_id)
    targets = load_targets(portfolio_id)
    return calculate_rebalancing(portfolio, prices, targets)


@app.post("/api/rebalancing")
async def api_save_rebalancing(portfolio_id: str, request: Request):
    from services.rebalancing import save_targets
    data = await request.json()
    save_targets(portfolio_id, data.get("targets", {}))
    return {"ok": True}


@app.get("/api/montecarlo")
async def api_montecarlo(
    portfolio_id: str = "default",
    years: int = 5,
    monthly: float = 0
):
    from services.analytics import monte_carlo_simulation
    data = build_portfolio_history(portfolio_id)
    if not data or not data.get("total"):
        return {}
    return monte_carlo_simulation(data["total"], data["invested"], years, 1000, monthly)


@app.get("/api/dividends")
async def api_dividends(portfolio_id: str = "default"):
    from services.dividends import get_dividend_summary
    portfolio, tickers, prices, _, _ = _portfolio_context(portfolio_id)
    return get_dividend_summary(portfolio_id, portfolio, prices)


@app.post("/api/dividends")
async def api_add_dividend(portfolio_id: str, request: Request):
    from services.dividends import add_manual_dividend
    data = await request.json()
    add_manual_dividend(portfolio_id, data["ticker"], data["amount"], data["date"])
    return {"ok": True}


@app.get("/api/goals")
async def api_goals(portfolio_id: str = "default"):
    from services.goals import load_goals, calculate_goal_progress
    from services.analytics import calculate_risk_metrics
    goals = load_goals(portfolio_id)
    portfolio, tickers, prices, total_value, _ = _portfolio_context(portfolio_id)
    hist = build_portfolio_history(portfolio_id)
    metrics = calculate_risk_metrics(
        hist.get("total", []), hist.get("invested", []), hist.get("dates", [])
    ) if hist else {}
    annual_return = metrics.get("annual_return", 7.0)
    return [{**goal, **calculate_goal_progress(goal, total_value, annual_return)} for goal in goals]


@app.post("/api/goals")
async def api_add_goal(portfolio_id: str, request: Request):
    from services.goals import load_goals, save_goals
    data = await request.json()
    goals = load_goals(portfolio_id)
    goal = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "name": data.get("name", "Cel"),
        "target": float(data.get("target", 0)),
        "deadline": data.get("deadline", "2030-01-01"),
        "monthly_investment": float(data.get("monthly_investment", 0)),
    }
    goals.append(goal)
    save_goals(portfolio_id, goals)
    return goal


@app.delete("/api/goals/{goal_id}")
async def api_delete_goal(portfolio_id: str, goal_id: str):
    from services.goals import load_goals, save_goals
    goals = [g for g in load_goals(portfolio_id) if g["id"] != goal_id]
    save_goals(portfolio_id, goals)
    return {"ok": True}


@app.get("/api/alerts")
async def api_alerts(portfolio_id: str = "default"):
    from services.alerts import load_alerts, check_alerts
    portfolio, tickers, prices, total_value, total_cost = _portfolio_context(portfolio_id)
    total_pnl_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
    triggered = check_alerts(portfolio_id, portfolio, prices, total_value, total_pnl_pct)
    alerts = load_alerts(portfolio_id)
    return {"alerts": alerts, "triggered": triggered}


@app.post("/api/alerts")
async def api_add_alert(request: Request, portfolio_id: str = "default"):
    from services.alerts import add_alert
    data = await request.json()
    alert = add_alert(
        portfolio_id,
        alert_type=data.get("type", "price"),
        ticker=data.get("ticker"),
        condition=data.get("condition", "below"),
        value=float(data.get("value", 0)),
        name=data.get("name", ""),
    )
    return alert


@app.delete("/api/alerts/{alert_id}")
async def api_delete_alert(alert_id: str, portfolio_id: str = "default"):
    from services.alerts import delete_alert
    delete_alert(portfolio_id, alert_id)
    return {"ok": True}

@app.get("/api/dashboard_data")
async def api_dashboard_data(portfolio_id: str = "default"):
    """Jeden endpoint zwracający wszystkie dane dashboardu równolegle."""
    from concurrent.futures import ThreadPoolExecutor
    from services.analytics import calculate_drawdown, calculate_risk_metrics, calculate_correlation, monte_carlo_simulation
    from services.categories import get_categories_summary
    from services.rebalancing import load_targets, calculate_rebalancing
    from services.dividends import get_dividend_summary
    from services.goals import load_goals, calculate_goal_progress

    portfolio, tickers, prices, total_value, total_cost = _portfolio_context(portfolio_id)
    hist = build_portfolio_history(portfolio_id)

    def get_analytics():
        if not hist or not hist.get("total"):
            return {}
        dd = calculate_drawdown(hist["total"])
        metrics = calculate_risk_metrics(hist["total"], hist["invested"], hist["dates"])
        return {
            "dates": hist["dates"],
            "drawdown": dd["drawdown"],
            "max_drawdown": dd["max_drawdown"],
            "peak_idx": dd["peak_idx"],
            "trough_idx": dd["trough_idx"],
            "metrics": metrics,
        }

    def get_correlation():
        if not hist:
            return {}
        return calculate_correlation(hist)

    def get_montecarlo():
        if not hist or not hist.get("total"):
            return {}
        return monte_carlo_simulation(hist["total"], hist["invested"], 5, 1000, 0)

    def get_categories():
        return get_categories_summary(portfolio, prices)

    def get_rebalancing():
        targets = load_targets(portfolio_id)
        return calculate_rebalancing(portfolio, prices, targets)

    def get_dividends():
        return get_dividend_summary(portfolio_id, portfolio, prices)

    def get_goals():
        goals = load_goals(portfolio_id)
        metrics = calculate_risk_metrics(
            hist.get("total", []), hist.get("invested", []), hist.get("dates", [])
        ) if hist else {}
        annual_return = metrics.get("annual_return", 7.0)
        return [{**g, **calculate_goal_progress(g, total_value, annual_return)} for g in goals]

    def get_alerts():
        from services.alerts import load_alerts, check_alerts
        total_pnl_pct = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
        triggered = check_alerts(portfolio_id, portfolio, prices, total_value, total_pnl_pct)
        alerts = load_alerts(portfolio_id)
        return {"alerts": alerts, "triggered": triggered}

    with ThreadPoolExecutor(max_workers=8) as executor:
        f_analytics    = executor.submit(get_analytics)
        f_correlation  = executor.submit(get_correlation)
        f_montecarlo   = executor.submit(get_montecarlo)
        f_categories   = executor.submit(get_categories)
        f_rebalancing  = executor.submit(get_rebalancing)
        f_dividends    = executor.submit(get_dividends)
        f_goals        = executor.submit(get_goals)
        f_alerts       = executor.submit(get_alerts)

        return {
            "analytics":   f_analytics.result(),
            "correlation": f_correlation.result(),
            "montecarlo":  f_montecarlo.result(),
            "categories":  f_categories.result(),
            "rebalancing": f_rebalancing.result(),
            "dividends":   f_dividends.result(),
            "goals":       f_goals.result(),
            "alerts":      f_alerts.result(),
        }



if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)