# strategy-engine

Strategy Engine scores strategy candidates, assigns macro/regime context, and returns trade or observe decisions for a symbol.

## Quick start

Run locally with Python:

```bash
cd services/strategy-engine
python app/main.py
```

Run with Docker (from repo root):

```bash
docker build -f services/strategy-engine/Dockerfile -t strategy-engine .
docker run -p 8080:8080 strategy-engine
```

## Environment variables

All variables are optional. Defaults are shown.

### Core

- `PORT` (default: `8080`)

### Service URLs

- `FEATURE_FACTORY_BASE_URL` (default: `http://feature-factory:8080`)

### Score thresholds

- `STRICT_SCORE_THRESHOLD` (default: `68`)
- `TRADE_SCORE_THRESHOLD` (default: `68`)
- `OBSERVE_SCORE_THRESHOLD` (default: `55`)

### Macro penalties

- `MACRO_NEUTRAL_PENALTY` (default: `8`)
- `MACRO_TRANSITION_PENALTY` (default: `15`)

### Regime caps

- `REGIME_TRANSITION_CAP` (default: `72`)
- `REGIME_CHOP_CAP` (default: `62`)
- `REGIME_RANGE_TREND_CAP` (default: `58`)
- `REGIME_TREND_MEAN_REVERSION_CAP` (default: `52`)

## Endpoints

All responses are JSON. Query params use standard URL encoding.

### Health

- `GET /health`

### Analyze

- `POST /analyze` `{ "symbol": "BTCUSDT" }`

## Code layout

Routes live in [services/strategy-engine/app/server.py](services/strategy-engine/app/server.py). Supporting modules are grouped by responsibility under [services/strategy-engine/app](services/strategy-engine/app).