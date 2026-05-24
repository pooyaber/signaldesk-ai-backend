from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf

from app.models import TechnicalSnapshot


INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "2h": "60m",  # Yahoo has no 2h interval; we approximate with 1h data.
    "4h": "60m",  # Resampling is possible, but 1h is good enough for this MVP.
    "1d": "1d",
    "1w": "1wk",
}

PERIOD_MAP = {
    "1m": "7d",
    "5m": "30d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "2h": "730d",
    "4h": "730d",
    "1d": "2y",
    "1w": "5y",
}

CHART_RANGE_MAP = {
    "1D": ("1d", "5m"),
    "7D": ("7d", "30m"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
    "ALL": ("max", "1mo"),
}

COMMON_SYMBOL_MAP = {
    "NVIDIA": "NVDA",
    "NVIDIACORPORATION": "NVDA",
    "APPLE": "AAPL",
    "APPLEINC": "AAPL",
    "TESLA": "TSLA",
    "TESLAINC": "TSLA",
    "MICROSOFT": "MSFT",
    "MICROSOFTCORPORATION": "MSFT",
    "BITCOIN": "BTC-USD",
    "ETHEREUM": "ETH-USD",
    "BTCUSD": "BTC-USD",
    "BTCUSDT": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSD": "SOL-USD",
    "SOLUSDT": "SOL-USD",
    "XRPUSD": "XRP-USD",
    "XRPUSDT": "XRP-USD",
}

POPULAR_SYMBOLS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "AMZN", "name": "Amazon.com, Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "META", "name": "Meta Platforms, Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "AMD", "name": "Advanced Micro Devices, Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "exchange": "NASDAQ", "type": "ETF"},
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "exchange": "CCC", "type": "Crypto"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "exchange": "CCC", "type": "Crypto"},
    {"symbol": "EURUSD=X", "name": "EUR/USD", "exchange": "FX", "type": "Currency"},
]

SYMBOL_PROFILES = {
    "NVDA": "NVIDIA Corporation",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "AMD": "Advanced Micro Devices, Inc.",
    "META": "Meta Platforms, Inc.",
    "TSLA": "Tesla, Inc.",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
}

LOGO_URLS = {
    "NVDA": "https://cdn.simpleicons.org/nvidia",
    "AAPL": "https://cdn.simpleicons.org/apple/000000",
    "MSFT": "https://cdn.simpleicons.org/microsoft",
    "AMD": "https://cdn.simpleicons.org/amd",
    "META": "https://cdn.simpleicons.org/meta",
    "TSLA": "https://cdn.simpleicons.org/tesla",
    "BTC-USD": "https://cdn.simpleicons.org/bitcoin",
    "ETH-USD": "https://cdn.simpleicons.org/ethereum",
}


def get_logo_url(mapped_symbol: str) -> str | None:
    return LOGO_URLS.get(mapped_symbol.upper())


def with_logo(item: dict) -> dict:
    symbol = str(item.get("symbol") or "").upper()
    mapped_symbol = map_symbol(symbol).upper() if symbol else symbol
    enriched = dict(item)
    enriched["logo_url"] = get_logo_url(mapped_symbol)
    return enriched


def map_symbol(symbol: str) -> str:
    clean = symbol.strip().upper().replace("/", "")
    compact_clean = "".join(ch for ch in clean if ch.isalnum())
    if clean in COMMON_SYMBOL_MAP:
        return COMMON_SYMBOL_MAP[clean]
    if compact_clean in COMMON_SYMBOL_MAP:
        return COMMON_SYMBOL_MAP[compact_clean]
    for item in POPULAR_SYMBOLS:
        item_symbol = "".join(ch for ch in item["symbol"].upper() if ch.isalnum())
        item_name = "".join(ch for ch in item["name"].upper() if ch.isalnum())
        if compact_clean == item_symbol or compact_clean == item_name:
            return item["symbol"]
        if len(compact_clean) >= 3 and item_name.startswith(compact_clean):
            return item["symbol"]
    return symbol.strip()


def get_asset_name(mapped_symbol: str) -> str:
    if mapped_symbol in SYMBOL_PROFILES:
        return SYMBOL_PROFILES[mapped_symbol]
    try:
        ticker = yf.Ticker(mapped_symbol)
        info = ticker.info
        return info.get("shortName") or info.get("longName") or mapped_symbol
    except Exception:
        return mapped_symbol


def get_quote_currency(mapped_symbol: str) -> str:
    try:
        currency = yf.Ticker(mapped_symbol).fast_info.get("currency")
        if currency:
            return str(currency).upper()
    except Exception:
        pass
    return "USD"


def search_symbols(query: str = "", limit: int = 12) -> dict:
    clean = query.strip()
    max_results = max(1, min(limit, 20))

    if not clean:
        return {"query": clean, "results": [with_logo(item) for item in POPULAR_SYMBOLS[:max_results]], "source": "popular"}

    fallback = [
        with_logo(item)
        for item in POPULAR_SYMBOLS
        if clean.upper() in item["symbol"].upper() or clean.lower() in item["name"].lower()
    ][:max_results]

    if fallback:
        return {"query": clean, "results": fallback, "source": "local"}

    try:
        search = yf.Search(clean, max_results=max_results)
        results = []
        seen: set[str] = set()
        for quote in getattr(search, "quotes", []) or []:
            symbol = str(quote.get("symbol") or "").strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append(
                {
                    "symbol": symbol,
                    "name": quote.get("shortname") or quote.get("longname") or symbol,
                    "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
                    "type": quote.get("typeDisp") or quote.get("quoteType") or "",
                    "logo_url": get_logo_url(map_symbol(symbol)),
                }
            )
        return {"query": clean, "results": results or fallback, "source": "yahoo"}
    except Exception as exc:
        return {"query": clean, "results": fallback, "source": "fallback", "error": str(exc)}


def get_fx_rate(base: str = "USD", quote: str = "EUR") -> dict:
    base_clean = base.strip().upper()
    quote_clean = quote.strip().upper()
    if base_clean == quote_clean:
        return {"base": base_clean, "quote": quote_clean, "rate": 1.0}

    pair = f"{base_clean}{quote_clean}=X"
    data = yf.download(pair, period="5d", interval="1d", progress=False, threads=False)

    if data.empty and base_clean == "USD" and quote_clean == "EUR":
        inverse = yf.download("EURUSD=X", period="5d", interval="1d", progress=False, threads=False)
        inverse = normalize_yfinance_columns(inverse)
        latest = _safe_float(inverse["Close"].dropna().iloc[-1]) if not inverse.empty else None
        if latest:
            return {"base": base_clean, "quote": quote_clean, "rate": 1 / latest}

    if data.empty and base_clean == "EUR" and quote_clean == "USD":
        inverse = yf.download("EURUSD=X", period="5d", interval="1d", progress=False, threads=False)
        inverse = normalize_yfinance_columns(inverse)
        latest = _safe_float(inverse["Close"].dropna().iloc[-1]) if not inverse.empty else None
        if latest:
            return {"base": base_clean, "quote": quote_clean, "rate": latest}

    if data.empty:
        return {"base": base_clean, "quote": quote_clean, "rate": None, "error": "FX rate unavailable"}

    data = normalize_yfinance_columns(data)
    latest = _safe_float(data["Close"].dropna().iloc[-1])
    return {"base": base_clean, "quote": quote_clean, "rate": latest}


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value) or math.isinf(float(value)):
            return None
        return float(value)
    except Exception:
        return None


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = data["High"] - data["Low"]
    high_close = (data["High"] - data["Close"].shift()).abs()
    low_close = (data["Low"] - data["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def add_indicator_columns(data: pd.DataFrame) -> pd.DataFrame:
    close = data["Close"]
    data["EMA20"] = close.ewm(span=20, adjust=False).mean()
    data["EMA50"] = close.ewm(span=50, adjust=False).mean()
    data["EMA200"] = close.ewm(span=200, adjust=False).mean()
    data["SMA20"] = close.rolling(20).mean()
    data["SMA50"] = close.rolling(50).mean()
    data["SMA200"] = close.rolling(200).mean()
    data["BB_MIDDLE"] = data["SMA20"]
    bb_std20 = close.rolling(20).std()
    data["BB_UPPER"] = data["BB_MIDDLE"] + (2 * bb_std20)
    data["BB_LOWER"] = data["BB_MIDDLE"] - (2 * bb_std20)
    data["BB_PERCENT"] = (close - data["BB_LOWER"]) / (data["BB_UPPER"] - data["BB_LOWER"])
    data["BB_WIDTH"] = (data["BB_UPPER"] - data["BB_LOWER"]) / data["BB_MIDDLE"]
    data["RSI14"] = calculate_rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_SIGNAL"] = data["MACD"].ewm(span=9, adjust=False).mean()
    data["MACD_HIST"] = data["MACD"] - data["MACD_SIGNAL"]
    data["ATR14"] = calculate_atr(data)

    if "Volume" in data:
        data["VOL_RATIO20"] = data["Volume"] / data["Volume"].rolling(20).mean()
    else:
        data["Volume"] = np.nan
        data["VOL_RATIO20"] = np.nan

    return data


def normalize_yfinance_columns(data: pd.DataFrame) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]
    return data


def get_chart_data(symbol: str, range_key: str = "6M") -> dict:
    clean_range = range_key.strip().upper()
    period, interval = CHART_RANGE_MAP.get(clean_range, CHART_RANGE_MAP["6M"])
    mapped_symbol = map_symbol(symbol)
    quote_currency = get_quote_currency(mapped_symbol)

    data = yf.download(
        mapped_symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if data.empty:
        return {
            "symbol": symbol,
            "mapped_symbol": mapped_symbol,
            "logo_url": get_logo_url(mapped_symbol),
            "currency": quote_currency,
            "range": clean_range,
            "interval": interval,
            "candles": [],
            "notes": ["No market data returned. Try a Yahoo Finance compatible symbol."],
        }

    data = normalize_yfinance_columns(data)
    data = add_indicator_columns(data)
    data = data.tail(900)

    candles = []
    for index, row in data.iterrows():
        candles.append(
            {
                "time": index.isoformat(),
                "timestamp": index.isoformat(),
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": _safe_float(row.get("Close")),
                "volume": _safe_float(row.get("Volume")),
                "ema20": _safe_float(row.get("EMA20")),
                "ema50": _safe_float(row.get("EMA50")),
                "ema200": _safe_float(row.get("EMA200")),
                "sma20": _safe_float(row.get("SMA20")),
                "sma50": _safe_float(row.get("SMA50")),
                "sma200": _safe_float(row.get("SMA200")),
                "bb_upper": _safe_float(row.get("BB_UPPER")),
                "bb_middle": _safe_float(row.get("BB_MIDDLE")),
                "bb_lower": _safe_float(row.get("BB_LOWER")),
                "bb_percent": _safe_float(row.get("BB_PERCENT")),
                "macd": _safe_float(row.get("MACD")),
                "macd_signal": _safe_float(row.get("MACD_SIGNAL")),
                "macd_histogram": _safe_float(row.get("MACD_HIST")),
                "rsi14": _safe_float(row.get("RSI14")),
                "atr14": _safe_float(row.get("ATR14")),
            }
        )

    return {
        "symbol": symbol,
        "mapped_symbol": mapped_symbol,
        "logo_url": get_logo_url(mapped_symbol),
        "currency": quote_currency,
        "range": clean_range,
        "interval": interval,
        "candles": candles,
        "notes": [],
    }


def get_technicals(symbol: str, timeframe: str = "1d") -> TechnicalSnapshot:
    mapped_symbol = map_symbol(symbol)
    interval = INTERVAL_MAP.get(timeframe, "1d")
    period = PERIOD_MAP.get(timeframe, "2y")
    quote_currency = get_quote_currency(mapped_symbol)
    asset_name = get_asset_name(mapped_symbol)

    notes: list[str] = []
    if timeframe in {"2h", "4h"}:
        notes.append("Yahoo Finance has no native 2h/4h interval here; using 1h candles as approximation.")

    data = yf.download(
        mapped_symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if data.empty:
        return TechnicalSnapshot(
            symbol=symbol,
            mapped_symbol=mapped_symbol,
            timeframe=timeframe,
            asset_name=asset_name,
            logo_url=get_logo_url(mapped_symbol),
            quote_currency=quote_currency,
            trend="unknown",
            notes=["No market data returned. Try a Yahoo Finance compatible symbol."],
        )

    data = normalize_yfinance_columns(data)

    data = add_indicator_columns(data)

    latest = data.iloc[-1]
    previous = data.iloc[-2] if len(data) >= 2 else latest

    last_price = _safe_float(latest.get("Close"))
    previous_close = _safe_float(previous.get("Close"))
    change_percent = None
    change_absolute = None
    if last_price is not None and previous_close not in (None, 0):
        change_absolute = last_price - previous_close
        change_percent = ((last_price - previous_close) / previous_close) * 100

    ema20 = _safe_float(latest.get("EMA20"))
    ema50 = _safe_float(latest.get("EMA50"))
    ema200 = _safe_float(latest.get("EMA200"))

    trend: Literal["bullish", "neutral", "bearish", "unknown"] = "unknown"
    if all(v is not None for v in [last_price, ema20, ema50, ema200]):
        if last_price > ema20 > ema50 > ema200:
            trend = "bullish"
        elif last_price < ema20 < ema50 < ema200:
            trend = "bearish"
        else:
            trend = "neutral"

    return TechnicalSnapshot(
        symbol=symbol,
        mapped_symbol=mapped_symbol,
        timeframe=timeframe,
        asset_name=asset_name,
        logo_url=get_logo_url(mapped_symbol),
        quote_currency=quote_currency,
        last_price=last_price,
        previous_close=previous_close,
        change_absolute=_safe_float(change_absolute),
        change_percent=_safe_float(change_percent),
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        sma20=_safe_float(latest.get("SMA20")),
        sma50=_safe_float(latest.get("SMA50")),
        sma200=_safe_float(latest.get("SMA200")),
        bb_middle=_safe_float(latest.get("BB_MIDDLE")),
        bb_upper=_safe_float(latest.get("BB_UPPER")),
        bb_lower=_safe_float(latest.get("BB_LOWER")),
        bb_percent=_safe_float(latest.get("BB_PERCENT")),
        bb_width=_safe_float(latest.get("BB_WIDTH")),
        rsi14=_safe_float(latest.get("RSI14")),
        macd=_safe_float(latest.get("MACD")),
        macd_signal=_safe_float(latest.get("MACD_SIGNAL")),
        macd_histogram=_safe_float(latest.get("MACD_HIST")),
        atr14=_safe_float(latest.get("ATR14")),
        volume=_safe_float(latest.get("Volume")),
        volume_ratio20=_safe_float(latest.get("VOL_RATIO20")),
        trend=trend,
        notes=notes,
    )
