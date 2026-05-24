from __future__ import annotations

import httpx

from app.config import get_settings
from app.models import AnalysisResult


def format_signal_message(result: AnalysisResult) -> str:
    price = result.technicals.last_price
    price_text = f"{price:,.4f}" if price is not None and price < 1000 else f"{price:,.2f}" if price else "n/a"
    reasons = "\n".join([f"• {reason}" for reason in result.reasons[:5]])
    ai = f"\n\nAI:\n{result.ai_commentary}" if result.ai_commentary else ""

    return (
        f"📊 {result.symbol} / {result.timeframe}\n"
        f"Price: {price_text}\n"
        f"Score: {result.score}/100\n"
        f"Bias: {result.bias}\n"
        f"Risk: {result.risk}\n"
        f"Setup: {result.setup}\n\n"
        f"Reasons:\n{reasons}\n\n"
        f"Invalidation: {result.invalidation_level or 'n/a'}\n"
        f"Watch levels: {', '.join(map(str, result.watch_levels)) or 'n/a'}"
        f"{ai}"
    )


async def send_telegram_message(text: str) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    return True


async def notify_analysis(result: AnalysisResult) -> bool:
    return await send_telegram_message(format_signal_message(result))
