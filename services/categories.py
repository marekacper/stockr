"""
Kategorie aktywów dla tickerów.
Automatyczne przypisanie + możliwość ręcznego nadpisania.
"""

# Ręczne przypisania — nadpisują automatyczne
MANUAL_CATEGORIES = {
    # ETF-y
    "VUAA.DE": "ETF",
    "V80A.DE": "ETF",
    "SXRV.DE": "ETF",
    "IUSQ.DE": "ETF",
    "CNDX.DE": "ETF",
    "CNDX.UK": "ETF",
    "EIMI.UK": "ETF",
    "MSF.DE":  "ETF",
    "AMD.DE":  "ETF",
    "NVD.DE":  "ETF",
    "CNYA.DE": "ETF",
    "ABEA.DE": "ETF",
    "ETFBS80TR.PL": "ETF",
    # Obligacje
    "TOS0428": "Obligacje",
    "TOS0528": "Obligacje",
    "TOS0628": "Obligacje",
    "TOS0728": "Obligacje",
    "TOS0928": "Obligacje",
    "EDO1135": "Obligacje",
    # Surowce/krypto
    "GLD":     "Surowce",
    "BTC-USD": "Krypto",
    "ETH-USD": "Krypto",
}

# Kategorie na podstawie sufiksu
SUFFIX_CATEGORIES = {
    ".WA": "Akcje GPW",
    ".PL": "Akcje GPW",
    ".DE": "ETF",
    ".UK": "ETF",
    ".L":  "ETF",
    ".AS": "ETF",
}

CATEGORY_COLORS = {
    "Akcje GPW":  "#6366f1",
    "ETF":        "#10b981",
    "Obligacje":  "#f59e0b",
    "Surowce":    "#f43f5e",
    "Krypto":     "#22d3ee",
    "Inne":       "#64748b",
}


def get_category(ticker: str) -> str:
    t = ticker.upper()
    if t in MANUAL_CATEGORIES:
        return MANUAL_CATEGORIES[t]
    for suffix, cat in SUFFIX_CATEGORIES.items():
        if t.endswith(suffix.upper()):
            return cat
    return "Inne"


def get_categories_summary(portfolio: dict, prices: dict) -> list[dict]:
    """Zwraca udział każdej kategorii w portfelu."""
    from collections import defaultdict
    totals = defaultdict(float)

    for ticker, pos in portfolio.items():
        price = prices.get(ticker)
        if price and pos["quantity"] > 0:
            value = price * pos["quantity"]
            cat = get_category(ticker)
            totals[cat] += value

    total = sum(totals.values())
    result = []
    for cat, val in sorted(totals.items(), key=lambda x: -x[1]):
        result.append({
            "category": cat,
            "value": round(val, 2),
            "share": round(val / total * 100, 2) if total > 0 else 0,
            "color": CATEGORY_COLORS.get(cat, "#64748b"),
        })
    return result