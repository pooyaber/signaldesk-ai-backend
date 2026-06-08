from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from pydantic import BaseModel, Field

from app.models import AnalyzeRequest, ScanRequest, TradingViewAlert
try:
    from app.models import AuthLoginRequest, AuthRegisterRequest
except ImportError:
    class AuthRegisterRequest(BaseModel):
        email: str = Field(..., examples=["user@example.com"])
        password: str = Field(..., min_length=8)
        display_name: str | None = Field(default=None, examples=["Pooya"])

    class AuthLoginRequest(BaseModel):
        email: str = Field(..., examples=["user@example.com"])
        password: str = Field(..., min_length=1)
from app.security import verify_webhook_token
from app.services.analysis import analyze_symbol
from app.services.chart_render import render_chart_dashboard
from app.services.deep_analysis import get_deep_analysis
from app.services.market_data import cache_stats, get_chart_data, get_fx_rate, search_symbols
from app.services.storage import init_db, list_signals, save_analysis
from app.services.telegram import notify_analysis

try:
    from app.services.auth import login_user, logout_user, register_user, user_from_token
except ImportError:
    login_user = logout_user = register_user = user_from_token = None

app = FastAPI(
    title="TradingView AI Backend",
    description="Receives TradingView alerts, analyzes symbols, stores signals, and optionally sends Telegram alerts.",
    version="0.1.0",
)

settings = get_settings()
logger = logging.getLogger("signaldesk")
_RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.middleware("http")
async def request_timer(request: Request, call_next):
    started = time.perf_counter()
    limit = max(0, int(settings.rate_limit_per_minute or 0))
    if limit:
        forwarded_for = request.headers.get("x-forwarded-for") or ""
        client_ip = forwarded_for.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")
        now = time.time()
        window_start = now - 60
        bucket = [stamp for stamp in _RATE_LIMIT_BUCKETS.get(client_ip, []) if stamp >= window_start]
        if len(bucket) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please wait a moment and try again.",
                    "retry_after_seconds": 60,
                },
            )
        bucket.append(now)
        _RATE_LIMIT_BUCKETS[client_ip] = bucket
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.exception("request_failed path=%s method=%s elapsed_ms=%s", request.url.path, request.method, elapsed_ms)
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400 or elapsed_ms > 2500:
        logger.warning(
            "request_complete path=%s method=%s status=%s elapsed_ms=%s",
            request.url.path,
            request.method,
            response.status_code,
            elapsed_ms,
        )
    return response

@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "providers": {
            "twelve_data": bool(settings.twelve_data_api_key),
            "openai": bool(settings.openai_api_key),
        },
    }


@app.get("/provider-status")
def provider_status() -> dict:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "providers": {
            "market_data_primary": "twelve_data",
            "twelve_data_configured": bool(settings.twelve_data_api_key),
            "yahoo_fallback_enabled": True,
            "openai_configured": bool(settings.openai_api_key),
        },
        "cache": cache_stats(),
        "rate_limit_per_minute": settings.rate_limit_per_minute,
    }


@app.post("/auth/register")
def auth_register(req: AuthRegisterRequest) -> dict:
    if register_user is None:
        return {"error": "auth_unavailable", "detail": "Account login is not enabled on this backend deployment."}
    return register_user(email=req.email, password=req.password, display_name=req.display_name)


@app.post("/auth/login")
def auth_login(req: AuthLoginRequest) -> dict:
    if login_user is None:
        return {"error": "auth_unavailable", "detail": "Account login is not enabled on this backend deployment."}
    return login_user(email=req.email, password=req.password)


@app.get("/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict:
    if user_from_token is None:
        return {"user": None, "error": "auth_unavailable"}
    return {"user": user_from_token(authorization)}


@app.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict:
    if logout_user is None:
        return {"ok": True, "error": "auth_unavailable"}
    return logout_user(authorization)


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
def analyze(req: AnalyzeRequest, force_refresh: bool = Query(default=False)) -> dict:
    refresh = bool(req.force_refresh or force_refresh)
    result = analyze_symbol(
        req.symbol,
        req.timeframe,
        include_ai=req.include_ai,
        display_currency=req.display_currency,
        force_refresh=refresh,
    )
    technicals = result.technicals
    if technicals.last_price is None:
        logger.warning(
            "analysis_missing_price symbol=%s timeframe=%s mapped_symbol=%s notes=%s",
            req.symbol,
            req.timeframe,
            technicals.mapped_symbol,
            technicals.notes,
        )
    signal_id, save_error = save_analysis_safely(result)
    if save_error:
        logger.warning("analysis_save_failed symbol=%s error=%s", req.symbol, save_error)
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
def chart(symbol: str = "AAPL", range: str = "6M", force_refresh: bool = Query(default=False)) -> dict:
    result = get_chart_data(symbol=symbol, range_key=range, force_refresh=force_refresh)
    if not result.get("points"):
        logger.warning("chart_empty symbol=%s range=%s", symbol, range)
    return result


@app.get("/symbols")
def symbols(q: str = "", limit: int = 12) -> dict:
    result = search_symbols(query=q, limit=limit)
    if q and not result.get("results"):
        logger.warning("symbol_search_empty query=%s limit=%s", q, limit)
    return result


@app.get("/deep-analysis")
def deep_analysis(symbol: str = "AAPL", currency: str = "USD", exchange: str | None = None, asset_type: str | None = None) -> dict:
    return get_deep_analysis(symbol=symbol, currency=currency, exchange=exchange, asset_type=asset_type)


@app.get("/fx")
def fx(base: str = "USD", quote: str = "EUR") -> dict:
    return get_fx_rate(base=base, quote=quote)


