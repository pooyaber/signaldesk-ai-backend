from __future__ import annotations

import json
import math
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
