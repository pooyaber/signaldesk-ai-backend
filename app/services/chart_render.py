from __future__ import annotations

import html
from urllib.parse import quote_plus

from app.services.market_data import get_chart_data


COLORS = {
    "bg": "#07101d",
    "card": "#101b2e",
    "line": "rgba(255,255,255,.12)",
    "text": "#f6f8ff",
    "muted": "#92a1b8",
    "green": "#2df2ad",
    "cyan": "#42d6ff",
    "violet": "#8d7bff",
    "amber": "#ffc857",
    "red": "#ff5f7d",
}


def _num(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:,.3f}"
    return f"{value:,.4f}"


def _values(candles: list[dict], keys: list[str]) -> list[float]:
    output: list[float] = []
    for candle in candles:
        for key in keys:
            value = _num(candle.get(key))
            if value is not None:
                output.append(value)
    return output


def _range(values: list[float], padding: float = 0.08) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    low = min(values)
    high = max(values)
    if low == high:
        low -= 1
        high += 1
    extra = (high - low) * padding
    return low - extra, high + extra


def _chart_frame(title: str, body: str, height: int = 240) -> str:
    return f"""
      <section class="chartBox">
        <div class="chartTitle">{html.escape(title)}</div>
        <svg viewBox="0 0 900 {height}" role="img" aria-label="{html.escape(title)} chart">
          {body}
        </svg>
      </section>
    """


def _grid(min_value: float, max_value: float, width: int, height: int) -> str:
    left = 72
    right = 16
    top = 16
    bottom = 30
    plot_width = width - left - right
    plot_height = height - top - bottom
    lines = []
    for index in range(4):
        y = top + (plot_height * index / 3)
        value = max_value - ((max_value - min_value) * index / 3)
        lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" class="grid"/>'
        )
        lines.append(
            f'<text x="{left - 8}" y="{y + 4:.2f}" class="axis" text-anchor="end">{_fmt(value)}</text>'
        )
    return "".join(lines)


def _scales(count: int, min_value: float, max_value: float, width: int, height: int):
    left = 72
    right = 16
    top = 16
    bottom = 30
    plot_width = width - left - right
    plot_height = height - top - bottom

    def x_at(index: int) -> float:
        if count <= 1:
            return left + plot_width / 2
        return left + (plot_width * index / (count - 1))

    def y_at(value: float) -> float:
        return top + ((max_value - value) / (max_value - min_value)) * plot_height

    return x_at, y_at, left, top, plot_width, plot_height


def _polyline(candles: list[dict], key: str, color: str, min_value: float, max_value: float, width: int, height: int) -> str:
    x_at, y_at, *_ = _scales(len(candles), min_value, max_value, width, height)
    points = []
    for index, candle in enumerate(candles):
        value = _num(candle.get(key))
        if value is not None:
            points.append(f"{x_at(index):.2f},{y_at(value):.2f}")
    if len(points) < 2:
        return ""
    return f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'


def _candles_chart(candles: list[dict]) -> str:
    width = 900
    height = 260
    min_value, max_value = _range(_values(candles, ["high", "low"]))
    x_at, y_at, *_ = _scales(len(candles), min_value, max_value, width, height)
    candle_width = max(2.0, min(9.0, 720 / max(1, len(candles))))
    parts = [_grid(min_value, max_value, width, height)]

    for index, candle in enumerate(candles):
        open_price = _num(candle.get("open"))
        high = _num(candle.get("high"))
        low = _num(candle.get("low"))
        close = _num(candle.get("close"))
        if None in (open_price, high, low, close):
            continue

        x = x_at(index)
        y_open = y_at(open_price)
        y_close = y_at(close)
        y_high = y_at(high)
        y_low = y_at(low)
        color = COLORS["green"] if close >= open_price else COLORS["red"]
        body_top = min(y_open, y_close)
        body_height = max(2.0, abs(y_close - y_open))
        parts.append(f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" stroke="{color}" stroke-width="1.4"/>')
        parts.append(
            f'<rect x="{x - candle_width / 2:.2f}" y="{body_top:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" rx="1.5" fill="{color}"/>'
        )

    return _chart_frame("Candles", "".join(parts), height)


def _bar_chart(candles: list[dict], key: str, title: str) -> str:
    width = 900
    height = 170
    _, max_value = _range(_values(candles, [key]), padding=0.18)
    min_value = 0.0
    x_at, y_at, *_ = _scales(len(candles), min_value, max(max_value, 1.0), width, height)
    bar_width = max(2.0, min(10.0, 760 / max(1, len(candles))))
    parts = [_grid(min_value, max(max_value, 1.0), width, height)]
    zero_y = y_at(0)

    for index, candle in enumerate(candles):
        value = _num(candle.get(key))
        if value is None:
            continue
        close = _num(candle.get("close"))
        open_price = _num(candle.get("open"))
        color = COLORS["green"] if close is not None and open_price is not None and close >= open_price else COLORS["red"]
        y = y_at(value)
        parts.append(
            f'<rect x="{x_at(index) - bar_width / 2:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{max(1, zero_y - y):.2f}" fill="{color}" opacity=".78"/>'
        )

    return _chart_frame(title, "".join(parts), height)


def _line_chart(candles: list[dict], title: str, series: list[tuple[str, str]], fixed_range: tuple[float, float] | None = None) -> str:
    width = 900
    height = 170
    keys = [key for key, _ in series]
    min_value, max_value = fixed_range or _range(_values(candles, keys))
    parts = [_grid(min_value, max_value, width, height)]
    for key, color in series:
        parts.append(_polyline(candles, key, color, min_value, max_value, width, height))
    return _chart_frame(title, "".join(parts), height)


def _macd_chart(candles: list[dict]) -> str:
    width = 900
    height = 170
    min_value, max_value = _range(_values(candles, ["macd", "macd_signal", "macd_histogram"]), padding=0.18)
    x_at, y_at, *_ = _scales(len(candles), min_value, max_value, width, height)
    bar_width = max(2.0, min(9.0, 760 / max(1, len(candles))))
    parts = [_grid(min_value, max_value, width, height)]
    zero_y = y_at(0)

    for index, candle in enumerate(candles):
        value = _num(candle.get("macd_histogram"))
        if value is None:
            continue
        y = y_at(value)
        color = COLORS["green"] if value >= 0 else COLORS["red"]
        parts.append(
            f'<rect x="{x_at(index) - bar_width / 2:.2f}" y="{min(y, zero_y):.2f}" width="{bar_width:.2f}" height="{max(1, abs(zero_y - y)):.2f}" fill="{color}" opacity=".58"/>'
        )

    parts.append(_polyline(candles, "macd", COLORS["cyan"], min_value, max_value, width, height))
    parts.append(_polyline(candles, "macd_signal", COLORS["amber"], min_value, max_value, width, height))
    return _chart_frame("MACD", "".join(parts), height)


def render_chart_dashboard(symbol: str = "AAPL", range_key: str = "6M") -> str:
    chart = get_chart_data(symbol=symbol, range_key=range_key)
    candles = chart.get("candles", [])
    selected_range = chart.get("range", range_key.upper())
    safe_symbol = html.escape(chart.get("symbol", symbol))
    query_symbol = quote_plus(chart.get("symbol", symbol))
    ranges = ["1D", "7D", "6M", "1Y", "5Y", "ALL"]

    range_links = "".join(
        f'<a class="range {"active" if value == selected_range else ""}" href="/?symbol={query_symbol}&range={value}">{value.title() if value == "ALL" else value}</a>'
        for value in ranges
    )

    if candles:
        charts_html = "".join(
            [
                _candles_chart(candles),
                _bar_chart(candles, "volume", "Volume"),
                _line_chart(
                    candles,
                    "Bollinger Bands",
                    [
                        ("close", COLORS["text"]),
                        ("bb_upper", COLORS["violet"]),
                        ("bb_middle", COLORS["cyan"]),
                        ("bb_lower", COLORS["violet"]),
                    ],
                ),
                _line_chart(
                    candles,
                    "SMA 20 / 50 / 200",
                    [
                        ("close", "rgba(246,248,255,.68)"),
                        ("sma20", COLORS["cyan"]),
                        ("sma50", COLORS["amber"]),
                        ("sma200", COLORS["red"]),
                    ],
                ),
                _macd_chart(candles),
                _line_chart(candles, "RSI 14", [("rsi14", COLORS["green"])], fixed_range=(0, 100)),
                _line_chart(candles, "ATR 14", [("atr14", COLORS["amber"])]),
            ]
        )
    else:
        charts_html = '<section class="chartBox"><div class="chartTitle">No chart data</div><p class="sub">Try another symbol.</p></section>'

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SignalDesk AI Charts</title>
  <style>
    :root{{--bg:#07101d;--card:#101b2e;--line:rgba(255,255,255,.12);--text:#f6f8ff;--muted:#92a1b8;--green:#2df2ad;--cyan:#42d6ff;--violet:#8d7bff;--amber:#ffc857;--red:#ff5f7d}}
    *{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(180deg,#07101d,#050814);color:var(--text);font-family:Inter,system-ui,Segoe UI,Arial,sans-serif;padding:18px;min-height:100vh}}
    .wrap{{max-width:980px;margin:0 auto}} .top{{display:flex;gap:10px;align-items:center;justify-content:space-between;margin-bottom:14px}} .title{{font-size:28px;font-weight:950}} .sub{{color:var(--muted);font-size:14px}}
    .panel,.chartBox{{background:rgba(16,27,46,.86);border:1px solid var(--line);border-radius:18px;padding:14px;margin-bottom:12px;box-shadow:0 18px 60px rgba(0,0,0,.22)}}
    .controls{{display:grid;grid-template-columns:1fr auto;gap:10px}} .field{{background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:12px;color:var(--text);padding:12px;font-size:16px}} .btn{{border:0;border-radius:12px;padding:12px 18px;background:linear-gradient(135deg,var(--cyan),var(--violet));font-weight:900;color:#06101b;text-decoration:none}}
    .ranges{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:10px}} .range{{border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.06);color:var(--muted);font-weight:900;padding:10px;text-align:center;text-decoration:none}} .range.active{{background:linear-gradient(135deg,var(--cyan),var(--violet));color:#06101b;border-color:transparent}}
    .chartTitle{{font-weight:900;margin-bottom:8px;color:#dfe8f8}} svg{{display:block;width:100%;height:auto}} .grid{{stroke:rgba(255,255,255,.08);stroke-width:1}} .axis{{fill:var(--muted);font-size:11px}}
    @media (max-width:560px){{body{{padding:12px}} .title{{font-size:22px}} .ranges{{gap:5px}} .range{{font-size:12px;padding:9px 3px}}}}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="top">
      <div>
        <div class="title">SignalDesk AI Charts</div>
        <div class="sub">{safe_symbol} {html.escape(str(selected_range))} / {html.escape(str(chart.get("interval", "")))} candles: {len(candles)}</div>
      </div>
      <a class="sub" href="/docs">API docs</a>
    </div>
    <section class="panel">
      <form class="controls" method="get" action="/">
        <input class="field" name="symbol" value="{safe_symbol}">
        <input type="hidden" name="range" value="{html.escape(str(selected_range))}">
        <button class="btn" type="submit">Load</button>
      </form>
      <div class="ranges">{range_links}</div>
    </section>
    {charts_html}
  </main>
</body>
</html>
"""
