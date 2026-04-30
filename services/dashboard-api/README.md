# dashboard-api

Lightweight HTTP service that aggregates system status, trading configuration, and performance data for the dashboard UI. This service is intentionally dependency-light and exposes a small set of JSON endpoints.

## Quick start

Run locally with Python:

```bash
cd services/dashboard-api
python app/main.py
```

Run with Docker (from repo root):

```bash
docker build -f services/dashboard-api/Dockerfile -t dashboard-api .
docker run -p 8080:8080 dashboard-api
```

## Environment variables

All variables are optional. Defaults are shown.

### Core

- `PORT` (default: `8080`)
- `APP_ENV` (default: `staging`)
- `SYMBOL_UNIVERSE_PATH` (default: `/config/symbol_universe.json`)

### Service URLs

- `EVALUATOR_BASE_URL` (default: `http://evaluator:8080`)
- `SCHEDULER_BASE_URL` (default: `http://scheduler:8080`)
- `TRADE_GUARDIAN_BASE_URL` (default: `http://trade-guardian:8080`)
- `CANDIDATE_FILTER_BASE_URL` (default: `http://candidate-filter:8080`)
- `STRATEGY_ENGINE_BASE_URL` (default: `http://strategy-engine:8080`)
- `RISK_ENGINE_BASE_URL` (default: `http://risk-engine:8080`)
- `PAPER_EXECUTION_BASE_URL` (default: `http://paper-execution:8080`)
- `API_GATEWAY_BASE_URL` (default: `http://api-gateway:8080`)
- `DATA_HUB_BASE_URL` (default: `http://data-hub:8080`)

### Trading configuration

- `STRICT_SCORE_THRESHOLD` (default: `75`)
- `MAX_RISK_PCT` (default: `1.0`)
- `MAX_LEVERAGE` (default: `15.0`)
- `MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE` (default: `1.0`)
- `LIMIT_FEE_PCT` (default: `0.02`)
- `MARKET_FEE_PCT` (default: `0.06`)
- `MARKET_SLIPPAGE_PCT` (default: `0.06`)

### MTM refresh

- `MTM_AUTO_REFRESH_ENABLED` (default: `true`)
- `MTM_AUTO_REFRESH_INTERVAL_SECONDS` (default: `30`)

## Endpoints

All responses are JSON. Query params use standard URL encoding.

### Health and status

- `GET /health`
- `GET /system/health`
- `GET /market/banner`

### Bootstrap

- `GET /bootstrap/overview?account_id=1`
- `GET /bootstrap/live-cycle-monitor?account_id=1&limit=15`
- `GET /bootstrap/performance?account_id=1`
- `GET /bootstrap/system-health?account_id=1`
- `GET /bootstrap/configuration`

### Positions and orders

- `GET /positions/open?account_id=1&refresh=true`
- `GET /positions/recent?account_id=1&limit=20`
- `GET /orders/open?account_id=1`
- `GET /orders/executed?account_id=1&limit=50`

### Controls and configuration

- `POST /controls/trading/suspend` `{ "account_id": 1 }`
- `POST /controls/trading/resume` `{ "account_id": 1 }`
- `POST /controls/scheduler/enable` `{}`
- `POST /controls/scheduler/disable` `{}`
- `POST /configuration/validate-symbol` `{ "symbol": "BTCUSDT" }`
- `POST /configuration/symbol-universe` `{ "symbols": ["BTCUSDT", "ETHUSDT"] }`
- `POST /configuration/auto-loop` `{ "enabled": true }`

## Code layout

The main router lives in [services/dashboard-api/app/main.py](services/dashboard-api/app/main.py). Supporting modules are grouped by responsibility under [services/dashboard-api/app](services/dashboard-api/app) and [services/dashboard-api/app/bootstrap](services/dashboard-api/app/bootstrap).