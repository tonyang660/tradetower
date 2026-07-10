-- 007_persistent_pending_entries.sql
--
-- Makes PostgreSQL the source of truth for pending paper entry retries.

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS execution_context JSONB,
ADD COLUMN IF NOT EXISTS retry_attempt INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS max_retry_attempts INTEGER,
ADD COLUMN IF NOT EXISTS originating_cycle_id TEXT;

ALTER TABLE orders
DROP CONSTRAINT IF EXISTS orders_retry_attempt_check;

ALTER TABLE orders
ADD CONSTRAINT orders_retry_attempt_check
CHECK (retry_attempt >= 0);

ALTER TABLE orders
DROP CONSTRAINT IF EXISTS orders_max_retry_attempts_check;

ALTER TABLE orders
ADD CONSTRAINT orders_max_retry_attempts_check
CHECK (
    max_retry_attempts IS NULL
    OR max_retry_attempts > 0
);

CREATE INDEX IF NOT EXISTS idx_orders_pending_entry_retry
ON orders(account_id, role, status, updated_at)
WHERE role = 'entry'
  AND status IN (
      'created',
      'submitted',
      'acknowledged',
      'open',
      'partially_filled'
  );
