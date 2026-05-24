"""Simple CLI scanner.

Usage:
    python -m app.scripts.scan_watchlist NVDA MSFT AAPL BTC-USD
"""

from __future__ import annotations

import sys
from app.services.analysis import analyze_symbol


def main() -> None:
    symbols = sys.argv[1:] or ["NVDA", "MSFT", "AAPL", "META", "AMD", "BTC-USD"]
    results = []
    for symbol in symbols:
        result = analyze_symbol(symbol, timeframe="1d", include_ai=False)
        results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
    for r in results:
        print(f"{r.symbol:10} score={r.score:3} bias={r.bias:8} risk={r.risk:6} setup={r.setup}")


if __name__ == "__main__":
    main()
