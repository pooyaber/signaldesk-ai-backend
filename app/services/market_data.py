from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf

from app.config import get_settings
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
    "1W": ("7d", "30m"),
    "7D": ("7d", "30m"),
    "1M": ("1mo", "1h"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
    "MAX": ("max", "1mo"),
    "ALL": ("max", "1mo"),
}

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

_MEMORY_CACHE: dict[str, tuple[float, object]] = {}
CACHE_TTL_SECONDS = {
    "symbols": 900,
    "profile": 604800,
    "quote": 60,
    "technicals": 180,
    "chart_intraday": 300,
    "chart_daily": 1800,
    "fx": 3600,
}
MAX_CACHE_ITEMS = 600


def _cache_get(key: str, ttl_seconds: int):
    item = _MEMORY_CACHE.get(key)
    if not item:
        return None
    created_at, value = item
    if time.time() - created_at > ttl_seconds:
        _MEMORY_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value):
    if len(_MEMORY_CACHE) > MAX_CACHE_ITEMS:
        oldest_keys = sorted(_MEMORY_CACHE, key=lambda item: _MEMORY_CACHE[item][0])[:120]
        for old_key in oldest_keys:
            _MEMORY_CACHE.pop(old_key, None)
    _MEMORY_CACHE[key] = (time.time(), value)
    return value


def cache_stats() -> dict:
    now = time.time()
    by_prefix: dict[str, int] = {}
    expired = 0
    for key, (created_at, _value) in list(_MEMORY_CACHE.items()):
        prefix = key.split(":", 1)[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        ttl_key = "chart_daily" if prefix == "chart" else prefix
        ttl = CACHE_TTL_SECONDS.get(ttl_key)
        if ttl is not None and now - created_at > ttl:
            expired += 1
    return {
        "items": len(_MEMORY_CACHE),
        "max_items": MAX_CACHE_ITEMS,
        "expired_items_waiting_cleanup": expired,
        "by_prefix": by_prefix,
        "ttl_seconds": CACHE_TTL_SECONDS,
    }

TWELVE_CHART_RANGE_MAP = {
    "1D": ("5min", 288),
    "1W": ("30min", 336),
    "7D": ("30min", 336),
    "1M": ("1h", 744),
    "6M": ("1day", 190),
    "1Y": ("1day", 370),
    "5Y": ("1week", 280),
    "MAX": ("1month", 1200),
    "ALL": ("1month", 1200),
}

TWELVE_TECHNICAL_INTERVAL_MAP = {
    "1m": ("1min", 500),
    "5m": ("5min", 500),
    "15m": ("15min", 500),
    "30m": ("30min", 500),
    "1h": ("1h", 1000),
    "2h": ("1h", 1000),
    "4h": ("1h", 1000),
    "1d": ("1day", 600),
    "1w": ("1week", 600),
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
    "AMAZON": "AMZN",
    "AMAZONCOM": "AMZN",
    "ALPHABET": "GOOGL",
    "GOOGLE": "GOOGL",
    "NETFLIX": "NFLX",
    "BROADCOM": "AVGO",
    "ORACLE": "ORCL",
    "INTEL": "INTC",
    "PAYPAL": "PYPL",
    "SALESFORCE": "CRM",
    "SHOPIFY": "SHOP",
    "UBER": "UBER",
    "DISNEY": "DIS",
    "VISA": "V",
    "MASTERCARD": "MA",
    "WALMART": "WMT",
    "COSTCO": "COST",
    "EXXON": "XOM",
    "EXXONMOBIL": "XOM",
    "VANGUARDSP500": "VOO",
    "VANGUARDTOTALSTOCK": "VTI",
    "VANGUARDTOTALWORLD": "VT",
    "DOWJONES": "DIA",
    "RUSSELL2000": "IWM",
    "EMERGINGMARKETS": "EEM",
    "SCHD": "SCHD",
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
    {"symbol": "NFLX", "name": "Netflix, Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "ORCL", "name": "Oracle Corporation", "exchange": "NYSE", "type": "Equity"},
    {"symbol": "INTC", "name": "Intel Corporation", "exchange": "NASDAQ", "type": "Equity"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "exchange": "NASDAQ", "type": "ETF"},
    {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "VT", "name": "Vanguard Total World Stock ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "DIA", "name": "SPDR Dow Jones Industrial Average ETF Trust", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "EFA", "name": "iShares MSCI EAFE ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "EEM", "name": "iShares MSCI Emerging Markets ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "SCHD", "name": "Schwab U.S. Dividend Equity ETF", "exchange": "NYSE Arca", "type": "ETF"},
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "exchange": "CCC", "type": "Crypto"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "exchange": "CCC", "type": "Crypto"},
    {"symbol": "SOL-USD", "name": "Solana USD", "exchange": "CCC", "type": "Crypto"},
    {"symbol": "EURUSD=X", "name": "EUR/USD", "exchange": "FX", "type": "Currency"},
]

SYMBOL_PROFILES = {
    "NVDA": "NVIDIA Corporation",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "AMD": "Advanced Micro Devices, Inc.",
    "META": "Meta Platforms, Inc.",
    "TSLA": "Tesla, Inc.",
    "GOOGL": "Alphabet Inc.",
    "GOOG": "Alphabet Inc.",
    "AMZN": "Amazon.com, Inc.",
    "NFLX": "Netflix, Inc.",
    "AVGO": "Broadcom Inc.",
    "ORCL": "Oracle Corporation",
    "INTC": "Intel Corporation",
    "MU": "Micron Technology, Inc.",
    "DELL": "Dell Technologies Inc.",
    "PLTR": "Palantir Technologies Inc.",
    "SPOT": "Spotify Technology S.A.",
    "PYPL": "PayPal Holdings, Inc.",
    "CRM": "Salesforce, Inc.",
    "SHOP": "Shopify Inc.",
    "UBER": "Uber Technologies, Inc.",
    "DIS": "The Walt Disney Company",
    "JPM": "JPMorgan Chase & Co.",
    "V": "Visa Inc.",
    "MA": "Mastercard Incorporated",
    "WMT": "Walmart Inc.",
    "COST": "Costco Wholesale Corporation",
    "XOM": "Exxon Mobil Corporation",
    "VOO": "Vanguard S&P 500 ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "VT": "Vanguard Total World Stock ETF",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "IWM": "iShares Russell 2000 ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "SCHD": "Schwab U.S. Dividend Equity ETF",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
}

LOGO_URLS = {
    "NVDA": "https://cdn.simpleicons.org/nvidia",
    "AAPL": "https://cdn.simpleicons.org/apple/000000",
    "MSFT": "https://cdn.simpleicons.org/microsoft",
    "AMD": "https://cdn.simpleicons.org/amd",
    "META": "https://cdn.simpleicons.org/meta",
    "TSLA": "https://cdn.simpleicons.org/tesla",
    "GOOGL": "https://cdn.simpleicons.org/google",
    "GOOG": "https://cdn.simpleicons.org/google",
    "AMZN": "https://cdn.simpleicons.org/amazon",
    "NFLX": "https://cdn.simpleicons.org/netflix",
    "AVGO": "https://cdn.simpleicons.org/broadcom",
    "ORCL": "https://cdn.simpleicons.org/oracle",
    "INTC": "https://cdn.simpleicons.org/intel",
    "MU": "https://logo.clearbit.com/micron.com",
    "DELL": "https://cdn.simpleicons.org/dell",
    "PLTR": "https://logo.clearbit.com/palantir.com",
    "SPOT": "https://cdn.simpleicons.org/spotify",
    "PYPL": "https://cdn.simpleicons.org/paypal",
    "CRM": "https://cdn.simpleicons.org/salesforce",
    "SHOP": "https://cdn.simpleicons.org/shopify",
    "UBER": "https://cdn.simpleicons.org/uber",
    "DIS": "https://cdn.simpleicons.org/disney",
    "V": "https://cdn.simpleicons.org/visa",
    "MA": "https://cdn.simpleicons.org/mastercard",
    "WMT": "https://cdn.simpleicons.org/walmart",
    "COST": "https://cdn.simpleicons.org/costco",
    "XOM": "https://cdn.simpleicons.org/exxonmobil",
    "VOO": "https://logo.clearbit.com/vanguard.com",
    "VTI": "https://logo.clearbit.com/vanguard.com",
    "VT": "https://logo.clearbit.com/vanguard.com",
    "DIA": "https://logo.clearbit.com/ssga.com",
    "IWM": "https://logo.clearbit.com/ishares.com",
    "EFA": "https://logo.clearbit.com/ishares.com",
    "EEM": "https://logo.clearbit.com/ishares.com",
    "SCHD": "https://logo.clearbit.com/schwabassetmanagement.com",
    "BTC-USD": "https://cdn.simpleicons.org/bitcoin",
    "ETH-USD": "https://cdn.simpleicons.org/ethereum",
    "SOL-USD": "https://cdn.simpleicons.org/solana",
    "XRP-USD": "https://cdn.simpleicons.org/ripple",
    "ADA-USD": "https://cdn.simpleicons.org/cardano",
    "DOGE-USD": "https://cdn.simpleicons.org/dogecoin",
    "BNB-USD": "https://cdn.simpleicons.org/binance",
}

LOGO_DOMAINS = {
    "NVDA": "nvidia.com",
    "AAPL": "apple.com",
    "MSFT": "microsoft.com",
    "AMD": "amd.com",
    "META": "meta.com",
    "TSLA": "tesla.com",
    "GOOGL": "google.com",
    "GOOG": "google.com",
    "AMZN": "amazon.com",
    "NFLX": "netflix.com",
    "AVGO": "broadcom.com",
    "ORCL": "oracle.com",
    "INTC": "intel.com",
    "MU": "micron.com",
    "DELL": "dell.com",
    "PLTR": "palantir.com",
    "SPOT": "spotify.com",
    "PYPL": "paypal.com",
    "CRM": "salesforce.com",
    "SHOP": "shopify.com",
    "UBER": "uber.com",
    "DIS": "disney.com",
    "JPM": "jpmorganchase.com",
    "V": "visa.com",
    "MA": "mastercard.com",
    "WMT": "walmart.com",
    "COST": "costco.com",
    "XOM": "exxonmobil.com",
    "SPY": "ssga.com",
    "QQQ": "invesco.com",
    "VOO": "vanguard.com",
    "VTI": "vanguard.com",
    "VT": "vanguard.com",
    "DIA": "ssga.com",
    "IWM": "ishares.com",
    "EFA": "ishares.com",
    "EEM": "ishares.com",
    "SCHD": "schwabassetmanagement.com",
    "BTC-USD": "bitcoin.org",
    "ETH-USD": "ethereum.org",
    "SOL-USD": "solana.com",
    "BRK-B": "berkshirehathaway.com",
    "LLY": "lilly.com",
    "UNH": "unitedhealthgroup.com",
    "HD": "homedepot.com",
    "PG": "pg.com",
    "JNJ": "jnj.com",
    "ABBV": "abbvie.com",
    "BAC": "bankofamerica.com",
    "KO": "coca-cola.com",
    "PEP": "pepsico.com",
    "ADBE": "adobe.com",
    "CSCO": "cisco.com",
    "TMO": "thermofisher.com",
    "PFE": "pfizer.com",
    "ABT": "abbott.com",
    "MCD": "mcdonalds.com",
    "NKE": "nike.com",
    "IBM": "ibm.com",
    "GE": "ge.com",
    "BA": "boeing.com",
    "CAT": "cat.com",
    "GS": "goldmansachs.com",
    "AXP": "americanexpress.com",
    "BLK": "blackrock.com",
    "NOW": "servicenow.com",
    "SNOW": "snowflake.com",
    "PANW": "paloaltonetworks.com",
    "CRWD": "crowdstrike.com",
    "SQ": "block.xyz",
    "COIN": "coinbase.com",
    "RBLX": "roblox.com",
    "ABNB": "airbnb.com",
    "ZM": "zoom.us",
    "MRNA": "modernatx.com",
    "NVO": "novonordisk.com",
    "ASML": "asml.com",
    "SAP": "sap.com",
    "SIE.DE": "siemens.com",
    "VOW3.DE": "volkswagen-group.com",
    "BMW.DE": "bmwgroup.com",
    "MBG.DE": "mercedes-benz.com",
    "ALV.DE": "allianz.com",
    "BAS.DE": "basf.com",
    "BAYN.DE": "bayer.com",
    "DTE.DE": "telekom.com",
    "AIR.PA": "airbus.com",
    "MC.PA": "lvmh.com",
    "OR.PA": "loreal.com",
    "NESN.SW": "nestle.com",
    "NOVN.SW": "novartis.com",
    "ROG.SW": "roche.com",
    "SHEL.L": "shell.com",
    "AZN.L": "astrazeneca.com",
    "HSBA.L": "hsbc.com",
    "BP.L": "bp.com",
    "ULVR.L": "unilever.com",
    "BABA": "alibabagroup.com",
    "TCEHY": "tencent.com",
    "TSM": "tsmc.com",
    "TM": "toyota-global.com",
    "SONY": "sony.com",
    "SHOP.TO": "shopify.com",
    "RY.TO": "rbc.com",
    "TD.TO": "td.com",
    "BHP.AX": "bhp.com",
    "CBA.AX": "commbank.com.au",
}


LOGO_NAME_DOMAINS = {
    "micron": "micron.com",
    "nvidia": "nvidia.com",
    "apple": "apple.com",
    "microsoft": "microsoft.com",
    "tesla": "tesla.com",
    "alphabet": "google.com",
    "google": "google.com",
    "amazon": "amazon.com",
    "meta": "meta.com",
    "advanced micro devices": "amd.com",
    "broadcom": "broadcom.com",
    "oracle": "oracle.com",
    "intel": "intel.com",
    "dell": "dell.com",
    "palantir": "palantir.com",
    "spotify": "spotify.com",
    "paypal": "paypal.com",
    "salesforce": "salesforce.com",
    "shopify": "shopify.com",
    "uber": "uber.com",
    "walt disney": "disney.com",
    "disney": "disney.com",
    "jpmorgan": "jpmorganchase.com",
    "visa": "visa.com",
    "mastercard": "mastercard.com",
    "walmart": "walmart.com",
    "costco": "costco.com",
    "exxon": "exxonmobil.com",
    "berkshire": "berkshirehathaway.com",
    "eli lilly": "lilly.com",
    "unitedhealth": "unitedhealthgroup.com",
    "home depot": "homedepot.com",
    "procter": "pg.com",
    "johnson": "jnj.com",
    "abbvie": "abbvie.com",
    "bank of america": "bankofamerica.com",
    "coca": "coca-cola.com",
    "pepsico": "pepsico.com",
    "adobe": "adobe.com",
    "cisco": "cisco.com",
    "thermo fisher": "thermofisher.com",
    "pfizer": "pfizer.com",
    "abbott": "abbott.com",
    "mcdonald": "mcdonalds.com",
    "nike": "nike.com",
    "blackrock": "blackrock.com",
    "servicenow": "servicenow.com",
    "snowflake": "snowflake.com",
    "palo alto": "paloaltonetworks.com",
    "crowdstrike": "crowdstrike.com",
    "coinbase": "coinbase.com",
    "airbnb": "airbnb.com",
    "roblox": "roblox.com",
    "zoom": "zoom.us",
    "moderna": "modernatx.com",
    "novo nordisk": "novonordisk.com",
    "asml": "asml.com",
    "siemens": "siemens.com",
    "volkswagen": "volkswagen-group.com",
    "mercedes": "mercedes-benz.com",
    "allianz": "allianz.com",
    "basf": "basf.com",
    "bayer": "bayer.com",
    "airbus": "airbus.com",
    "lvmh": "lvmh.com",
    "loreal": "loreal.com",
    "nestle": "nestle.com",
    "novartis": "novartis.com",
    "roche": "roche.com",
    "shell": "shell.com",
    "astrazeneca": "astrazeneca.com",
    "hsbc": "hsbc.com",
    "unilever": "unilever.com",
    "alibaba": "alibabagroup.com",
    "tencent": "tencent.com",
    "taiwan semiconductor": "tsmc.com",
    "toyota": "toyota-global.com",
    "sony": "sony.com",
    "spdr": "ssga.com",
    "invesco": "invesco.com",
    "vanguard": "vanguard.com",
    "ishares": "ishares.com",
    "schwab": "schwabassetmanagement.com",
}


ETF_DOMAIN_HINTS = {
    "SPDR": "ssga.com",
    "ISHARES": "ishares.com",
    "VANGUARD": "vanguard.com",
    "INVESCO": "invesco.com",
    "SCHWAB": "schwabassetmanagement.com",
    "FIDELITY": "fidelity.com",
    "ARK": "ark-funds.com",
    "GLOBAL X": "globalxetfs.com",
    "WISDOMTREE": "wisdomtree.com",
}


def _base_logo_symbol(symbol: str) -> str:
    clean = (symbol or "").strip().upper()
    crypto_aliases = {
        "BTCUSD": "BTC-USD",
        "BTCUSDT": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "ETHUSDT": "ETH-USD",
        "SOLUSD": "SOL-USD",
        "SOLUSDT": "SOL-USD",
        "XRPUSD": "XRP-USD",
        "XRPUSDT": "XRP-USD",
        "ADAUSD": "ADA-USD",
        "ADAUSDT": "ADA-USD",
        "DOGEUSD": "DOGE-USD",
        "DOGEUSDT": "DOGE-USD",
        "BNBUSD": "BNB-USD",
        "BNBUSDT": "BNB-USD",
    }
    if clean in crypto_aliases:
        return crypto_aliases[clean]
    if clean.endswith("-USD"):
        return clean
    for suffix in [".DE", ".F", ".PA", ".AS", ".BR", ".MI", ".MC", ".L", ".SW", ".TO", ".AX", ".HK", ".T", ".MX", ".NE"]:
        if clean.endswith(suffix):
            return clean[: -len(suffix)]
    return clean


def _domain_from_name(name: str | None) -> str | None:
    lowered = (name or "").lower()
    if not lowered:
        return None
    for hint, domain in LOGO_NAME_DOMAINS.items():
        if hint in lowered:
            return domain
    upper = lowered.upper()
    for hint, domain in ETF_DOMAIN_HINTS.items():
        if hint in upper:
            return domain
    return None


def get_logo_domain(mapped_symbol: str, name: str | None = None) -> str | None:
    symbol = (mapped_symbol or "").upper()
    base = _base_logo_symbol(symbol)
    return LOGO_DOMAINS.get(symbol) or LOGO_DOMAINS.get(base) or _domain_from_name(name)


def get_logo_url(mapped_symbol: str, name: str | None = None) -> str | None:
    symbol = (mapped_symbol or "").upper()
    base = _base_logo_symbol(symbol)
    if symbol in LOGO_URLS:
        return LOGO_URLS[symbol]
    if base in LOGO_URLS:
        return LOGO_URLS[base]
    domain = get_logo_domain(symbol, name)
    if domain:
        return f"https://logo.clearbit.com/{domain}"
    return None


def with_logo(item: dict) -> dict:
    symbol = str(item.get("symbol") or "").upper()
    mapped_symbol = map_symbol(symbol).upper() if symbol else symbol
    name = str(item.get("name") or item.get("instrument_name") or "")
    enriched = dict(item)
    enriched["logo_url"] = item.get("logo_url") or get_logo_url(mapped_symbol, name)
    enriched["logo_domain"] = item.get("logo_domain") or get_logo_domain(mapped_symbol, name)
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
    clean_symbol = (mapped_symbol or "").strip().upper()
    base_symbol = _base_logo_symbol(clean_symbol)
    cache_key = f"profile:name:{clean_symbol}"
    cached = _cache_get(cache_key, CACHE_TTL_SECONDS["profile"])
    if cached is not None:
        return cached
    if clean_symbol in SYMBOL_PROFILES:
        return _cache_set(cache_key, SYMBOL_PROFILES[clean_symbol])
    if base_symbol in SYMBOL_PROFILES:
        return _cache_set(cache_key, SYMBOL_PROFILES[base_symbol])
    try:
        payload = _twelve_get("quote", {"symbol": _twelve_symbol(clean_symbol)})
        if isinstance(payload, dict):
            name = _clean_asset_name(payload.get("name") or payload.get("instrument_name") or "", clean_symbol)
            if name and name.upper() != clean_symbol:
                return _cache_set(cache_key, name)
    except Exception:
        pass
    try:
        ticker = yf.Ticker(clean_symbol)
        info = ticker.info
        return _cache_set(cache_key, _clean_asset_name(info.get("longName") or info.get("shortName") or clean_symbol, clean_symbol))
    except Exception:
        return _cache_set(cache_key, clean_symbol)


def get_quote_currency(mapped_symbol: str) -> str:
    clean_symbol = (mapped_symbol or "").strip().upper()
    cache_key = f"profile:currency:{clean_symbol}"
    cached = _cache_get(cache_key, CACHE_TTL_SECONDS["profile"])
    if cached is not None:
        return cached
    try:
        payload = _twelve_get("quote", {"symbol": _twelve_symbol(clean_symbol)})
        if isinstance(payload, dict):
            currency = str(payload.get("currency") or "").upper()
            if currency:
                return _cache_set(cache_key, currency)
    except Exception:
        pass
    try:
        currency = yf.Ticker(clean_symbol).fast_info.get("currency")
        if currency:
            return _cache_set(cache_key, str(currency).upper())
    except Exception:
        pass
    if clean_symbol.endswith(".DE") or clean_symbol.endswith(".F"):
        return _cache_set(cache_key, "EUR")
    if clean_symbol.endswith("-USD"):
        return _cache_set(cache_key, "USD")
    return _cache_set(cache_key, "USD")


def _search_currency(item: dict) -> str:
    symbol = str(item.get("symbol") or "").upper()
    exchange = str(item.get("exchange") or "").upper()
    currency = str(item.get("currency") or item.get("quote_currency") or "").upper()
    if currency:
        return currency
    if symbol.endswith(".DE") or symbol.endswith(".F") or "XETRA" in exchange or "FRANKFURT" in exchange or "GERMANY" in exchange:
        return "EUR"
    if symbol.endswith("-USD") or "NASDAQ" in exchange or "NYSE" in exchange:
        return "USD"
    return ""


def _search_market_rank(item: dict) -> int:
    symbol = str(item.get("symbol") or "").upper()
    exchange = str(item.get("exchange") or "").upper()
    currency = _search_currency(item)
    if "XETRA" in exchange or symbol.endswith(".DE"):
        return 0
    if "FRANKFURT" in exchange or "GERMANY" in exchange or symbol.endswith(".F"):
        return 1
    if currency == "EUR":
        return 2
    if "NASDAQ" in exchange or "NYSE" in exchange or currency == "USD":
        return 3
    return 4


def _asset_type_rank(item: dict) -> int:
    raw_type = str(item.get("type") or item.get("instrument_type") or "").upper()
    symbol = str(item.get("symbol") or "").upper()
    if symbol.endswith("-USD") or "/" in symbol:
        return 0
    if any(token in raw_type for token in ["COMMON STOCK", "EQUITY", "STOCK", "SHARE"]):
        return 0
    if any(token in raw_type for token in ["ETF", "ETC", "FUND"]):
        return 1
    if any(token in raw_type for token in ["INDEX", "FOREX", "CURRENCY", "CRYPTO", "DIGITAL"]):
        return 2
    if any(token in raw_type for token in ["COMMODITY", "FUTURE"]):
        return 3
    if any(token in raw_type for token in ["WARRANT", "CERTIFICATE", "OPTION", "TURBO", "KNOCK", "BOND", "NOTE", "RIGHT", "DEPOSITARY RECEIPT"]):
        return 99
    return 5


def _is_search_result_allowed(item: dict, query: str) -> bool:
    raw = query.strip()
    symbol = str(item.get("symbol") or "").strip()
    if not symbol:
        return False
    type_rank = _asset_type_rank(item)
    if type_rank < 99:
        return True
    # If the user types the exact warrant/certificate ticker, allow it.
    return bool(raw) and _compact(raw) == _compact(symbol)


def _company_key(item: dict) -> str:
    raw = str(item.get("name") or item.get("symbol") or "").upper()
    cleanup_tokens = [
        "INCORPORATED", "CORPORATION", "COMPANY", "HOLDINGS", "LIMITED",
        "CLASS A", "CLASS B", "REGISTERED SHARES", "REG SHS", "SHARES",
        "COMMON STOCK", "ORDINARY", "DR", "ADR", "CDR", "ETF", "ETC",
        "INC", "CORP", "LTD", "PLC", "AG", "SA", "SE", "NV", "R",
    ]
    for token in cleanup_tokens:
        raw = raw.replace(token, " ")
    return "".join(ch for ch in raw if ch.isalnum()) or str(item.get("symbol") or "").upper()


def _clean_asset_name(name: str | None, symbol: str = "") -> str:
    raw = " ".join(str(name or symbol or "").replace("\t", " ").split())
    if not raw:
        return str(symbol or "").upper()
    noisy_suffixes = [
        " R", " DR", " ADR", " CDR", " COMMON STOCK", " ORDINARY SHARES",
        " REGISTERED SHARES", " REG SHS",
    ]
    upper = raw.upper()
    for suffix in noisy_suffixes:
        if upper.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
            upper = raw.upper()
    profile_name = SYMBOL_PROFILES.get(_base_logo_symbol(symbol))
    if profile_name and (upper == symbol.upper() or len(raw) <= 6):
        return profile_name
    return raw


def _search_tokens(value: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return [token for token in cleaned.split() if len(token) >= 2]


def _compact(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _relevance_rank(item: dict, query: str) -> int:
    raw = query.strip()
    if not raw:
        return 0
    q_compact = _compact(raw)
    symbol = str(item.get("symbol") or "").lower()
    symbol_compact = _compact(symbol)
    name = str(item.get("name") or "")
    name_compact = _compact(name)
    q_tokens = _search_tokens(raw)
    name_tokens = _search_tokens(name)

    if symbol == raw.lower() or symbol_compact == q_compact:
        return 0
    if name_compact == q_compact:
        return 1
    if symbol.startswith(raw.lower()) or symbol_compact.startswith(q_compact):
        return 2

    token_matches = sum(
        1 for token in q_tokens
        if any(name_token == token or name_token.startswith(token) for name_token in name_tokens)
    )
    if len(q_tokens) >= 2 and token_matches < len(q_tokens):
        return 99
    if q_tokens and token_matches == len(q_tokens):
        return 3
    if len(q_tokens) >= 2 and token_matches >= math.ceil(len(q_tokens) * 0.75):
        return 4
    if len(q_compact) >= 3 and q_compact in name_compact:
        return 5
    if len(q_tokens) == 1 and len(q_tokens[0]) >= 3 and token_matches == 1:
        return 6
    return 99


def _rank_and_dedupe_results(items: list[dict], limit: int, query: str = "") -> list[dict]:
    by_company: dict[str, dict] = {}
    for item in items:
        if not item.get("symbol"):
            continue
        if not _is_search_result_allowed(item, query):
            continue
        cleaned = {**item, "currency": _search_currency(item)}
        cleaned["name"] = _clean_asset_name(cleaned.get("name"), str(cleaned.get("symbol") or ""))
        enriched = with_logo(cleaned)
        if _relevance_rank(enriched, query) >= 99:
            continue
        key = _company_key(enriched)
        current = by_company.get(key)
        if current is None or (_relevance_rank(enriched, query), _asset_type_rank(enriched), _search_market_rank(enriched)) < (_relevance_rank(current, query), _asset_type_rank(current), _search_market_rank(current)):
            by_company[key] = enriched
    return sorted(
        by_company.values(),
        key=lambda item: (_relevance_rank(item, query), _asset_type_rank(item), _search_market_rank(item), str(item.get("symbol") or "")),
    )[:limit]


def _search_symbols_yahoo(query: str = "", limit: int = 12) -> dict:
    clean = query.strip()
    max_results = max(1, min(limit, 20))

    if not clean:
        return {"query": clean, "results": [with_logo(item) for item in POPULAR_SYMBOLS[:max_results]], "source": "popular"}

    fallback = [
        with_logo(item)
        for item in POPULAR_SYMBOLS
        if clean.upper() in item["symbol"].upper() or clean.lower() in item["name"].lower()
    ]

    try:
        search = yf.Search(clean, max_results=max_results * 3)
        results = []
        seen: set[str] = set()
        for quote in getattr(search, "quotes", []) or []:
            symbol = str(quote.get("symbol") or "").strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append(
                with_logo(
                    {
                        "symbol": symbol,
                        "name": quote.get("shortname") or quote.get("longname") or symbol,
                        "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
                        "currency": quote.get("currency") or "",
                        "type": quote.get("typeDisp") or quote.get("quoteType") or "",
                    }
                )
            )
        ranked = _rank_and_dedupe_results(results + fallback, max_results, clean)
        return {"query": clean, "results": ranked, "source": "yahoo" if results else "local"}
    except Exception as exc:
        return {"query": clean, "results": _rank_and_dedupe_results(fallback, max_results, clean), "source": "fallback", "error": str(exc)}


def _twelve_search_results(clean: str, max_results: int) -> list[dict]:
    query_attempts = [clean]
    tokens = _search_tokens(clean)
    if len(tokens) > 1:
        query_attempts.extend(tokens)
    compact = "".join(ch for ch in clean.upper() if ch.isalnum())
    mapped = COMMON_SYMBOL_MAP.get(compact)
    if mapped:
        query_attempts.insert(0, mapped)
    results = []
    seen_payloads: set[str] = set()
    for attempt in query_attempts:
        attempt_key = attempt.lower()
        if attempt_key in seen_payloads:
            continue
        seen_payloads.add(attempt_key)
        payload = _twelve_get("symbol_search", {"symbol": attempt, "outputsize": max_results * 4})
        if not payload:
            continue
        raw_results = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(raw_results, list):
            continue
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").strip()
            if not symbol:
                continue
            name = _clean_asset_name(item.get("instrument_name") or item.get("name") or symbol, symbol)
            exchange = item.get("exchange") or item.get("mic_code") or item.get("exchange_timezone") or ""
            currency = item.get("currency") or ""
            asset_type = item.get("instrument_type") or item.get("type") or ""
            results.append(
                with_logo(
                    {
                        "symbol": symbol,
                        "name": name,
                        "exchange": exchange,
                        "currency": currency,
                        "type": asset_type,
                        "source": "twelve_data",
                    }
                )
            )
    return results


def search_symbols(query: str = "", limit: int = 12) -> dict:
    clean = query.strip()
    max_results = max(1, min(limit, 20))
    cache_key = f"symbols:{clean.lower()}:{max_results}"
    cached = _cache_get(cache_key, CACHE_TTL_SECONDS["symbols"])
    if cached is not None:
        return cached
    if not clean:
        return _cache_set(cache_key, {"query": clean, "results": [with_logo(item) for item in POPULAR_SYMBOLS[:max_results]], "source": "popular", "cache_ttl_seconds": CACHE_TTL_SECONDS["symbols"]})

    fallback = [
        with_logo(item)
        for item in POPULAR_SYMBOLS
        if clean.upper() in item["symbol"].upper() or clean.lower() in item["name"].lower()
    ]

    try:
        twelve_results = _twelve_search_results(clean, max_results)
        if twelve_results:
            ranked = _rank_and_dedupe_results(twelve_results + fallback, max_results, clean)
            if ranked:
                return _cache_set(cache_key, {"query": clean, "results": ranked, "source": "twelve_data", "fallback_used": False, "cache_ttl_seconds": CACHE_TTL_SECONDS["symbols"]})
            twelve_error = "Twelve Data returned only derivative or low-relevance results."
        else:
            twelve_error = "Twelve Data returned no usable symbol results."
    except Exception as exc:
        twelve_error = str(exc)

    yahoo = _search_symbols_yahoo(query, limit)
    yahoo["fallback_used"] = True
    yahoo["cache_ttl_seconds"] = CACHE_TTL_SECONDS["symbols"]
    if twelve_error:
        yahoo["twelve_data_error"] = twelve_error
    return _cache_set(cache_key, yahoo)

def get_fx_rate(base: str = "USD", quote: str = "EUR") -> dict:
    base_clean = base.strip().upper()
    quote_clean = quote.strip().upper()
    cache_key = f"fx:{base_clean}:{quote_clean}"
    cached = _cache_get(cache_key, 1800)
    if cached is not None:
        return cached
    if base_clean == quote_clean:
        return _cache_set(cache_key, {"base": base_clean, "quote": quote_clean, "rate": 1.0})

    pair = f"{base_clean}{quote_clean}=X"
    data = yf.download(pair, period="5d", interval="1d", progress=False, threads=False)

    if data.empty and base_clean == "USD" and quote_clean == "EUR":
        inverse = yf.download("EURUSD=X", period="5d", interval="1d", progress=False, threads=False)
        inverse = normalize_yfinance_columns(inverse)
        latest = _safe_float(inverse["Close"].dropna().iloc[-1]) if not inverse.empty else None
        if latest:
            return _cache_set(cache_key, {"base": base_clean, "quote": quote_clean, "rate": 1 / latest})

    if data.empty and base_clean == "EUR" and quote_clean == "USD":
        inverse = yf.download("EURUSD=X", period="5d", interval="1d", progress=False, threads=False)
        inverse = normalize_yfinance_columns(inverse)
        latest = _safe_float(inverse["Close"].dropna().iloc[-1]) if not inverse.empty else None
        if latest:
            return _cache_set(cache_key, {"base": base_clean, "quote": quote_clean, "rate": latest})

    if data.empty:
        return {"base": base_clean, "quote": quote_clean, "rate": None, "error": "FX rate unavailable"}

    data = normalize_yfinance_columns(data)
    latest = _safe_float(data["Close"].dropna().iloc[-1])
    return _cache_set(cache_key, {"base": base_clean, "quote": quote_clean, "rate": latest})


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


def _get_chart_data_yahoo(symbol: str, range_key: str = "6M") -> dict:
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
        asset_name = get_asset_name(mapped_symbol)
        return {
            "symbol": symbol,
            "mapped_symbol": mapped_symbol,
            "asset_name": asset_name,
            "logo_url": get_logo_url(mapped_symbol, asset_name),
            "currency": quote_currency,
            "range": clean_range,
            "interval": interval,
            "candles": [],
            "notes": [f"No chart data returned for {mapped_symbol} on {clean_range}. The symbol may be unsupported by the active provider or outside available history."],
            "error": "chart_data_unavailable",
            "user_message": f"Chart data unavailable for {mapped_symbol}. Try another exchange listing or timeframe.",
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
        "asset_name": get_asset_name(mapped_symbol),
        "logo_url": get_logo_url(mapped_symbol, get_asset_name(mapped_symbol)),
        "currency": quote_currency,
        "range": clean_range,
        "interval": interval,
        "candles": candles,
        "notes": [],
        "source": "yahoo",
    }


def _get_technicals_yahoo(symbol: str, timeframe: str = "1d") -> TechnicalSnapshot:
    mapped_symbol = map_symbol(symbol)
    raw_timeframe = (timeframe or "1d").strip()
    range_key = raw_timeframe.upper()
    uses_chart_range = range_key in CHART_RANGE_MAP and raw_timeframe != raw_timeframe.lower()
    if uses_chart_range:
        period, interval = CHART_RANGE_MAP[range_key]
    else:
        interval = INTERVAL_MAP.get(raw_timeframe, "1d")
        period = PERIOD_MAP.get(raw_timeframe, "2y")
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
            logo_url=get_logo_url(mapped_symbol, asset_name),
            quote_currency=quote_currency,
            trend="unknown",
            notes=[f"No technical data returned for {mapped_symbol} on {timeframe}. The symbol may be unsupported by the active provider or outside available history."],
        )

    data = normalize_yfinance_columns(data)

    data = add_indicator_columns(data)

    latest = data.iloc[-1]
    previous = data.iloc[-2] if len(data) >= 2 else latest
    range_start = data.iloc[0] if uses_chart_range else previous

    last_price = _safe_float(latest.get("Close"))
    previous_close = _safe_float(previous.get("Close"))
    performance_start_close = _safe_float(range_start.get("Close"))
    change_percent = None
    change_absolute = None
    if last_price is not None and performance_start_close not in (None, 0):
        change_absolute = last_price - performance_start_close
        change_percent = ((last_price - performance_start_close) / performance_start_close) * 100

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
        timeframe=range_key if uses_chart_range else raw_timeframe,
        asset_name=asset_name,
        logo_url=get_logo_url(mapped_symbol, asset_name),
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


def _twelve_api_key() -> str | None:
    key = (get_settings().twelve_data_api_key or "").strip()
    return key or None


def _twelve_get(endpoint: str, params: dict) -> dict | None:
    key = _twelve_api_key()
    if not key:
        return None
    request_params = dict(params)
    request_params["apikey"] = key
    url = f"{TWELVE_DATA_BASE_URL}/{endpoint}?{urllib.parse.urlencode(request_params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "SignalDeskAI/0.10.2"})
    try:
        with urllib.request.urlopen(request, timeout=14) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Twelve Data request failed: {exc}") from exc
    if isinstance(payload, dict) and (payload.get("status") == "error" or payload.get("code")):
        message = payload.get("message") or payload.get("error") or "Twelve Data error"
        raise RuntimeError(str(message))
    return payload


def _twelve_symbol(symbol: str) -> str:
    mapped = map_symbol(symbol).strip().upper()
    if mapped.endswith("-USD"):
        return f"{mapped[:-4]}/USD"
    if mapped.endswith("=X") and len(mapped) >= 7:
        return f"{mapped[0:3]}/{mapped[3:6]}"
    return mapped


def _twelve_quote_currency(meta: dict, symbol: str) -> str:
    currency = str(meta.get("currency") or "").strip().upper()
    if currency:
        return currency
    td_symbol = _twelve_symbol(symbol)
    if "/" in td_symbol:
        return td_symbol.split("/", 1)[1].upper()
    return "USD"


def _twelve_asset_name(meta: dict, mapped_symbol: str) -> str:
    return _clean_asset_name(meta.get("instrument_name") or meta.get("name") or meta.get("symbol") or SYMBOL_PROFILES.get(mapped_symbol.upper()) or mapped_symbol, mapped_symbol)


def _twelve_dataframe(payload: dict) -> pd.DataFrame:
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        return pd.DataFrame()
    rows = []
    index = []
    for item in values:
        if not isinstance(item, dict):
            continue
        timestamp = pd.to_datetime(item.get("datetime"), utc=True, errors="coerce")
        close = _safe_float(item.get("close"))
        if pd.isna(timestamp) or close is None:
            continue
        index.append(timestamp)
        rows.append(
            {
                "Open": _safe_float(item.get("open")) or close,
                "High": _safe_float(item.get("high")) or close,
                "Low": _safe_float(item.get("low")) or close,
                "Close": close,
                "Volume": _safe_float(item.get("volume")),
            }
        )
    if not rows:
        return pd.DataFrame()
    data = pd.DataFrame(rows, index=pd.DatetimeIndex(index))
    return data.sort_index()


def _twelve_time_series(symbol: str, interval: str, outputsize: int) -> tuple[pd.DataFrame, dict]:
    td_symbol = _twelve_symbol(symbol)
    payload = _twelve_get(
        "time_series",
        {
            "symbol": td_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "order": "ASC",
            "format": "JSON",
        },
    )
    if not payload:
        return pd.DataFrame(), {}
    return _twelve_dataframe(payload), payload.get("meta") or {}


def _technical_snapshot_from_data(
    symbol: str,
    mapped_symbol: str,
    timeframe: str,
    data: pd.DataFrame,
    quote_currency: str,
    asset_name: str,
    uses_chart_range: bool,
    notes: list[str],
) -> TechnicalSnapshot | None:
    if data.empty:
        return None
    data = normalize_yfinance_columns(data)
    data = add_indicator_columns(data)
    latest = data.iloc[-1]
    previous = data.iloc[-2] if len(data) >= 2 else latest
    range_start = data.iloc[0] if uses_chart_range else previous
    last_price = _safe_float(latest.get("Close"))
    previous_close = _safe_float(previous.get("Close"))
    performance_start_close = _safe_float(range_start.get("Close"))
    change_percent = None
    change_absolute = None
    if last_price is not None and performance_start_close not in (None, 0):
        change_absolute = last_price - performance_start_close
        change_percent = ((last_price - performance_start_close) / performance_start_close) * 100
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
        logo_url=get_logo_url(mapped_symbol, asset_name),
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


def _chart_response_from_data(
    symbol: str,
    mapped_symbol: str,
    range_key: str,
    interval: str,
    quote_currency: str,
    data: pd.DataFrame,
    source: str,
) -> dict | None:
    if data.empty:
        return None
    asset_name = get_asset_name(mapped_symbol)
    data = normalize_yfinance_columns(data)
    data = add_indicator_columns(data).tail(900)
    candles = []
    for index, row in data.iterrows():
        timestamp = index.isoformat()
        candles.append(
            {
                "time": timestamp,
                "timestamp": timestamp,
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
        "asset_name": asset_name,
        "logo_url": get_logo_url(mapped_symbol, asset_name),
        "currency": quote_currency,
        "range": range_key,
        "interval": interval,
        "candles": candles,
        "notes": [f"Data source: {source}."],
        "source": source,
        "fallback_used": source != "twelve_data",
        "provider": {
            "primary": "twelve_data",
            "actual": source,
            "fallback_used": source != "twelve_data",
        },
    }


def get_chart_data(symbol: str, range_key: str = "6M") -> dict:
    clean_range = range_key.strip().upper()
    mapped_symbol = map_symbol(symbol)
    cache_key = f"chart:{mapped_symbol.upper()}:{clean_range}"
    chart_ttl = CACHE_TTL_SECONDS["chart_intraday"] if clean_range in {"1D", "1W", "7D", "1M"} else CACHE_TTL_SECONDS["chart_daily"]
    cached = _cache_get(cache_key, chart_ttl)
    if cached is not None:
        return cached
    td_interval, outputsize = TWELVE_CHART_RANGE_MAP.get(clean_range, TWELVE_CHART_RANGE_MAP["6M"])
    try:
        td_data, meta = _twelve_time_series(mapped_symbol, td_interval, outputsize)
        response = _chart_response_from_data(
            symbol,
            mapped_symbol,
            clean_range,
            td_interval,
            _twelve_quote_currency(meta, mapped_symbol),
            td_data,
            "twelve_data",
        )
        if response:
            response["cache_ttl_seconds"] = chart_ttl
            return _cache_set(cache_key, response)
    except Exception as exc:
        fallback = _get_chart_data_yahoo(symbol, range_key)
        fallback.setdefault("notes", []).append(f"Twelve Data unavailable, using Yahoo fallback: {exc}")
        fallback["source"] = "yahoo_fallback"
        fallback["fallback_used"] = True
        fallback["cache_ttl_seconds"] = chart_ttl
        if not fallback.get("candles"):
            fallback["user_message"] = f"No chart data available for {mapped_symbol} on {clean_range}. Twelve Data failed and Yahoo fallback returned no candles."
        fallback["provider"] = {
            "primary": "twelve_data",
            "actual": "yahoo",
            "fallback_used": True,
            "twelve_data_error": str(exc),
        }
        return _cache_set(cache_key, fallback)
    fallback = _get_chart_data_yahoo(symbol, range_key)
    fallback["source"] = "yahoo_fallback"
    fallback["fallback_used"] = True
    fallback["cache_ttl_seconds"] = chart_ttl
    fallback.setdefault("notes", []).append("Twelve Data unavailable or not configured, using Yahoo fallback.")
    if not fallback.get("candles"):
        fallback["user_message"] = f"No chart data available for {mapped_symbol} on {clean_range}. Check the symbol, exchange suffix, or provider coverage."
    fallback["provider"] = {
        "primary": "twelve_data",
        "actual": "yahoo",
        "fallback_used": True,
        "twelve_data_error": "Twelve Data returned no usable candles or is not configured.",
    }
    return _cache_set(cache_key, fallback)


def get_technicals(symbol: str, timeframe: str = "1d") -> TechnicalSnapshot:
    mapped_symbol = map_symbol(symbol)
    raw_timeframe = (timeframe or "1d").strip()
    cache_key = f"technicals:{mapped_symbol.upper()}:{raw_timeframe}"
    cached = _cache_get(cache_key, CACHE_TTL_SECONDS["technicals"])
    if cached is not None:
        return cached
    range_key = raw_timeframe.upper()
    uses_chart_range = range_key in CHART_RANGE_MAP and raw_timeframe != raw_timeframe.lower()
    if uses_chart_range:
        td_interval, outputsize = TWELVE_CHART_RANGE_MAP.get(range_key, TWELVE_CHART_RANGE_MAP["6M"])
        response_timeframe = range_key
    else:
        td_interval, outputsize = TWELVE_TECHNICAL_INTERVAL_MAP.get(raw_timeframe, TWELVE_TECHNICAL_INTERVAL_MAP["1d"])
        response_timeframe = raw_timeframe
    try:
        td_data, meta = _twelve_time_series(mapped_symbol, td_interval, outputsize)
        snapshot = _technical_snapshot_from_data(
            symbol,
            mapped_symbol,
            response_timeframe,
            td_data,
            _twelve_quote_currency(meta, mapped_symbol),
            _twelve_asset_name(meta, mapped_symbol),
            uses_chart_range,
            ["Data source: Twelve Data."],
        )
        if snapshot:
            return _cache_set(cache_key, snapshot)
    except Exception as exc:
        snapshot = _get_technicals_yahoo(symbol, timeframe)
        snapshot.notes.append(f"Twelve Data unavailable, using Yahoo fallback: {exc}")
        return _cache_set(cache_key, snapshot)
    snapshot = _get_technicals_yahoo(symbol, timeframe)
    snapshot.notes.append("Twelve Data unavailable or not configured, using Yahoo fallback.")
    return _cache_set(cache_key, snapshot)
