-- 009_consecutive_loss_circuit_breaker.sql
--
-- Adds an account-wide consecutive-loss circuit breaker to Trade Guardian.
--
-- A completed losing position increments the streak.
-- Any completed non-losing position resets the streak to zero.
-- Reaching the configured threshold activates a fixed cooldown.

ALTER TABLE guardian_state
ADD COLUMN IF NOT EXISTS consecutive_losses INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS consecutive_loss_cooldown_until TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS max_consecutive_losses INTEGER NOT NULL DEFAULT 3,
ADD COLUMN IF NOT EXISTS consecutive_loss_cooldown_hours INTEGER NOT NULL DEFAULT 4;

ALTER TABLE guardian_state
DROP CONSTRAINT IF EXISTS guardian_state_consecutive_losses_check;

ALTER TABLE guardian_state
ADD CONSTRAINT guardian_state_consecutive_losses_check
CHECK (consecutive_losses >= 0);

ALTER TABLE guardian_state
DROP CONSTRAINT IF EXISTS guardian_state_max_consecutive_losses_check;

ALTER TABLE guardian_state
ADD CONSTRAINT guardian_state_max_consecutive_losses_check
CHECK (max_consecutive_losses > 0);

ALTER TABLE guardian_state
DROP CONSTRAINT IF EXISTS guardian_state_consecutive_loss_cooldown_hours_check;

ALTER TABLE guardian_state
ADD CONSTRAINT guardian_state_consecutive_loss_cooldown_hours_check
CHECK (consecutive_loss_cooldown_hours > 0);

-- Link new completed trades to the position that generated them.
-- Existing historical trades may remain NULL.
ALTER TABLE trades
ADD COLUMN IF NOT EXISTS position_id INTEGER REFERENCES positions(position_id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_trades_position_id
ON trades(position_id)
WHERE position_id IS NOT NULL;
