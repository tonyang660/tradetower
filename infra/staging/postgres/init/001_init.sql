CREATE TABLE IF NOT EXISTS accounts (
    account_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL CHECK (account_type IN ('paper', 'live')),
    starting_balance NUMERIC(18,8) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS account_balances (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    cash_balance NUMERIC(18,8) NOT NULL,
    equity NUMERIC(18,8) NOT NULL,
    realized_pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
    unrealized_pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
    fees_paid_total NUMERIC(18,8) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions (
    position_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    size NUMERIC(18,8) NOT NULL,
    entry_price NUMERIC(18,8) NOT NULL,
    leverage NUMERIC(18,8) NOT NULL,
    margin_used NUMERIC(18,8) NOT NULL,
    stop_loss NUMERIC(18,8),
    take_profit NUMERIC(18,8),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed'))
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    requested_price NUMERIC(18,8),
    requested_size NUMERIC(18,8) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'submitted', 'filled', 'cancelled', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS execution_reports (
    execution_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id) ON DELETE SET NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    fill_price NUMERIC(18,8) NOT NULL,
    filled_size NUMERIC(18,8) NOT NULL,
    fee_paid NUMERIC(18,8) NOT NULL DEFAULT 0,
    slippage_bps NUMERIC(18,8) NOT NULL DEFAULT 0,
    execution_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    entry_price NUMERIC(18,8) NOT NULL,
    exit_price NUMERIC(18,8),
    size NUMERIC(18,8) NOT NULL,
    realized_pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
    fees_paid NUMERIC(18,8) NOT NULL DEFAULT 0,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS guardian_events (
    event_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cycle_runs (
    cycle_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    llm_invocations INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

INSERT INTO accounts (account_name, account_type, starting_balance, is_active)
VALUES ('paper-main', 'paper', 2000.00000000, TRUE)
ON CONFLICT (account_name) DO NOTHING;

INSERT INTO account_balances (account_id, cash_balance, equity, realized_pnl, unrealized_pnl, fees_paid_total)
SELECT account_id, starting_balance, starting_balance, 0, 0, 0
FROM accounts
WHERE account_name = 'paper-main'
ON CONFLICT (account_id) DO NOTHING;