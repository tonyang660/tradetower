# trade-guardian

Trade Guardian enforces account-level safety checks, manages open positions and protective orders, records executions, and maintains mark-to-market state. It exposes guard endpoints for entry and maintenance decisions.

## Quick start

Run locally with Python:

```bash
cd services/trade-guardian
python app/main.py
```

Run with Docker (from repo root):

```bash
docker build -f services/trade-guardian/Dockerfile -t trade-guardian .
docker run -p 8080:8080 trade-guardian
```

## Environment variables

All variables are optional. Defaults are shown.

### Core

- `PORT` (default: `8080`)
- `APP_ENV` (default: `unknown`)

### Postgres

- `POSTGRES_HOST` (default: `postgres`)
- `POSTGRES_PORT` (default: `5432`)
- `POSTGRES_DB` (default: `trading_platform`)
- `POSTGRES_USER` (default: `trading`)
- `POSTGRES_PASSWORD` (default: `change_me`)

### API Gateway

- `API_GATEWAY_BASE_URL` (default: `http://api-gateway:8080`)
- `API_GATEWAY_LATEST_PRICE_PATH` (default: `/providers/bitget/ticker`)

### Mark-to-market loop

- `MTM_AUTO_REFRESH_ENABLED` (default: `false`)
- `MTM_REFRESH_INTERVAL_SECONDS` (default: `30`)
- `MTM_ACCOUNT_ID` (default: `1`)

## Endpoints

All responses are JSON. Query params use standard URL encoding.

### Health

- `GET /health`

### Status and positions

- `GET /status?account_id=1`
- `GET /position/open?account_id=1&symbol=BTCUSDT`
- `GET /positions/open?account_id=1`
- `GET /orders/open?account_id=1`

### Guards and controls

- `POST /guard/check-entry` `{ "account_id": 1, "symbol": "BTCUSDT" }`
- `POST /guard/check-maintenance` `{ "account_id": 1, "symbol": "BTCUSDT" }`
- `POST /guard/manual-halt` `{ "account_id": 1, "enabled": true, "reason_code": "MANUAL_HALT" }`

### Execution and mark-to-market

- `POST /execution/apply` `{ ...execution payload... }`
- `POST /mark-to-market/refresh` `{ "account_id": 1 }`
- `POST /orders/reprice-protective` `{ "account_id": 1, "order_id": 123, "new_price": 100.5 }`

## Code layout

Routes live in [services/trade-guardian/app/main.py](services/trade-guardian/app/main.py). Supporting modules are grouped by responsibility under [services/trade-guardian/app](services/trade-guardian/app).