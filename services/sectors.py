"""
sectors.py — analiza sektorowa portfela.
Pobiera sektor dla każdego tickera przez yfinance z cache 7-dniowym.
"""

import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
from services.prices import to_yf_ticker

SECTOR_CACHE_DIR = "data/sector_cache"
SECTOR_CACHE_TTL = 60 * 60 * 24 * 7  # 7 dni — sektory zmieniają się rzadko

# Mapowanie angielskich sektorów yfinance na polskie
SECTOR_NAMES = {
    "Technology":               "Technologia",
    "Financial Services":       "Finanse",
    "Healthcare":               "Ochrona zdrowia",
    "Consumer Cyclical":        "Dobra cykliczne",
    "Consumer Defensive":       "Dobra podstawowe",
    "Industrials":              "Przemysł",
    "Energy":                   "Energia",
    "Basic Materials":          "Surowce",
    "Real Estate":              "Nieruchomości",
    "Communication Services":   "Komunikacja",
    "Utilities":                "Utilities",
    "Financial":                "Finanse",
    "Services":                 "Usługi",
}

SECTOR_COLORS = {
    "Technologia":       "#6366f1",
    "Finanse":           "#22d3ee",
    "Ochrona zdrowia":   "#34d399",
    "Dobra cykliczne":   "#f59e0b",
    "Dobra podstawowe":  "#10b981",
    "Przemysł":          "#f43f5e",
    "Energia":           "#fb923c",
    "Surowce":           "#a78bfa",
    "Nieruchomości":     "#38bdf8",
    "Komunikacja":       "#e879f9",
    "Utilities":         "#84cc16",
    "Usługi":            "#facc15",
    "ETF":               "#64748b",
    "Obligacje":         "#fbbf24",
    "Inne":              "#475569",
}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace(".", "_")
    return os.path.join(SECTOR_CACHE_DIR, f"{safe}.json")


def _load_sector_cache(ticker: str) -> dict | None:
    os.makedirs(SECTOR_CACHE_DIR, exist_ok=True)
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    if datetime.now().timestamp() - os.path.getmtime(path) > SECTOR_CACHE_TTL:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_sector_cache(ticker: str, data: dict):
    os.makedirs(SECTOR_CACHE_DIR, exist_ok=True)
    try:
        with open(_cache_path(ticker), "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pobieranie sektora
# ---------------------------------------------------------------------------

def _fetch_ticker_sector(ticker: str) -> dict:
    """Pobiera sektor tickera z yfinance. Zwraca {ticker, sector, industry}."""
    from services.categories import get_category, MANUAL_CATEGORIES

    # Obligacje i ETF-y mają przypisane kategorie ręcznie — nie odpytuj yfinance
    cat = get_category(ticker)
    if cat in ("Obligacje", "Krypto", "Surowce"):
        result = {"ticker": ticker, "sector": cat, "industry": cat}
        _save_sector_cache(ticker, result)
        return result

    if cat == "ETF":
        result = {"ticker": ticker, "sector": "ETF", "industry": "ETF"}
        _save_sector_cache(ticker, result)
        return result

    cached = _load_sector_cache(ticker)
    if cached is not None:
        return cached

    result = {"ticker": ticker, "sector": "Inne", "industry": "Inne"}
    try:
        yf_ticker = to_yf_ticker(ticker)
        info = yf.Ticker(yf_ticker).info
        sector_en = info.get("sector") or ""
        industry_en = info.get("industry") or ""
        sector_pl = SECTOR_NAMES.get(sector_en, sector_en or "Inne")
        result = {
            "ticker": ticker,
            "sector": sector_pl,
            "industry": industry_en,
        }
    except Exception:
        pass

    _save_sector_cache(ticker, result)
    return result


# ---------------------------------------------------------------------------
# Główna funkcja
# ---------------------------------------------------------------------------

def get_sector_summary(portfolio: dict, prices: dict) -> dict:
    """
    Zwraca analizę sektorową portfela.
    """
    from collections import defaultdict

    active_tickers = [t for t, pos in portfolio.items() if pos["quantity"] > 0 and prices.get(t)]

    if not active_tickers:
        return {"sectors": [], "by_ticker": [], "total_value": 0}

    # Pobierz sektory równolegle
    ticker_sectors = {}
    with ThreadPoolExecutor(max_workers=min(len(active_tickers), 8)) as executor:
        futures = {executor.submit(_fetch_ticker_sector, t): t for t in active_tickers}
        for future in as_completed(futures):
            try:
                res = future.result()
                ticker_sectors[res["ticker"]] = res
            except Exception:
                pass

    # Oblicz wartości per sektor
    sector_totals = defaultdict(float)
    ticker_details = []
    total_value = 0.0

    for ticker, pos in portfolio.items():
        price = prices.get(ticker)
        if not price or pos["quantity"] <= 0:
            continue
        value = price * pos["quantity"]
        total_value += value
        sector_info = ticker_sectors.get(ticker, {"sector": "Inne", "industry": "Inne"})
        sector = sector_info["sector"]
        sector_totals[sector] += value
        ticker_details.append({
            "ticker": ticker,
            "sector": sector,
            "industry": sector_info["industry"],
            "value": round(value, 2),
        })

    # Posortuj tickery wg wartości
    ticker_details.sort(key=lambda x: x["value"], reverse=True)

    # Zbuduj listę sektorów
    sectors = []
    for sector, val in sorted(sector_totals.items(), key=lambda x: -x[1]):
        sectors.append({
            "sector": sector,
            "value": round(val, 2),
            "share": round(val / total_value * 100, 2) if total_value > 0 else 0,
            "color": SECTOR_COLORS.get(sector, "#64748b"),
        })

    return {
        "sectors": sectors,
        "by_ticker": ticker_details,
        "total_value": round(total_value, 2),
    }