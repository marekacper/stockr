"""
inflation.py — dane inflacji CPI z GUS.
Zahardkodowane dane historyczne + próba pobrania najnowszych ze strony GUS.
Cache 7-dniowy.
"""

import json
import os
from datetime import datetime

INFLATION_CACHE = "data/inflation_cache.json"
INFLATION_CACHE_TTL = 60 * 60 * 24 * 7  # 7 dni

# Roczna inflacja CPI Polska (GUS) — % r/r, średnia roczna
HISTORICAL_CPI = {
    "2010": 2.6,
    "2011": 4.3,
    "2012": 3.7,
    "2013": 0.9,
    "2014": 0.0,
    "2015": -0.9,
    "2016": -0.6,
    "2017": 2.0,
    "2018": 1.6,
    "2019": 2.3,
    "2020": 3.4,
    "2021": 5.1,
    "2022": 14.4,
    "2023": 11.4,
    "2024": 3.6,
}


def _load_cache() -> dict | None:
    if not os.path.exists(INFLATION_CACHE):
        return None
    if datetime.now().timestamp() - os.path.getmtime(INFLATION_CACHE) > INFLATION_CACHE_TTL:
        return None
    try:
        with open(INFLATION_CACHE) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(data: dict):
    os.makedirs("data", exist_ok=True)
    try:
        with open(INFLATION_CACHE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _fetch_latest_cpi() -> dict:
    """Próba pobrania najnowszych danych CPI ze strony GUS."""
    try:
        import urllib.request
        # GUS API BDL (Bank Danych Lokalnych)
        # Wskaźnik cen towarów i usług konsumpcyjnych - P2516 (CPI rok poprzedni=100)
        url = "https://bdl.stat.gov.pl/api/v1/data/by-variable/64428?format=json&lang=pl&unit-level=0&page-size=10"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode())

        results = {}
        for item in raw.get("results", []):
            for val in item.get("values", []):
                year = str(val.get("year", ""))
                value = val.get("val")
                if year and value is not None:
                    # GUS podaje rok poprzedni=100, więc CPI% = value - 100
                    results[year] = round(float(value) - 100, 1)

        if results:
            return results
    except Exception:
        pass

    return {}


def get_inflation_data() -> dict:
    """
    Zwraca słownik {rok: cpi_procent} — dane historyczne + najnowsze z GUS.
    """
    cached = _load_cache()
    if cached:
        return cached

    # Zacznij od danych historycznych
    data = dict(HISTORICAL_CPI)

    # Spróbuj pobrać najnowsze
    latest = _fetch_latest_cpi()
    if latest:
        data.update(latest)

    # Posortuj wg roku
    data = dict(sorted(data.items()))

    _save_cache(data)
    return data


def calculate_real_return(portfolio_history: dict, inflation_data: dict) -> dict:
    """
    Oblicza realną stopę zwrotu portfela po uwzględnieniu inflacji.
    Zwraca series dat i wartości "portfel w PLN z 2010" (siła nabywcza).
    """
    dates = portfolio_history.get("dates", [])
    total = portfolio_history.get("total", [])

    if not dates or not total:
        return {}

    # Oblicz skumulowaną inflację per data
    def get_cumulative_inflation_factor(date_str: str) -> float:
        """Ile PLN z daty startowej = 1 PLN dziś."""
        year = int(date_str[:4])
        factor = 1.0
        start_year = int(dates[0][:4])
        for y in range(start_year, year + 1):
            cpi = inflation_data.get(str(y), 2.5)  # fallback 2.5%
            factor *= (1 + cpi / 100)
        return factor

    # Wartość nominalna vs realna
    start_value = next((v for v in total if v > 0), None)
    if not start_value:
        return {}

    nominal = []
    real = []
    inflation_baseline = []

    start_factor = get_cumulative_inflation_factor(dates[0])

    for i, (date, value) in enumerate(zip(dates, total)):
        if value == 0:
            nominal.append(None)
            real.append(None)
            inflation_baseline.append(None)
            continue

        factor = get_cumulative_inflation_factor(date)
        relative_inflation = factor / start_factor

        nominal.append(round(value / start_value * 100, 2))
        real.append(round((value / start_value / relative_inflation) * 100, 2))
        inflation_baseline.append(round(relative_inflation * 100, 2))

    return {
        "dates": dates,
        "nominal": nominal,
        "real": real,
        "inflation_baseline": inflation_baseline,
        "cpi_by_year": inflation_data,
    }