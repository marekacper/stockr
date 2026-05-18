"""
technical.py — analiza techniczna dla tickerów.
Wskaźniki: RSI, MACD, MA20/MA50, Bollinger Bands, wolumen.
"""

import numpy as np
from datetime import datetime, timedelta


def calculate_rsi(prices: list, period: int = 14) -> list:
    """Relative Strength Index."""
    if len(prices) < period + 1:
        return [None] * len(prices)

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi = [None] * (period)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(round(100 - 100 / (1 + rs), 2))

    return [None] + rsi  # wyrównaj do długości prices


def calculate_ma(prices: list, period: int) -> list:
    """Simple Moving Average."""
    result = []
    for i in range(len(prices)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(prices[i-period+1:i+1]) / period, 4))
    return result


def calculate_ema(prices: list, period: int) -> list:
    """Exponential Moving Average."""
    if len(prices) < period:
        return [None] * len(prices)

    result = [None] * (period - 1)
    sma = sum(prices[:period]) / period
    result.append(round(sma, 4))
    multiplier = 2 / (period + 1)

    for i in range(period, len(prices)):
        ema = (prices[i] - result[-1]) * multiplier + result[-1]
        result.append(round(ema, 4))

    return result


def calculate_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD = EMA12 - EMA26, Signal = EMA9(MACD), Histogram = MACD - Signal."""
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)

    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(round(f - s, 4))

    # Signal line — EMA9 of MACD (tylko na nieNone wartościach)
    macd_valid_start = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if macd_valid_start is None:
        return {"macd": macd_line, "signal": [None]*len(prices), "histogram": [None]*len(prices)}

    macd_values = macd_line[macd_valid_start:]
    ema_signal_raw = calculate_ema(macd_values, signal)

    signal_line = [None] * macd_valid_start + ema_signal_raw
    histogram = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(round(m - s, 4))

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def calculate_bollinger_bands(prices: list, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands: Middle = MA20, Upper/Lower = MA20 ± 2*std."""
    middle = calculate_ma(prices, period)
    upper = []
    lower = []

    for i in range(len(prices)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
        else:
            window = prices[i-period+1:i+1]
            std = (sum((p - middle[i])**2 for p in window) / period) ** 0.5
            upper.append(round(middle[i] + std_dev * std, 4))
            lower.append(round(middle[i] - std_dev * std, 4))

    return {"middle": middle, "upper": upper, "lower": lower}


def get_current_signal(prices: list, rsi: list, macd: dict, ma20: list, ma50: list) -> dict:
    """Generuje prosty sygnał kupna/sprzedaży na podstawie wskaźników."""
    if not prices or len(prices) < 50:
        return {"signal": "neutral", "strength": 0, "reasons": []}

    current_price = prices[-1]
    current_rsi = next((v for v in reversed(rsi) if v is not None), None)
    current_macd = next((v for v in reversed(macd["macd"]) if v is not None), None)
    current_signal_val = next((v for v in reversed(macd["signal"]) if v is not None), None)
    current_ma20 = next((v for v in reversed(ma20) if v is not None), None)
    current_ma50 = next((v for v in reversed(ma50) if v is not None), None)

    bullish = []
    bearish = []

    if current_rsi is not None:
        if current_rsi < 30:
            bullish.append(f"RSI wyprzedany ({current_rsi:.1f})")
        elif current_rsi > 70:
            bearish.append(f"RSI wykupiony ({current_rsi:.1f})")

    if current_macd is not None and current_signal_val is not None:
        if current_macd > current_signal_val:
            bullish.append("MACD powyżej linii sygnału")
        else:
            bearish.append("MACD poniżej linii sygnału")

    if current_ma20 is not None and current_ma50 is not None:
        if current_ma20 > current_ma50:
            bullish.append("MA20 > MA50 (złoty krzyż)")
        else:
            bearish.append("MA20 < MA50 (krzyż śmierci)")

    if current_price and current_ma20:
        if current_price > current_ma20:
            bullish.append("Cena powyżej MA20")
        else:
            bearish.append("Cena poniżej MA20")

    score = len(bullish) - len(bearish)
    if score >= 2:
        signal = "buy"
    elif score <= -2:
        signal = "sell"
    else:
        signal = "neutral"

    return {
        "signal": signal,
        "strength": score,
        "bullish": bullish,
        "bearish": bearish,
    }


def get_technical_analysis(ticker: str, period_days: int = 365) -> dict:
    """
    Pobiera dane cenowe i wolumen, oblicza wszystkie wskaźniki.
    """
    import yfinance as yf
    from services.prices import to_yf_ticker

    try:
        yf_ticker = to_yf_ticker(ticker)
        start = (datetime.now() - timedelta(days=period_days + 60)).strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        df = yf.download(yf_ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return {"error": "Brak danych"}

        # Wytnij do żądanego okresu
        cutoff = datetime.now() - timedelta(days=period_days)
        df = df[df.index >= cutoff]

        dates = [d.strftime("%Y-%m-%d") for d in df.index]
        closes = [float(v) for v in df["Close"].squeeze().values]
        volumes = [int(v) for v in df["Volume"].squeeze().values]
        opens = [float(v) for v in df["Open"].squeeze().values]
        highs = [float(v) for v in df["High"].squeeze().values]
        lows = [float(v) for v in df["Low"].squeeze().values]

        # Wskaźniki
        rsi = calculate_rsi(closes)
        ma20 = calculate_ma(closes, 20)
        ma50 = calculate_ma(closes, 50)
        macd = calculate_macd(closes)
        bb = calculate_bollinger_bands(closes)
        signal = get_current_signal(closes, rsi, macd, ma20, ma50)

        # Statystyki
        current_price = closes[-1] if closes else None
        price_change_1d = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else None
        price_change_1m = round((closes[-1] - closes[-22]) / closes[-22] * 100, 2) if len(closes) >= 22 else None
        price_high_52w = round(max(closes[-252:]) if len(closes) >= 252 else max(closes), 2)
        price_low_52w = round(min(closes[-252:]) if len(closes) >= 252 else min(closes), 2)

        return {
            "ticker": ticker,
            "dates": dates,
            "prices": closes,
            "volumes": volumes,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "indicators": {
                "rsi": rsi,
                "ma20": ma20,
                "ma50": ma50,
                "macd": macd["macd"],
                "macd_signal": macd["signal"],
                "macd_histogram": macd["histogram"],
                "bb_upper": bb["upper"],
                "bb_middle": bb["middle"],
                "bb_lower": bb["lower"],
            },
            "signal": signal,
            "stats": {
                "current_price": current_price,
                "price_change_1d": price_change_1d,
                "price_change_1m": price_change_1m,
                "price_high_52w": price_high_52w,
                "price_low_52w": price_low_52w,
                "current_rsi": next((v for v in reversed(rsi) if v is not None), None),
                "current_ma20": next((v for v in reversed(ma20) if v is not None), None),
                "current_ma50": next((v for v in reversed(ma50) if v is not None), None),
                "avg_volume_10d": round(sum(volumes[-10:]) / min(10, len(volumes))) if volumes else None,
            }
        }

    except Exception as e:
        return {"error": str(e)}