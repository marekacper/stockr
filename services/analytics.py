import numpy as np
import pandas as pd
from datetime import datetime, timedelta


def calculate_drawdown(total_values: list) -> dict:
    values = np.array(total_values, dtype=float)
    values[values == 0] = np.nan

    peak = np.maximum.accumulate(np.where(np.isnan(values), 0, values))
    peak[peak == 0] = np.nan

    drawdown = np.where(peak > 0, (values - peak) / peak * 100, 0)

    max_dd = float(np.nanmin(drawdown))
    max_dd_idx = int(np.nanargmin(drawdown))
    peak_idx = int(np.nanargmax(
        np.where(np.isnan(values[:max_dd_idx+1]), -np.inf, values[:max_dd_idx+1])
    )) if max_dd_idx > 0 else 0

    return {
        "drawdown": [round(float(d), 2) if not np.isnan(d) else 0 for d in drawdown],
        "max_drawdown": round(max_dd, 2),
        "peak_idx": peak_idx,
        "trough_idx": max_dd_idx,
    }


def calculate_risk_metrics(total_values: list, invested_values: list, dates: list, risk_free_rate: float = 0.055) -> dict:
    values = np.array(total_values, dtype=float)
    invested = np.array(invested_values, dtype=float)

    first_nonzero = np.argmax(values > 0)
    values = values[first_nonzero:]
    invested = invested[first_nonzero:]

    if len(values) < 10:
        return {}

    twr_returns = []
    for i in range(1, len(values)):
        prev_val = values[i-1]
        cash_flow = invested[i] - invested[i-1]
        adjusted_prev = prev_val + cash_flow
        if adjusted_prev > 0 and values[i] > 0:
            r = (values[i] - adjusted_prev) / adjusted_prev
            if abs(r) < 0.5:
                twr_returns.append(r)

    returns = np.array(twr_returns)

    if len(returns) < 5:
        return {}

    daily_vol = float(np.std(returns))
    annual_vol = daily_vol * np.sqrt(252)
    mean_daily = float(np.mean(returns))
    annual_return = (1 + mean_daily) ** 252 - 1

    daily_rf = risk_free_rate / 252
    excess_returns = returns - daily_rf
    sharpe = float(np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)) if np.std(excess_returns) > 0 else 0

    negative_returns = returns[returns < 0]
    downside_vol = float(np.std(negative_returns)) * np.sqrt(252) if len(negative_returns) > 0 else 0.0001
    sortino = float((annual_return - risk_free_rate) / downside_vol)

    dd = calculate_drawdown(total_values)
    max_dd = dd["max_drawdown"]
    calmar = float(annual_return / abs(max_dd / 100)) if max_dd < 0 else 0

    win_rate = float(np.sum(returns > 0) / len(returns) * 100)
    best_day = float(np.max(returns) * 100)
    worst_day = float(np.min(returns) * 100)

    return {
        "annual_return": round(annual_return * 100, 2),
        "annual_volatility": round(annual_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown": round(max_dd, 2),
        "calmar_ratio": round(calmar, 2),
        "win_rate": round(win_rate, 2),
        "best_day": round(best_day, 2),
        "worst_day": round(worst_day, 2),
        "trading_days": len(returns),
    }


def calculate_correlation(history_data: dict) -> dict:
    tickers = [
        k for k in history_data.keys()
        if k not in ("total", "invested", "dates") and history_data[k]
    ]

    if len(tickers) < 2:
        return {}

    returns = {}
    for ticker in tickers:
        vals = np.array(history_data[ticker], dtype=float)
        if np.sum(vals > 0) < 10:
            continue
        r = np.diff(vals) / np.where(vals[:-1] > 0, vals[:-1], np.nan)
        r[~np.isfinite(r)] = np.nan
        returns[ticker] = r

    if len(returns) < 2:
        return {}

    df = pd.DataFrame(returns)
    df = df.dropna(how='all')

    corr = df.corr(min_periods=20).round(3)
    corr = corr.fillna(0)

    return {
        "tickers": list(corr.columns),
        "matrix": corr.values.tolist(),
    }


def monte_carlo_simulation(
    total_values: list,
    invested_values: list,
    years: int = 5,
    simulations: int = 1000,
    monthly_investment: float = 0,
) -> dict:
    values = np.array(total_values, dtype=float)
    invested = np.array(invested_values, dtype=float)

    twr_returns = []
    for i in range(1, len(values)):
        prev = values[i-1]
        cf = invested[i] - invested[i-1]
        adj = prev + cf
        if adj > 0 and values[i] > 0:
            r = (values[i] - adj) / adj
            if abs(r) < 0.3:
                twr_returns.append(r)

    if len(twr_returns) < 20:
        return {}

    returns = np.array(twr_returns)
    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns))
    current_value = float(values[-1])

    trading_days = years * 252
    monthly_days = 21

    all_paths = np.zeros((simulations, trading_days))
    for s in range(simulations):
        daily_returns = np.random.normal(mean_r, std_r, trading_days)
        portfolio_value = current_value
        for d in range(trading_days):
            portfolio_value *= (1 + daily_returns[d])
            if monthly_investment > 0 and d % monthly_days == 0:
                portfolio_value += monthly_investment
            all_paths[s, d] = portfolio_value

    percentiles = [10, 25, 50, 75, 90]
    result_percentiles = {}
    for p in percentiles:
        result_percentiles[str(p)] = [
            round(float(np.percentile(all_paths[:, d], p)), 2)
            for d in range(0, trading_days, 5)
        ]

    start = datetime.now()
    dates = [
        (start + timedelta(days=d*5)).strftime("%Y-%m-%d")
        for d in range(len(result_percentiles["50"]))
    ]

    final_values = all_paths[:, -1]
    prob_profit = float(np.sum(final_values > current_value) / simulations * 100)
    prob_double = float(np.sum(final_values > current_value * 2) / simulations * 100)

    return {
        "dates": dates,
        "percentiles": result_percentiles,
        "current_value": current_value,
        "prob_profit": round(prob_profit, 1),
        "prob_double": round(prob_double, 1),
        "mean_final": round(float(np.mean(final_values)), 2),
        "simulations": simulations,
    }