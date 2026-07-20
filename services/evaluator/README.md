# evaluator

Evaluator aggregates trade data, performance analytics, and cycle history for the platform. It also ingests cycle summaries and equity snapshots into Postgres.

## Quick start

Run locally with Python:

```bash
cd services/evaluator
python app/main.py
```

Run with Docker (from repo root):

```bash
docker build -f services/evaluator/Dockerfile -t evaluator .
docker run -p 8080:8080 evaluator
```

## Environment variables

All variables are optional. Defaults are shown.

### Core

- `PORT` (default: `8080`)

### Postgres

- `POSTGRES_HOST` (default: `postgres`)
- `POSTGRES_PORT` (default: `5432`)
- `POSTGRES_DB` (default: `trading_platform`)
- `POSTGRES_USER` (default: `trading`)
- `POSTGRES_PASSWORD` (default: `trading`)

### Service URLs

- `TRADE_GUARDIAN_BASE_URL` (default: `http://trade-guardian:8080`)

## Endpoints

All responses are JSON. Query params use standard URL encoding.

### Health

- `GET /health`

### Overview

- `GET /overview?account_id=1`

### Positions and orders

- `GET /positions/open?account_id=1&refresh=true`
- `GET /positions/recent?account_id=1&limit=20`
- `GET /orders/open?account_id=1`
- `GET /orders/executed?account_id=1&limit=50`

### Equity and cycles

- `GET /equity/history?account_id=1&limit=100`
- `GET /cycles/latest?account_id=1`
- `GET /cycles/history?account_id=1&limit=50`

### Performance

- `GET /performance/summary?account_id=1`
- `GET /performance/summary-extended?account_id=1`
- `GET /performance/pnl-series?account_id=1&limit=200`
- `GET /performance/drawdown-series?account_id=1&limit=10000`
- `GET /performance/directional-breakdown?account_id=1`
- `GET /performance/hourly?account_id=1`
- `GET /performance/weekday?account_id=1`
- `GET /performance/session?account_id=1`
- `GET /performance/calendar?account_id=1&limit_days=120`
- `GET /performance/monthly-summary?account_id=1`

### Analytics

- `GET /analytics/decision-funnel?account_id=1`

### Ingest

- `POST /ingest/cycle-summary`
- `POST /ingest/equity-snapshot`
- `POST /ingest/pending-entry-event`

## Code layout

Routes live in [services/evaluator/app/main.py](services/evaluator/app/main.py). Supporting modules are grouped by responsibility under [services/evaluator/app](services/evaluator/app).