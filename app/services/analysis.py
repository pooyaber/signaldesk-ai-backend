from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from app.config import get_settings
from app.models import AISignal, AnalysisResult, TechnicalSnapshot
from app.services.market_data import get_fx_rate, get_technicals

_ANALYSIS_CACHE: dict[str, tuple[float, AnalysisResult]] = {}
ANALYSIS_CACHE_TTL_SECONDS = 180


def _analysis_cache_get(key: str) -> AnalysisResult | None:
    item = _ANALYSIS_CACHE.get(key)
    if not item:
        return None
    created_at, value = item
    if time.time() - created_at > ANALYSIS_CACHE_TTL_SECONDS:
        _ANALYSIS_CACHE.pop(key, None)
        return None
    return value


def _analysis_cache_set(key: str, value: AnalysisResult) -> AnalysisResult:
    if len(_ANALYSIS_CACHE) > 160:
        oldest_keys = sorted(_ANALYSIS_CACHE, key=lambda item: _ANALYSIS_CACHE[item][0])[:40]
        for old_key in oldest_keys:
            _ANALYSIS_CACHE.pop(old_key, None)
    _ANALYSIS_CACHE[key] = (time.time(), value)
    return value


def _round_level(value: float | None) -> float | None:
    if value is None:
        return None
    if value >= 1000:
        return round(value, 2)
    if value >= 1:
        return round(value, 4)
    return round(value, 8)


def rules_based_analysis(technicals: TechnicalSnapshot) -> dict[str, Any]:
    score = 50
    reasons: list[str] = []
    bias = "neutral"
    risk = "medium"
    setup = "No clear setup"

    price = technicals.last_price
    rsi = technicals.rsi14
    macd_hist = technicals.macd_histogram
    vol_ratio = technicals.volume_ratio20
    atr = technicals.atr14
    performance = technicals.change_percent

    if technicals.trend == "bullish":
        score += 14
        reasons.append("Long-term trend remains constructive above key moving averages.")
    elif technicals.trend == "bearish":
        score -= 14
        reasons.append("Trend structure is weak below key moving averages.")
    elif technicals.trend == "neutral":
        reasons.append("EMA structure is mixed, so trend confirmation is weak.")

    if price is not None:
        above_short = technicals.ema20 is not None and price >= technicals.ema20
        above_mid = technicals.ema50 is not None and price >= technicals.ema50
        above_long = technicals.ema200 is not None and price >= technicals.ema200
        aligned_count = sum([above_short, above_mid, above_long])
        score += (aligned_count - 1) * 4
        if above_long and not above_short:
            reasons.append("Short-term momentum softened while the broader structure remains above long-term trend support.")

    if rsi is not None:
        if 45 <= rsi <= 55:
            reasons.append("RSI is neutral and lacks strong momentum conviction.")
        elif 55 < rsi <= 65:
            score += 7
            reasons.append("RSI is in a healthy bullish momentum zone.")
        elif 65 < rsi <= 75:
            score += 3
            reasons.append("RSI is strong but getting extended; the stock may pause after a fast move.")
        elif rsi > 75:
            score -= 6
            reasons.append("RSI is overextended; the stock may have risen too quickly and could pull back.")
        elif 35 <= rsi < 45:
            score -= 5
            reasons.append("RSI shows weakening momentum but is not yet oversold.")
        elif rsi < 35:
            score -= 8
            reasons.append("RSI is oversold; trend may be weak, but a relief bounce is possible.")

    if macd_hist is not None:
        if macd_hist > 0:
            score += 6
            reasons.append("MACD histogram is positive, which suggests momentum is improving.")
        elif macd_hist < 0:
            score -= 6
            reasons.append("MACD histogram is negative, which suggests momentum is weakening.")

    if performance is not None:
        if performance >= 20:
            score += 5
            reasons.append("Selected-timeframe performance is strongly positive, adding trend confirmation.")
        elif performance >= 5:
            score += 3
            reasons.append("Selected-timeframe performance is positive, which supports the setup.")
        elif performance <= -20:
            score -= 5
            reasons.append("Selected-timeframe performance is deeply negative, so recovery needs confirmation.")
        elif performance <= -5:
            score -= 3
            reasons.append("Selected-timeframe performance is negative, which weakens the setup.")

    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            score += 6
            reasons.append("Volume is significantly above average, showing stronger trader participation.")
        elif vol_ratio < 0.7:
            score -= 5
            reasons.append("Volume is below average, so the move currently has weaker trader participation.")

    if technicals.bb_percent is not None:
        if technicals.bb_percent > 1:
            score -= 3
            reasons.append("Price is stretched above the upper Bollinger range, increasing pullback risk.")
        elif technicals.bb_percent > 0.8:
            score -= 1
            reasons.append("Price trades near the upper Bollinger range, so chasing strength carries more risk.")
        elif 0.2 <= technicals.bb_percent <= 0.8:
            reasons.append("Price remains inside neutral Bollinger positioning.")
        elif technicals.bb_percent < 0:
            score -= 3
            reasons.append("Price is below the lower Bollinger range, confirming downside pressure but also possible oversold conditions.")

    if price is not None and atr is not None and price > 0:
        atr_percent = (atr / price) * 100
        if atr_percent > 6:
            risk = "high"
            score -= 5
            reasons.append("ATR volatility is high; position sizing should be conservative.")
        elif atr_percent < 2:
            risk = "low"
            reasons.append("ATR volatility is relatively low.")

    score = max(0, min(100, score))

    if score >= 68:
        bias = "bullish"
        setup = "Bullish watchlist candidate"
    elif score <= 38:
        bias = "bearish"
        setup = "Weak setup"
    else:
        bias = "neutral"
        setup = "Wait for confirmation"

    invalidation_level = None
    watch_levels: list[float] = []
    if price is not None:
        if technicals.ema20:
            watch_levels.append(_round_level(technicals.ema20))
        if technicals.ema50:
            watch_levels.append(_round_level(technicals.ema50))
        if technicals.ema200:
            watch_levels.append(_round_level(technicals.ema200))
        if atr:
            if bias == "bullish":
                invalidation_level = _round_level(price - 1.5 * atr)
            elif bias == "bearish":
                invalidation_level = _round_level(price + 1.5 * atr)

    if not reasons:
        reasons.append("Not enough clean technical data to create a strong signal.")

    return {
        "score": score,
        "risk": risk,
        "bias": bias,
        "setup": setup,
        "reasons": reasons,
        "invalidation_level": invalidation_level,
        "watch_levels": [v for v in watch_levels if v is not None],
    }


def _timeframe_note(timeframe: str) -> str:
    raw = timeframe or "1d"
    tf = (timeframe or "1d").lower()
    if tf in {"1m", "5m", "15m"} or raw == "1D":
        return "Intraday view focused on short-term movement; signals can change quickly."
    if tf in {"1h", "4h"}:
        return "Swing momentum view focused on timing and short-term structure."
    if tf in {"1w", "5y", "max"}:
        return "Long-term structure view focused on major trend direction and broader risk."
    if tf in {"1y"}:
        return "One-year performance view focused on the broader trend, moving averages, and confirmation strength."
    if tf in {"1m", "6m"}:
        return "Multi-week to multi-month view focused on trend quality, momentum, and participation."
    return "Daily swing view focused on broader trend, moving averages, volume, and momentum."


def _analysis_sections(technicals: TechnicalSnapshot, base: dict[str, Any]) -> dict[str, str]:
    price = technicals.last_price
    rsi = technicals.rsi14
    macd_hist = technicals.macd_histogram
    vol_ratio = technicals.volume_ratio20
    bb = technicals.bb_percent
    atr = technicals.atr14

    trend = "Trend confirmation is mixed because price is not clearly aligned across short-, medium-, and long-term averages."
    if price is not None:
        above20 = technicals.ema20 is not None and price >= technicals.ema20
        above50 = technicals.ema50 is not None and price >= technicals.ema50
        above200 = technicals.ema200 is not None and price >= technicals.ema200
        if above20 and above50 and above200:
            trend = "Trend is constructive with price holding above EMA20, EMA50, and EMA200."
        elif above50 and above200 and not above20:
            trend = "Short-term trend softened below EMA20, while the broader trend remains constructive above EMA50 and EMA200."
        elif not above50 and not above200:
            trend = "Trend structure is weak because price is below important medium- and long-term averages."

    momentum = "Momentum is unclear because RSI or MACD data is incomplete."
    if rsi is not None:
        if 45 <= rsi <= 55:
            momentum = "RSI is neutral and lacks strong momentum conviction."
        elif rsi > 70:
            momentum = "RSI is overextended, meaning the asset may have moved too quickly and could pause or pull back."
        elif rsi < 30:
            momentum = "RSI is oversold, showing weak pressure but also possible bounce risk."
        elif macd_hist is not None and macd_hist > 0:
            momentum = "Momentum remains constructive with RSI outside the neutral zone and MACD histogram positive."
        elif macd_hist is not None and macd_hist < 0:
            momentum = "Momentum is weakening because MACD histogram is negative."

    volume = "Volume confirmation is unclear."
    if vol_ratio is not None:
        if vol_ratio >= 1.2:
            volume = "Volume is above average, which supports the move with stronger trader participation."
        elif vol_ratio < 0.8:
            volume = "Volume is below average, reducing confirmation because participation is weaker."
        else:
            volume = "Volume is close to average, giving only moderate confirmation."

    volatility = "Volatility positioning is neutral."
    if bb is not None:
        if bb > 0.85:
            volatility = "Price trades near the upper Bollinger range, so the setup may be stretched in the short term."
        elif bb < 0.15:
            volatility = "Price trades near the lower Bollinger range, showing downside pressure or possible oversold positioning."
        else:
            volatility = "Price remains inside neutral Bollinger positioning."
    if price is not None and atr is not None and price > 0:
        atr_percent = (atr / price) * 100
        if atr_percent > 6:
            volatility += " ATR is elevated, so price swings may be wider than usual."
        elif atr_percent < 2:
            volatility += " ATR is contained, suggesting calmer price movement."

    risk = f"Risk is {base['risk']} based on volatility, momentum confirmation, and trend quality."
    conclusion = f"Overall, this is a {base['bias']} setup with a {base['score']}/100 score; confirmation matters before relying on the signal."
    return {
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "volatility": volatility,
        "risk": risk,
        "conclusion": conclusion,
    }


def _traffic_light(technicals: TechnicalSnapshot, base: dict[str, Any]) -> str:
    score = base["score"]
    risk = base["risk"]
    bias = base["bias"]
    macd_hist = technicals.macd_histogram
    rsi = technicals.rsi14
    if bias == "bearish" or score <= 35 or (risk == "high" and score < 55):
        return "red"
    if bias == "bullish" and score >= 70 and risk != "high" and (macd_hist is None or macd_hist >= 0) and (rsi is None or rsi < 76):
        return "green"
    return "orange"


def _confidence(technicals: TechnicalSnapshot, base: dict[str, Any]) -> str:
    score = base["score"]
    risk = base["risk"]
    aligned = 0
    if technicals.trend in {"bullish", "bearish"}:
        aligned += 1
    if technicals.macd_histogram is not None and technicals.macd_histogram > 0 and base["bias"] == "bullish":
        aligned += 1
    if technicals.volume_ratio20 is not None and technicals.volume_ratio20 >= 1:
        aligned += 1
    if score >= 75 and risk != "high" and aligned >= 2:
        return "high"
    if risk == "high" or 43 <= score <= 57:
        return "low"
    return "medium"


def _position_state(technicals: TechnicalSnapshot, base: dict[str, Any]) -> str:
    rsi = technicals.rsi14
    macd_hist = technicals.macd_histogram
    bias = base["bias"]
    if rsi is not None and rsi > 75:
        return "overextended"
    if bias == "bullish" and technicals.trend == "bullish" and (macd_hist is None or macd_hist >= 0):
        return "bullish continuation"
    if bias == "bearish" and (macd_hist is None or macd_hist < 0):
        return "bearish pressure"
    if rsi is not None and rsi < 45 and macd_hist is not None and macd_hist > 0:
        return "recovery attempt"
    if technicals.trend == "neutral" and macd_hist is not None and macd_hist > 0:
        return "trend reversal attempt"
    if rsi is not None and rsi < 50:
        return "weak momentum"
    return "mixed consolidation"


def _display_currency_snapshot(technicals: TechnicalSnapshot, display_currency: str | None) -> TechnicalSnapshot:
    target = (display_currency or technicals.quote_currency or "USD").upper()
    source = (technicals.quote_currency or "USD").upper()
    if target == source:
        return technicals

    fx = get_fx_rate(source, target)
    rate = fx.get("rate") if isinstance(fx, dict) else None
    if rate in (None, 0):
        return technicals

    monetary_fields = [
        "last_price",
        "previous_close",
        "change_absolute",
        "ema20",
        "ema50",
        "ema200",
        "sma20",
        "sma50",
        "sma200",
        "bb_middle",
        "bb_upper",
        "bb_lower",
        "bb_width",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr14",
    ]
    updates = {"quote_currency": target}
    for field in monetary_fields:
        value = getattr(technicals, field, None)
        updates[field] = value * rate if value is not None else None
    return technicals.model_copy(update=updates)


def _fallback_ai_signal(technicals: TechnicalSnapshot, base: dict[str, Any]) -> AISignal:
    symbol = technicals.symbol.upper()
    timeframe = technicals.timeframe
    score = base["score"]
    risk = base["risk"]
    bias = base["bias"]
    currency = (technicals.quote_currency or "USD").upper()
    price_text = f"{currency} {technicals.last_price:.2f}" if technicals.last_price is not None else "unavailable"
    change_text = f"{technicals.change_percent:.2f}%" if technicals.change_percent is not None else "unavailable"
    rsi_text = f"{technicals.rsi14:.1f}" if technicals.rsi14 is not None else "unavailable"
    sections = _analysis_sections(technicals, base)
    tf_note = _timeframe_note(timeframe)
    position_state = _position_state(technicals, base)
    traffic_light = _traffic_light(technicals, base)
    confidence = _confidence(technicals, base)
    article = "an" if position_state[:1].lower() in {"a", "e", "i", "o", "u"} else "a"

    if technicals.last_price is None:
        provider_note = " ".join(technicals.notes or [])
        summary = (
            f"Market data is unavailable for {symbol} on the selected {timeframe} timeframe. "
            "The backend could not build a reliable technical view from the current provider response. "
            "Try another exchange listing, a different timeframe, or check provider coverage. "
            f"{provider_note} Not financial advice."
        ).strip()
        return AISignal(
            ai_summary=summary,
            traffic_light="orange",
            confidence="low",
            position_state="mixed consolidation",
            main_reasons=[
                "Latest price data is unavailable.",
                "Technical indicators cannot be trusted without candles.",
                "Try another listing or timeframe.",
            ],
            timeframe_note=_timeframe_note(timeframe),
            not_financial_advice=True,
        )

    summary = (
        f"{symbol} shows a {tf_note.lower()} Latest quote is near {price_text} with change at {change_text}. "
        f"{sections['trend']} {sections['momentum']} {sections['volume']} {sections['volatility']} "
        f"{sections['conclusion']} This looks like {article} {position_state} setup with {risk} risk. Not financial advice."
    )

    return AISignal(
        ai_summary=summary,
        traffic_light=traffic_light,
        confidence=confidence,
        position_state=position_state,
        main_reasons=[sections["trend"], sections["momentum"], sections["volume"]][:3],
        timeframe_note=tf_note,
        not_financial_advice=True,
    )


def _openai_ai_signal(technicals: TechnicalSnapshot, base: dict[str, Any]) -> AISignal | None:
    settings = get_settings()
    if not settings.openai_api_key or technicals.last_price is None:
        return None

    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "technicals": technicals.model_dump(),
        "rules_based_result": base,
    }

    fallback = _fallback_ai_signal(technicals, base)
    system_prompt = "You are a careful trading analyst assistant. Return only valid JSON. Never promise returns."
    user_prompt = (
        "Analyze this market setup and return exactly this JSON shape: "
        "{\"ai_summary\":\"60-100 word professional paragraph ending with Not financial advice.\","
        "\"traffic_light\":\"green|orange|red\",\"confidence\":\"low|medium|high\","
        "\"position_state\":\"bullish continuation|mixed consolidation|bearish pressure|overextended|recovery attempt|weak momentum|trend reversal attempt\","
        "\"main_reasons\":[\"reason 1\",\"reason 2\",\"reason 3\"],"
        "\"timeframe_note\":\"timeframe-specific note\",\"not_financial_advice\":true}. "
        "Internally cover Trend, Momentum, Volume, Volatility, Risk, and Conclusion. "
        "Separate short-term momentum from long-term trend. Explain technical terms in beginner-friendly language without turning it into a tutorial. "
        "If any market data field is null or unavailable, say it is unavailable; do not invent prices, earnings dates, indicators, or provider coverage. "
        "If you mention price, include the quote_currency code from the technicals data. "
        "Avoid buy now, sell now, and guaranteed profit. Make the summary timeframe-aware, concise, and professional.\n\n"
        f"DATA:\n{json.dumps(payload, indent=2)}"
    )

    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        data = json.loads(response.output_text.strip())
        data["not_financial_advice"] = True
        data.setdefault("main_reasons", fallback.main_reasons)
        data.setdefault("timeframe_note", fallback.timeframe_note)
        return AISignal(**data)
    except Exception:
        return None


def analyze_symbol(symbol: str, timeframe: str = "1d", include_ai: bool = True, display_currency: str | None = None) -> AnalysisResult:
    cache_key = f"{symbol.strip().upper()}:{timeframe}:{(display_currency or '').upper()}:{include_ai}"
    cached = _analysis_cache_get(cache_key)
    if cached is not None:
        return cached
    technicals = get_technicals(symbol=symbol, timeframe=timeframe)
    display_technicals = _display_currency_snapshot(technicals, display_currency)
    base = rules_based_analysis(display_technicals)
    ai_signal = _openai_ai_signal(display_technicals, base) if include_ai else None
    if ai_signal is None:
        ai_signal = _fallback_ai_signal(display_technicals, base)

    return _analysis_cache_set(cache_key, AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        logo_url=display_technicals.logo_url,
        score=base["score"],
        risk=base["risk"],
        bias=base["bias"],
        setup=base["setup"],
        reasons=base["reasons"],
        invalidation_level=base["invalidation_level"],
        watch_levels=base["watch_levels"],
        technicals=display_technicals,
        ai_commentary=ai_signal.ai_summary,
        ai_signal=ai_signal,
    ))
