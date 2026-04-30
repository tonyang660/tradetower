# scheduler

Scheduler orchestrates the trading cycle by refreshing market data, running candidate/strategy/risk pipelines, submitting paper orders, and handling pending entries, exits, and maintenance loops. It also pushes cycle summaries and equity snapshots to the evaluator service.

## Quick start

Run locally with Python:

```bash
cd services/scheduler
python app/main.py
```

Run with Docker (from repo root):

```bash
docker build -f services/scheduler/Dockerfile -t scheduler .
docker run -p 8080:8080 scheduler
```

## Environment variables

All variables are optional. Defaults are shown.

### Core

- `PORT` (default: `8080`)
- `ACCOUNT_ID` (default: `1`)
- `AUTO_LOOP_ENABLED` (default: `false`)
- `LOOP_INTERVAL_SECONDS` (default: `300`)
- `SYMBOL_UNIVERSE_PATH` (default: `/app/config/symbol_universe.json`)

### External service URLs

- `API_GATEWAY_BASE_URL` (default: `http://api-gateway:8080`)
- `DATA_HUB_BASE_URL` (default: `http://data-hub:8080`)
- `TRADE_GUARDIAN_BASE_URL` (default: `http://trade-guardian:8080`)
- `CANDIDATE_FILTER_BASE_URL` (default: `http://candidate-filter:8080`)
- `STRATEGY_ENGINE_BASE_URL` (default: `http://strategy-engine:8080`)
- `RISK_ENGINE_BASE_URL` (default: `http://risk-engine:8080`)
- `PAPER_EXECUTION_BASE_URL` (default: `http://paper-execution:8080`)
- `EVALUATOR_BASE_URL` (default: `http://evaluator:8080`)

### Paper execution

- `PAPER_EXECUTION_ENTRY_PATH` (default: `/entry/simulate`)

### Pending entry loop

- `PENDING_ENTRY_LOOP_INTERVAL_SECONDS` (default: `60`)
- `ENTRY_RETRY_MAX_ATTEMPTS` (default: `15`)

### Maintenance loop

- `MAINTENANCE_LOOP_INTERVAL_SECONDS` (default: `60`)

### Pending exit loop

- `PENDING_EXIT_LOOP_INTERVAL_SECONDS` (default: `60`)
- `EXIT_RETRY_MAX_ATTEMPTS` (default: `5`)

### Evaluator ingest

- `MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST` (default: `true`)

## Endpoints

All responses are JSON. Query params use standard URL encoding.

### Health

- `GET /health`

### Controls

- `POST /controls/auto-loop` `{ "enabled": true }`
- `POST /cycle/run-once` `{}`

## Code layout

Routes live in [services/scheduler/app/main.py](services/scheduler/app/main.py). Supporting modules are grouped by responsibility under [services/scheduler/app](services/scheduler/app).