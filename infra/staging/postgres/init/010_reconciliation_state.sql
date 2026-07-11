-- 010_reconciliation_state.sql
--
-- Persists the safety state produced by a future exchange reconciliation worker.
--
-- Paper accounts do not require reconciliation.
-- Shadow/live accounts require a fresh HEALTHY reconciliation before new entry.
-- Close-only remains entry-blocked by execution mode and may still reduce/manage
-- existing positions even when reconciliation is degraded.

CREATE TABLE IF NOT EXISTS reconciliation_state (
    account_id INTEGER PRIMARY KEY
        REFERENCES accounts(account_id)
        ON DELETE CASCADE,

    provider TEXT NOT NULL DEFAULT 'blofin',

    status TEXT NOT NULL DEFAULT 'unknown',
    last_started_at TIMESTAMPTZ,
    last_completed_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,

    account_match BOOLEAN,
    positions_match BOOLEAN,
    orders_match BOOLEAN,

    mismatch_count INTEGER NOT NULL DEFAULT 0,
    max_age_seconds INTEGER NOT NULL DEFAULT 120,

    details_json JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT reconciliation_state_status_check
        CHECK (status IN ('unknown', 'running', 'healthy', 'drift', 'error')),

    CONSTRAINT reconciliation_state_mismatch_count_check
        CHECK (mismatch_count >= 0),

    CONSTRAINT reconciliation_state_max_age_seconds_check
        CHECK (max_age_seconds > 0)
);

INSERT INTO reconciliation_state (
    account_id,
    provider,
    status,
    mismatch_count,
    max_age_seconds,
    details_json,
    updated_at
)
SELECT
    account_id,
    'blofin',
    'unknown',
    0,
    120,
    '{}'::jsonb,
    NOW()
FROM accounts
WHERE account_type = 'live'
ON CONFLICT (account_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_reconciliation_state_status
ON reconciliation_state(status);

CREATE INDEX IF NOT EXISTS idx_reconciliation_state_last_success
ON reconciliation_state(last_success_at);
