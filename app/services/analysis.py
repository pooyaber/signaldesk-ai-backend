from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import get_settings
from app.models import AISignal, AnalysisResult, TechnicalSnapshot
from app.services.market_data import get_technicals


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

    if technicals.trend == "bullish":
        score += 20
        reasons.append("Price is above EMA20, EMA50, and EMA200 with bullish EMA alignment.")
    elif technicals.trend == "bearish":
        score -= 20
        reasons.append("Price is below EMA20, EMA50, and EMA200 with bearish EMA alignment.")
    elif technicals.trend == "neutral":
        reasons.append("EMA structure is mixed, so trend confirmation is weak.")

    if rsi is not None:
        if 50 <= rsi <= 65:
            score += 10
            reasons.append("RSI is in a healthy bullish momentum zone.")
        elif 65 < rsi <= 75:
            score += 5
            reasons.append("RSI is strong but getting extended.")
        elif rsi > 75:
            score -= 7
            reasons.append("RSI is overextended; pullback risk is higher.")
        elif 35 <= rsi < 50:
            score -= 5
            reasons.append("RSI is below the bullish zone and momentum is weak.")
        elif rsi < 35:
            score -= 10
            reasons.append("RSI is oversold; trend may be weak, but bounce risk exists.")

    if macd_hist is not None:
        if macd_hist > 0:
            score += 8
            reasons.append("MACD histogram is positive, supporting bullish momentum.")
        elif macd_hist < 0:
            score -= 8
            reasons.append("MACD histogram is negative, supporting bearish momentum.")

    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            score += 8
            reasons.append("Volume is significantly above the 20-period average.")
        elif vol_ratio < 0.7:
            score -= 4
            reasons.append("Volume is below average, so conviction is weaker.")

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

    if score >= 70:
        bias = "bullish"
        setup = "Bullish watchlist candidate"
    elif score <= 35:
        bias = "bearish"
        setup = "Avoid or short-bias candidate"
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
    if timeframe in {"1m", "5m", "15m"}:
        return "Intraday view focused on short-term movement; signals can change quickly."
    if timeframe in {"1h", "4h"}:
        return "Swing momentum view focused on timing and short-term structure."
    if timeframe == "1w":
        return "Long-term structure view focused on major trend direction and broader risk."
    return "Daily swing view focused on broader trend, moving averages, volume, and momentum."


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
    macd_text = "positive" if (technicals.macd_histogram or 0) > 0 else "negative" if technicals.macd_histogram is not None else "unclear"
    volume_text = "above average" if (technicals.volume_ratio20 or 0) >= 1 else "below average" if technicals.volume_ratio20 is not None else "unclear"
    tf_note = _timeframe_note(timeframe)
    position_state = _position_state(technicals, base)
    traffic_light = _traffic_light(technicals, base)
    confidence = _confidence(technicals, base)
    article = "an" if position_state[:1].lower() in {"a", "e", "i", "o", "u"} else "a"

    summary = (
        f"{symbol} shows a {tf_note.lower()} Latest quote is near {price_text} with change at {change_text}. "
        f"The setup is currently {bias} with a {score}/100 score, RSI near {rsi_text}, MACD momentum {macd_text}, "
        f"and volume {volume_text}. Risk is {risk}, so this looks like {article} {position_state} setup that should be watched "
        f"for confirmation rather than treated as a direct trade instruction. Not financial advice."
    )

    return AISignal(
        ai_summary=summary,
        traffic_light=traffic_light,
        confidence=confidence,
        position_state=position_state,
        main_reasons=base["reasons"][:3],
        timeframe_note=tf_note,
        not_financial_advice=True,
    )


def _openai_ai_signal(technicals: TechnicalSnapshot, base: dict[str, Any]) -> AISignal | None:
    settings = get_settings()
    if not settings.openai_api_key:
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
        "If you mention price, include the quote_currency code from the technicals data. "
        "Avoid buy now, sell now, and guaranteed profit. Make the summary timeframe-aware.\n\n"
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


def analyze_symbol(symbol: str, timeframe: str = "1d", include_ai: bool = True) -> AnalysisResult:
    technicals = get_technicals(symbol=symbol, timeframe=timeframe)
    base = rules_based_analysis(technicals)
    ai_signal = _openai_ai_signal(technicals, base) if include_ai else None
    if ai_signal is None:
        ai_signal = _fallback_ai_signal(technicals, base)

    return AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        logo_url=technicals.logo_url,
        score=base["score"],
        risk=base["risk"],
        bias=base["bias"],
        setup=base["setup"],
        reasons=base["reasons"],
        invalidation_level=base["invalidation_level"],
        watch_levels=base["watch_levels"],
        technicals=technicals,
        ai_commentary=ai_signal.ai_summary,
        ai_signal=ai_signal,
    )
