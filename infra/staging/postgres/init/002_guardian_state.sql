CREATE TABLE IF NOT EXISTS guardian_state (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    manual_halt BOOLEAN NOT NULL DEFAULT FALSE,
    daily_kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
    weekly_kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
    max_concurrent_positions INTEGER NOT NULL DEFAULT 5,
    daily_loss_limit_pct NUMERIC(10,4) NOT NULL DEFAULT 3.0,
    weekly_loss_limit_pct NUMERIC(10,4) NOT NULL DEFAULT 6.0,
    daily_basis_equity NUMERIC(18,8) NOT NULL DEFAULT 0,
    weekly_basis_equity NUMERIC(18,8) NOT NULL DEFAULT 0,
    daily_basis_date DATE NOT NULL DEFAULT CURRENT_DATE,
    weekly_basis_start DATE NOT NULL DEFAULT CURRENT_DATE,
    weekly_kill_switch_expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO guardian_state (
    account_id,
    trading_enabled,
    manual_halt,
    daily_kill_switch,
    weekly_kill_switch,
    max_concurrent_positions,
    daily_loss_limit_pct,
    weekly_loss_limit_pct,
    daily_basis_equity,
    weekly_basis_equity,
    daily_basis_date,
    weekly_basis_start,
    weekly_kill_switch_expires_at,
    updated_at
)
SELECT
    ab.account_id,
    TRUE,
    FALSE,
    FALSE,
    FALSE,
    5,
    3.0,
    6.0,
    ab.equity,
    ab.equity,
    CURRENT_DATE,
    CURRENT_DATE,
    NULL,
    NOW()
FROM account_balances ab
JOIN accounts a ON a.account_id = ab.account_id
WHERE a.account_name = 'paper-main'
ON CONFLICT (account_id) DO NOTHING;
