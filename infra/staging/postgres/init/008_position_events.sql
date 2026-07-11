-- 008_position_events.sql
--
-- Adds an append-only position-management audit ledger.
--
-- orders remain the authority for order state.
-- execution_reports remain the authority for fills.
-- position_events records the chronological management lifecycle of a position.

CREATE TABLE IF NOT EXISTS position_events (
    position_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES positions(position_id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES orders(order_id) ON DELETE SET NULL,
    execution_id INTEGER REFERENCES execution_reports(execution_id) ON DELETE SET NULL,

    event_type TEXT NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    price NUMERIC(18,8),
    size_before NUMERIC(18,8),
    size_delta NUMERIC(18,8),
    size_after NUMERIC(18,8),

    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_events_position_time
ON position_events(position_id, event_timestamp, position_event_id);

CREATE INDEX IF NOT EXISTS idx_position_events_account_time
ON position_events(account_id, event_timestamp);

CREATE INDEX IF NOT EXISTS idx_position_events_type
ON position_events(event_type);
