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

FALLBACK_PROFILES = {
    "NVDA": {
        "name": "NVIDIA Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "business": "NVIDIA designs graphics processors, AI accelerators, networking hardware, and software platforms used in gaming, data centers, artificial intelligence, visualization, and automotive computing.",
        "competitive": "NVIDIA has a strong position in AI infrastructure through GPU hardware, CUDA software, networking, and a broad developer ecosystem.",
        "drivers": "Key growth drivers include AI data center demand, accelerator upgrades, networking, enterprise AI adoption, and software ecosystem expansion.",
        "risks": "Key risks include high valuation expectations, competition from custom chips and other semiconductor firms, supply constraints, export restrictions, and cyclical demand.",
    },
    "AAPL": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "business": "Apple designs iPhone, Mac, iPad, wearables, services, and software ecosystems supported by a global hardware and services business.",
        "competitive": "Apple benefits from brand strength, hardware and software integration, customer loyalty, services revenue, and a large installed base.",
        "drivers": "Growth drivers include services expansion, device upgrade cycles, wearables, emerging AI features, and ecosystem monetization.",
        "risks": "Key risks include slower device upgrades, China exposure, regulatory pressure, supply chain dependence, and valuation sensitivity.",
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "business": "Microsoft provides cloud computing, productivity software, operating systems, enterprise software, gaming, and AI services.",
        "competitive": "Microsoft has a strong enterprise moat through Azure, Microsoft 365, Windows, developer tools, security products, and AI integration.",
        "drivers": "Growth drivers include Azure cloud demand, AI services, enterprise software adoption, security, productivity tools, and LinkedIn/Gaming monetization.",
        "risks": "Key risks include cloud competition, AI infrastructure spending, regulatory scrutiny, cybersecurity incidents, and valuation expectations.",
    },
    "TSLA": {
        "name": "Tesla, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "business": "Tesla designs and sells electric vehicles, energy storage products, solar solutions, charging infrastructure, and software-enabled vehicle services.",
        "competitive": "Tesla benefits from brand recognition, manufacturing scale, battery expertise, charging network, software capability, and direct customer distribution.",
        "drivers": "Growth drivers include EV adoption, new models, energy storage growth, software features, autonomy development, and manufacturing efficiency.",
        "risks": "Key risks include EV competition, price cuts, margin pressure, execution risk, regulation, demand cyclicality, and high valuation sensitivity.",
    },
    "SPY": {
        "name": "SPDR S&P 500 ETF Trust",
        "sector": "ETF",
        "industry": "Broad Market ETF",
        "business": "SPY is an exchange-traded fund designed to track the S&P 500 Index, providing diversified exposure to large-cap U.S. equities.",
        "competitive": "SPY is one of the most liquid ETFs globally, with broad diversification, tight spreads, and strong institutional adoption.",
        "drivers": "Performance is driven by U.S. large-cap earnings, interest rates, macroeconomic conditions, sector leadership, and market risk appetite.",
        "risks": "Key risks include broad equity market drawdowns, valuation compression, recession risk, interest-rate changes, and concentration in large technology names.",
    },
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


def _fallback_for(symbol: str, info: dict[str, Any]) -> dict[str, Any]:
    clean = symbol.upper().replace(".DE", "").replace(".F", "")
    if clean in FALLBACK_PROFILES:
        return FALLBACK_PROFILES[clean]
    return {
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "sector": info.get("sector") or "Data unavailable",
        "industry": info.get("industry") or "Data unavailable",
        "business": "Detailed business description is unavailable from the current data source.",
        "competitive": "Competitive position data is limited. Review company filings, investor presentations, and industry comparisons for deeper context.",
        "drivers": "Growth drivers are not fully available from the current data source. Watch earnings, guidance, sector trends, and company-specific announcements.",
        "risks": "Risk data is limited. Consider valuation, competition, balance sheet strength, macroeconomic exposure, and execution risk.",
    }


def _fast_info_dict(ticker: yf.Ticker) -> dict[str, Any]:
    try:
        fast = ticker.fast_info
        return {
            "marketCap": getattr(fast, "market_cap", None) or fast.get("marketCap"),
            "currency": getattr(fast, "currency", None) or fast.get("currency"),
            "lastPrice": getattr(fast, "last_price", None) or fast.get("lastPrice"),
        }
    except Exception:
        return {}


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
    fast_info = _fast_info_dict(ticker)
    info = {**fast_info, **info}
    fallback = _fallback_for(mapped.upper(), info)

    name = info.get("longName") or info.get("shortName") or fallback["name"] or mapped.upper()
    quote_currency = (currency or info.get("currency") or get_quote_currency(mapped) or "USD").upper()
    sector = info.get("sector") or fallback["sector"]
    industry = info.get("industry") or fallback["industry"]
    market_cap_category = _market_cap_category(info.get("marketCap"))
    score, rating, risk = _score(info)
    business = info.get("longBusinessSummary") or fallback["business"]

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
        _section("Competitive Position", f"{fallback['competitive']} Sector: {sector}. Industry: {industry}. Market cap category: {market_cap_category}. This is not financial advice."),
        _section(
            "Growth Drivers",
            f"{fallback['drivers']} This is not financial advice.",
        ),
        _section(
            "Risks",
            f"{fallback['risks']} "
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
