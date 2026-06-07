from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


class TradingViewAlert(BaseModel):
    symbol: str = Field(..., examples=["BTC-USD", "NVDA", "BTCUSD"])
    exchange: str | None = Field(default=None, examples=["NASDAQ", "BINANCE"])
    timeframe: str = Field(default="1d", examples=["15m", "1h", "2h", "4h", "1d"])
    price: float | str | None = None
    alert_name: str | None = None
    strategy: str | None = None
    note: str | None = None
    raw: dict[str, Any] | None = None


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., examples=["NVDA", "BTC-USD"])
    timeframe: str = Field(default="1d", examples=["1h", "4h", "1d"])
    include_ai: bool = True
    display_currency: Literal["USD", "EUR"] = "USD"


class ScanRequest(BaseModel):
    symbols: list[str] = Field(..., examples=[["NVDA", "AAPL", "MSFT", "BTC-USD"]])
    timeframe: str = "1d"
    include_ai: bool = False


class AuthRegisterRequest(BaseModel):
    email: str = Field(..., examples=["user@example.com"])
    password: str = Field(..., min_length=8)
    display_name: str | None = Field(default=None, examples=["Pooya"])


class AuthLoginRequest(BaseModel):
    email: str = Field(..., examples=["user@example.com"])
    password: str = Field(..., min_length=1)


class TechnicalSnapshot(BaseModel):
    symbol: str
    mapped_symbol: str
    timeframe: str
    asset_name: str | None = None
    logo_url: str | None = None
    quote_currency: str = "USD"
    last_price: float | None = None
    previous_close: float | None = None
    change_absolute: float | None = None
    change_percent: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    bb_middle: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_percent: float | None = None
    bb_width: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    atr14: float | None = None
    volume: float | None = None
    volume_ratio20: float | None = None
    trend: Literal["bullish", "neutral", "bearish", "unknown"] = "unknown"
    notes: list[str] = []


class AISignal(BaseModel):
    ai_summary: str
    traffic_light: Literal["green", "orange", "red"] = "orange"
    confidence: Literal["low", "medium", "high"] = "medium"
    position_state: str = "mixed consolidation"
    main_reasons: list[str] = []
    timeframe_note: str = ""
    not_financial_advice: bool = True


class AnalysisResult(BaseModel):
    symbol: str
    timeframe: str
    logo_url: str | None = None
    score: int = Field(..., ge=0, le=100)
    risk: Literal["low", "medium", "high"]
    bias: Literal["bullish", "neutral", "bearish"]
    setup: str
    reasons: list[str]
    invalidation_level: float | None = None
    watch_levels: list[float] = []
    technicals: TechnicalSnapshot
    ai_commentary: str | None = None
    ai_signal: AISignal | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
