CREATE TABLE IF NOT EXISTS evaluator_equity_history (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    cash_balance NUMERIC(18,8) NOT NULL,
    equity NUMERIC(18,8) NOT NULL,
    realized_pnl NUMERIC(18,8) NOT NULL,
    unrealized_pnl NUMERIC(18,8) NOT NULL,
    fees_paid_total NUMERIC(18,8) NOT NULL,
    trading_enabled BOOLEAN NOT NULL,
    manual_halt BOOLEAN NOT NULL,
    daily_kill_switch BOOLEAN NOT NULL,
    weekly_kill_switch BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluator_equity_history_account_time
ON evaluator_equity_history (account_id, recorded_at DESC);


CREATE TABLE IF NOT EXISTS evaluator_cycle_history (
    cycle_id TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    entry_gate_allowed BOOLEAN,
    enabled_symbols_json JSONB NOT NULL,
    entry_eligible_symbols_json JSONB NOT NULL,
    summary_json JSONB NOT NULL
);


CREATE TABLE IF NOT EXISTS evaluator_decision_history (
    id BIGSERIAL PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,

    candidate_score NUMERIC(10,4),
    candidate_bias TEXT,
    candidate_reasons_json JSONB,
    candidate_sub_scores_json JSONB,

    strategy_regime TEXT,
    strategy_macro_bias TEXT,
    strategy_setup_confidence NUMERIC(10,4),
    strategy_decision_confidence NUMERIC(10,4),
    best_strategy_candidate TEXT,
    best_strategy_score NUMERIC(10,4),
    strategy_reason_tags_json JSONB,

    final_decision TEXT,
    risk_approved BOOLEAN,
    guardian_allowed BOOLEAN,
    paper_submitted BOOLEAN,
    filled BOOLEAN,

    UNIQUE (cycle_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_evaluator_decision_history_cycle
ON evaluator_decision_history (cycle_id);

CREATE INDEX IF NOT EXISTS idx_evaluator_decision_history_account_symbol
ON evaluator_decision_history (account_id, symbol);


CREATE TABLE IF NOT EXISTS evaluator_trade_analytics (
    trade_id BIGINT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    strategy_name TEXT,
    regime TEXT,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    holding_minutes NUMERIC(12,2),
    entry_price NUMERIC(18,8),
    exit_price NUMERIC(18,8),
    size NUMERIC(18,8),
    notional NUMERIC(18,8),
    leverage NUMERIC(18,8),
    realized_pnl NUMERIC(18,8),
    pnl_pct NUMERIC(18,8),
    fees_paid NUMERIC(18,8),
    win_loss TEXT,
    tp_hits INTEGER DEFAULT 0,
    sl_hit BOOLEAN DEFAULT FALSE,
    exit_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_evaluator_trade_analytics_account_time
ON evaluator_trade_analytics (account_id, closed_at DESC);