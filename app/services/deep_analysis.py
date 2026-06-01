from __future__ import annotations

from typing import Any

import yfinance as yf

from app.services.market_data import get_logo_url, get_quote_currency, map_symbol


SECTION_SUBTITLES = {
    "Business Overview": "What the company does and its key revenue streams",
    "Financial Health": "Revenue growth, profitability, balance sheet and cash flow",
    "Valuation": "Valuation multiples and fair value assessment",
    "Competitive Position": "Industry position, competitive advantages and market share",
    "Growth Drivers": "Key growth catalysts and future opportunities",
    "Risks": "Business, industry and macroeconomic risks",
    "Upcoming Catalysts": "Earnings, product launches, events and key catalysts",
    "Market Sentiment": "Analyst ratings, institutional activity and news sentiment",
    "Final Investment Summary": "Overall conclusion and investment perspective",
}


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: Any) -> str:
    n = _num(value)
    return "Data unavailable" if n is None else f"{n * 100:.1f}%"


def _fmt_multiple(value: Any) -> str:
    n = _num(value)
    return "Data unavailable" if n is None else f"{n:.1f}x"


def _market_cap_category(market_cap: Any) -> str:
    value = _num(market_cap)
    if value is None:
        return "Data unavailable"
    if value >= 200_000_000_000:
        return "Mega Cap"
    if value >= 10_000_000_000:
        return "Large Cap"
    if value >= 2_000_000_000:
        return "Mid Cap"
    return "Small Cap"


def _score(info: dict[str, Any]) -> tuple[float, str, str]:
    score = 5.0
    profit_margin = _num(info.get("profitMargins"))
    revenue_growth = _num(info.get("revenueGrowth"))
    debt_to_equity = _num(info.get("debtToEquity"))
    free_cashflow = _num(info.get("freeCashflow"))
    forward_pe = _num(info.get("forwardPE") or info.get("trailingPE"))

    if profit_margin is not None:
        score += 1.0 if profit_margin >= 0.18 else -0.7 if profit_margin < 0.03 else 0.2
    if revenue_growth is not None:
        score += 1.0 if revenue_growth >= 0.12 else -0.6 if revenue_growth < 0 else 0.2
    if debt_to_equity is not None:
        score += 0.5 if debt_to_equity <= 80 else -0.8 if debt_to_equity > 180 else 0
    if free_cashflow is not None:
        score += 0.6 if free_cashflow > 0 else -0.6
    if forward_pe is not None:
        score += 0.4 if forward_pe <= 25 else -0.5 if forward_pe > 60 else 0

    score = round(max(0, min(10, score)), 1)
    if score >= 7:
        return score, "Favorable", "Medium Risk" if forward_pe and forward_pe > 45 else "Low Risk"
    if score >= 5:
        return score, "Neutral", "Medium Risk"
    if score >= 3.5:
        return score, "Caution", "Medium Risk"
    return score, "Risky", "High Risk"


def _section(title: str, content: str) -> dict[str, str]:
    return {
        "title": title,
        "subtitle": SECTION_SUBTITLES[title],
        "content": content or "Data unavailable. This is not financial advice.",
    }


def get_deep_analysis(symbol: str, currency: str = "USD", exchange: str | None = None, asset_type: str | None = None) -> dict[str, Any]:
    mapped = map_symbol(symbol)
    ticker = yf.Ticker(mapped)
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    name = info.get("longName") or info.get("shortName") or mapped.upper()
    quote_currency = (currency or info.get("currency") or get_quote_currency(mapped) or "USD").upper()
    sector = info.get("sector") or "Data unavailable"
    industry = info.get("industry") or "Data unavailable"
    market_cap_category = _market_cap_category(info.get("marketCap"))
    score, rating, risk = _score(info)
    business = info.get("longBusinessSummary") or "Business description is unavailable from the current data source."

    summary = (
        f"{name} has a {rating.lower()} fundamental profile with a {score}/10 score. "
        f"The view reflects available growth, profitability, valuation, balance sheet and cash flow data. "
        "This is not financial advice."
    )

    sections = [
        _section("Business Overview", f"{business} This is not financial advice."),
        _section(
            "Financial Health",
            f"Revenue growth: {_fmt_pct(info.get('revenueGrowth'))}. Profit margin: {_fmt_pct(info.get('profitMargins'))}. "
            f"Operating margin: {_fmt_pct(info.get('operatingMargins'))}. Free cash flow: {info.get('freeCashflow', 'Data unavailable')}. "
            "This helps show whether the business is growing profitably and funding itself. This is not financial advice.",
        ),
        _section(
            "Valuation",
            f"Trailing P/E: {_fmt_multiple(info.get('trailingPE'))}. Forward P/E: {_fmt_multiple(info.get('forwardPE'))}. "
            f"Price to sales: {_fmt_multiple(info.get('priceToSalesTrailing12Months'))}. "
            "Higher multiples can reflect quality or growth expectations, but also raise valuation risk. This is not financial advice.",
        ),
        _section(
            "Competitive Position",
            f"Sector: {sector}. Industry: {industry}. Market cap category: {market_cap_category}. "
            "A stronger competitive position usually comes from scale, brand, technology, distribution, or switching costs. This is not financial advice.",
        ),
        _section(
            "Growth Drivers",
            "Potential drivers may include revenue expansion, margin improvement, product cycles, sector demand, and execution against strategic priorities. "
            "Specific catalyst data may be unavailable from the current data source. This is not financial advice.",
        ),
        _section(
            "Risks",
            f"Key risks can include valuation pressure, competition, margin compression, debt levels, execution risk, and macroeconomic weakness. "
            f"Debt to equity: {info.get('debtToEquity', 'Data unavailable')}. This is not financial advice.",
        ),
        _section(
            "Upcoming Catalysts",
            f"Next earnings date: {info.get('earningsDate', 'Data unavailable')}. Watch earnings, guidance updates, product news, regulation, and sector news. "
            "This is not financial advice.",
        ),
        _section(
            "Market Sentiment",
            f"Recommendation: {info.get('recommendationKey', 'Data unavailable')}. Analyst target mean: {info.get('targetMeanPrice', 'Data unavailable')}. "
            "Sentiment can change quickly and should be checked against current news. This is not financial advice.",
        ),
        _section(
            "Final Investment Summary",
            f"Overall, {name} receives a {rating} fundamental view with {risk.lower()}. "
            "Use this as a structured research snapshot, not as a recommendation. This is not financial advice.",
        ),
    ]

    return {
        "symbol": symbol.upper(),
        "mapped_symbol": mapped.upper(),
        "name": name,
        "exchange": exchange or info.get("exchange") or info.get("fullExchangeName") or "Data unavailable",
        "currency": quote_currency,
        "asset_type": asset_type or info.get("quoteType") or "Equity",
        "sector": sector,
        "industry": industry,
        "market_cap_category": market_cap_category,
        "logo_url": get_logo_url(mapped),
        "fundamental_score": score,
        "rating": rating,
        "risk": risk,
        "summary": summary,
        "sections": sections,
        "not_financial_advice": True,
    }
