CREATE TABLE IF NOT EXISTS evaluator_events (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    event_version TEXT NOT NULL,
    event_family TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ,
    account_id INTEGER,
    symbol TEXT,
    position_id TEXT,
    order_id TEXT,
    cycle_id TEXT,
    source_service TEXT,
    source_version TEXT,
    strategy_name TEXT,
    strategy_side TEXT,
    regime TEXT,
    execution_mode TEXT,
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluator_events_account_time
ON evaluator_events (account_id, event_time DESC);

CREATE INDEX IF NOT EXISTS idx_evaluator_events_family_type
ON evaluator_events (event_family, event_type);

CREATE INDEX IF NOT EXISTS idx_evaluator_events_cycle
ON evaluator_events (cycle_id);

CREATE INDEX IF NOT EXISTS idx_evaluator_events_symbol_time
ON evaluator_events (symbol, event_time DESC);
