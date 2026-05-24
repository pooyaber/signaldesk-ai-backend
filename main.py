from __future__ import annotations

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.models import AnalyzeRequest, ScanRequest, TradingViewAlert
from app.security import verify_webhook_token
from app.services.analysis import analyze_symbol
from app.services.chart_render import render_chart_dashboard
from app.services.market_data import get_chart_data, get_fx_rate, search_symbols
from app.services.storage import init_db, list_signals, save_analysis
from app.services.telegram import notify_analysis

app = FastAPI(
    title="TradingView AI Backend",
    description="Receives TradingView alerts, analyzes symbols, stores signals, and optionally sends Telegram alerts.",
    version="0.1.0",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.app_env}


def save_analysis_safely(result) -> tuple[int | None, str | None]:
    try:
        return save_analysis(result), None
    except Exception as exc:
        return None, str(exc)


@app.get("/", response_class=HTMLResponse)
def dashboard(symbol: str = "AAPL", range: str = "6M") -> str:
    return render_chart_dashboard(symbol=symbol, range_key=range)


@app.post("/webhook/tradingview")
async def tradingview_webhook(
    request: Request,
    token: str | None = Query(default=None),
) -> dict:
    verify_webhook_token(token)

    payload = await request.json()
    alert = TradingViewAlert(**payload, raw=payload)

    result = analyze_symbol(alert.symbol, alert.timeframe, include_ai=True)
    signal_id, save_error = save_analysis_safely(result)
    telegram_sent = await notify_analysis(result)

    return {
        "received": True,
        "signal_id": signal_id,
        "save_error": save_error,
        "telegram_sent": telegram_sent,
        "analysis": result,
    }


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    result = analyze_symbol(req.symbol, req.timeframe, include_ai=req.include_ai)
    signal_id, save_error = save_analysis_safely(result)
    return {"signal_id": signal_id, "save_error": save_error, "analysis": result}


@app.post("/scan")
def scan(req: ScanRequest) -> dict:
    results = []
    for symbol in req.symbols:
        try:
            result = analyze_symbol(symbol, req.timeframe, include_ai=req.include_ai)
            save_analysis_safely(result)
            results.append(result)
        except Exception as exc:
            results.append({"symbol": symbol, "error": str(exc)})

    ranked = sorted(
        results,
        key=lambda item: item.score if hasattr(item, "score") else -1,
        reverse=True,
    )
    return {"count": len(ranked), "results": ranked}


@app.get("/signals")
def recent_signals(limit: int = 50, symbol: str | None = None) -> dict:
    return {"results": list_signals(limit=limit, symbol=symbol)}


@app.get("/chart")
def chart(symbol: str = "AAPL", range: str = "6M") -> dict:
    return get_chart_data(symbol=symbol, range_key=range)


@app.get("/symbols")
def symbols(q: str = "", limit: int = 12) -> dict:
    return search_symbols(query=q, limit=limit)


@app.get("/fx")
def fx(base: str = "USD", quote: str = "EUR") -> dict:
    return get_fx_rate(base=base, quote=quote)
