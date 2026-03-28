# External Integrations

**Analysis Date:** 2026-03-28

## APIs & External Services

**Market Data — Forex & Commodities:**
- Dukascopy — tick/OHLCV data for forex and commodities pairs (~3,000 valid symbols in `metadata/dukas_assets.csv`)
  - SDK/Client: `dukascopy-python>=4.0.1`
  - Auth: No API key required (public data)
  - Fetcher: `components/datamanager/src/trademachine/datamanager/fetchers/dukascopy.py`

**Market Data — Equities & ETFs:**
- OpenBB (YFinance provider) — equity and ETF OHLCV data via Yahoo Finance
  - SDK/Client: `openbb>=4.7.1`, `openbb-yfinance>=1.6.0`
  - Auth: No API key required (public data via YFinance)
  - Fetcher: `components/datamanager/src/trademachine/datamanager/fetchers/openbb.py`
  - Usage: `obb.equity.price.historical(symbol, interval="1m", provider="yfinance")`

**Market Data — Crypto:**
- CCXT — unified cryptocurrency exchange API supporting Binance, Bybit, and others
  - SDK/Client: `ccxt>=4.5.44`
  - Auth: No key required for public OHLCV endpoints; exchange selected via `exchange:SYMBOL` prefix (e.g., `binance:BTC/USDT`)
  - Fetcher: `components/datamanager/src/trademachine/datamanager/fetchers/ccxt.py`
  - Default exchange: Binance when no prefix given

**Trading Platform — MetaTrader 5:**
- MT5 Expert Advisor (MQL5) — publishes real-time trade data (DEAL, EQUITY, ACCOUNT topics) over TCP to TradingMonitor
  - Protocol: Raw TCP socket, JSON payloads, format `"{TOPIC} {JSON}"`
  - Port: `127.0.0.1:5555` (configurable via `SERVER_HOST`/`SERVER_PORT` env vars)
  - EA source: MQL5 Expert Advisor (`MetricsPublisher.mq5`) runs inside MT5 terminal
  - Receiver: `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/tcp_server.py`
  - MT5 data format parsing: `components/mt5/` component

## Notifications

**Telegram Bot API:**
- Used by TradingMonitor for real-time trade alerts and report delivery
  - Client: `httpx>=0.28.1` (async HTTP to `https://api.telegram.org/bot{token}/sendMessage` and `/sendDocument`)
  - Auth: `TELEGRAM_TOKEN` (bot token), `TELEGRAM_CHAT_ID`
  - Toggle: `ENABLE_NOTIFICATIONS=False` (disabled by default)
  - Implementation: `components/tradingmonitor/src/trademachine/tradingmonitor/utils/notifications.py`
  - Alert types:
    - New strategy auto-detected
    - Critical ingestion errors
    - Low margin warnings (threshold: `MARGIN_THRESHOLD_PCT`, default 20%)
    - VaR 95% breach alerts (threshold: `VAR_95_THRESHOLD`, default 5%)
    - QuantStats HTML report delivery via document upload

## Data Storage

**Databases:**
- TimescaleDB (PostgreSQL 15 + TimescaleDB extension)
  - Used by: DataManager (OHLCV storage), TradingMonitor (trade data)
  - Connection: `DATABASE_URL` env var
    - DataManager default: `postgresql://postgres:password@localhost:5433/tradingmonitor`
    - TradingMonitor default: `postgresql://postgres:password@localhost:5432/trademachine.tradingmonitor`
  - Client: SQLAlchemy `>=2.0.48` + psycopg2-binary `>=2.9.11`
  - Docker image: `timescale/timescaledb:latest-pg15` (see `projects/tradingmonitor/docker-compose.yml`)
  - Hypertables:
    - DataManager: `ohlcv_m1` (partitioned by timestamp)
    - DataManager: Continuous Aggregates for `ohlcv_m5`, `ohlcv_m15`, `ohlcv_h1`, `ohlcv_h4`, `ohlcv_d1`
    - TradingMonitor: `deals`, `equity_curve` (both hypertables)
  - Migrations: Alembic (`projects/datamanager/alembic/`) with two versions: initial schema + continuous aggregates

**File Storage:**
- Local filesystem — Parquet files for PortfolioMaster parsed MT5 report cache
  - Format: Polars/PyArrow Parquet (`cache.parquet` in working directory)
  - Fallback: re-parses raw MT5 HTML reports if cache is missing/invalid

**Legacy Catalog (DataManager — transitional):**
- SQLite — `metadata/catalog.db` (WAL mode) — metadata index for stored data
  - Note: Being replaced by TimescaleDB; the `StorageManager` class now uses PostgreSQL directly

## Authentication & Identity

**DataManager REST API:**
- API key authentication via `X-API-Key` header
  - Config: `DATAMANAGER_API_KEY` env var (prefix: `DATAMANAGER_`)
  - Implementation: `bases/datamanager_api/src/trademachine/datamanager_api/router.py` — `APIKeyHeader` from FastAPI security
  - Key validation: `settings.is_api_key_configured` property checks non-empty and non-default value

**TradingMonitor:**
- API key: `API_KEY` env var (used for dashboard access)
- No multi-user authentication; single-user personal project

## CI/CD & Deployment

**Container Registry:**
- GitHub Container Registry (`ghcr.io/guilsmatos1/datamanager:latest`) — DataManager API Docker image

**Hosting:**
- Self-hosted / personal server
- CasaOS application metadata present in `projects/datamanager/docker-compose.yml` (indicates potential deployment on CasaOS home server platform)
- No cloud provider detected

**CI Pipeline:**
- Not detected (no `.github/workflows/` CI config found)
- Pre-commit hooks enforce quality gates locally (see `STACK.md`)

## Webhooks & Callbacks

**Incoming:**
- TCP socket server on `127.0.0.1:5555` — receives real-time DEAL, EQUITY, ACCOUNT messages from MT5 EA
  - Not HTTP webhooks; raw TCP protocol
  - Receiver: `components/tradingmonitor/src/trademachine/tradingmonitor/ingestion/tcp_server.py`

**Outgoing:**
- Telegram Bot API — `POST https://api.telegram.org/bot{token}/sendMessage` and `/sendDocument`
  - Triggered by: margin alerts, VaR alerts, ingestion errors, new strategy detection, QuantStats report delivery

## Environment Configuration

**Required env vars (TradingMonitor):**
- `DATABASE_URL` — TimescaleDB connection string
- `API_KEY` — dashboard authentication key
- `SERVER_HOST` — TCP ingestion host (default: `127.0.0.1`)
- `SERVER_PORT` — TCP ingestion port (default: `5555`)

**Required env vars (DataManager):**
- `DATAMANAGER_API_KEY` — REST API authentication
- `DATAMANAGER_HOST` — API bind host (default: `0.0.0.0`)
- `DATAMANAGER_PORT` — API port (default: `8686`)
- `DATABASE_URL` (via `DATAMANAGER_DATABASE_URL` prefix) — TimescaleDB connection

**Optional env vars (TradingMonitor notifications):**
- `ENABLE_NOTIFICATIONS` — toggle Telegram alerts (default: `False`)
- `TELEGRAM_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — Telegram chat ID for alerts
- `MARGIN_THRESHOLD_PCT` — margin alert threshold % (default: `20.0`)
- `VAR_95_THRESHOLD` — VaR 95% alert threshold % (default: `5.0`)

**Optional env vars (TradingMonitor drift detection):**
- `ENABLE_DRIFT_ALERTS` — toggle performance drift alerts (default: `True`)
- `DRIFT_WIN_RATE_THRESHOLD` — max % win rate drop allowed (default: `15.0`)
- `DRIFT_PF_THRESHOLD` — max % profit factor drop allowed (default: `20.0`)
- `DRIFT_DD_MULTIPLIER` — max drawdown multiplier vs backtest (default: `1.2`)
- `DRIFT_MIN_TRADES` — min trades before drift check triggers (default: `20`)

**Secrets location:**
- `.env` file at workspace root (not committed; `.env.example` is the template)
- Docker Compose injects env vars via `environment:` section

## Monitoring & Observability

**Error Tracking:**
- Dead-letter file — failed TCP messages written to `/tmp/trademachine.tradingmonitor_dead_letters.jsonl` (path configurable via `DEAD_LETTER_FILE`)
- Heartbeat file — `/tmp/trademachine.tradingmonitor_heartbeat` (path configurable via `HEARTBEAT_FILE`) for ingestion daemon liveness

**Logs:**
- Structured JSON logging via `python-json-logger` (`pythonjsonlogger.json.JsonFormatter`)
- Logger setup in `components/core/src/trademachine/core/` — shared `LOGGER_NAME` constant
- TCP ingestion server logs to JSON format; dashboard and API use standard Python logging

---

*Integration audit: 2026-03-28*
