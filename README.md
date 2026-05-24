# TradingView AI Backend MVP

A small FastAPI backend that receives TradingView webhook alerts, enriches them with market data, scores the setup, optionally asks an AI model for analysis, stores the result in SQLite, and can send a Telegram alert.

This is an **AI analyst assistant**, not an auto-trading bot.

## What it does

- `POST /webhook/tradingview` receives TradingView alerts.
- `POST /analyze` analyzes any symbol manually.
- `POST /scan` scans a watchlist and ranks symbols.
- `GET /signals` shows recent analysis results.
- Optional OpenAI analysis if `OPENAI_API_KEY` is configured.
- Optional Telegram notifications if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured.

## Quick start

```bash
cd tradingview_ai_backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000/docs
```

## Environment variables

Edit `.env`:

```env
APP_ENV=development
PUBLIC_API_URL=http://127.0.0.1:8000
CORS_ORIGINS=*
WEBHOOK_SECRET=change-me
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DATABASE_PATH=signals.db
```

If no OpenAI key is set, the backend still works with a rules-based score.

## Cloud deployment

The backend is ready for Render or Railway. Keep all secrets in the backend environment variables. Do not put OpenAI, Telegram, or webhook secrets in the Android app.

### Render

Use the included `render.yaml`, or create a Web Service manually with:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set these environment variables in Render:

```env
APP_ENV=production
PUBLIC_API_URL=https://your-render-service.onrender.com
CORS_ORIGINS=*
WEBHOOK_SECRET=your_secret_here
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DATABASE_PATH=/tmp/signals.db
```

### Railway

Use the included `railway.json`. Set the same environment variables in Railway. Railway provides `PORT`; the start command uses it automatically.

Production health check:

```text
https://your-production-api/health
```

Note: `DATABASE_PATH=/tmp/signals.db` is fine for testing, but cloud disks may be ephemeral. Use a managed database before relying on signal history in production.

## TradingView alert setup

In TradingView:

1. Create an alert.
2. Enable Webhook URL.
3. Use:

```text
https://your-domain.com/webhook/tradingview?token=change-me
```

For local testing, use ngrok or Cloudflare Tunnel.

Example TradingView alert message:

```json
{
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "timeframe": "2h",
  "price": {{close}},
  "alert_name": "EMA breakout",
  "strategy": "EMA20/50/200 + RSI",
  "note": "TradingView alert triggered"
}
```

If TradingView complains about JSON, wrap dynamic values in quotes:

```json
{
  "symbol": "{{ticker}}",
  "exchange": "{{exchange}}",
  "timeframe": "2h",
  "price": "{{close}}",
  "alert_name": "EMA breakout"
}
```

## Manual test

```bash
curl -X POST "http://localhost:8000/webhook/tradingview?token=change-me" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC-USD","timeframe":"2h","price":75853.60,"alert_name":"support test"}'
```

Manual analysis:

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"NVDA","timeframe":"1d"}'
```

Scan a watchlist:

```bash
curl -X POST "http://localhost:8000/scan" \
  -H "Content-Type: application/json" \
  -d '{"symbols":["NVDA","MSFT","AAPL","META","AMD","BTC-USD"],"timeframe":"1d"}'
```

## Symbol notes

Yahoo Finance symbols are used for market data.

Examples:

- `BTC-USD` instead of TradingView `BTCUSD`
- `ETH-USD`
- `NVDA`
- `AAPL`
- `^GSPC` for S&P 500
- `EURUSD=X`

The backend tries to map common TradingView crypto symbols automatically.

## Suggested next upgrades

- Add Polygon.io / Finnhub for cleaner market data.
- Add sector strength scoring.
- Add earnings/news sentiment.
- Add a React dashboard.
- Add backtesting before trusting any score.
- Add risk rules: max position size, invalidation level, stop-loss distance.

## Disclaimer

This project is for analysis and education only. It does not provide financial advice and does not execute trades.
