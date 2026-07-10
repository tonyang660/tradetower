-- 006_persistent_order_lifecycle.sql
--
-- Expands the existing orders table into the persistent order lifecycle used
-- by both paper execution and future live exchange execution.
--
-- This migration also converts legacy status values:
--   planned   -> created
--   submitted -> open
--
-- Existing filled/cancelled/rejected values remain unchanged.

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS exchange TEXT,
ADD COLUMN IF NOT EXISTS client_order_id TEXT,
ADD COLUMN IF NOT EXISTS exchange_order_id TEXT,
ADD COLUMN IF NOT EXISTS position_side TEXT,
ADD COLUMN IF NOT EXISTS filled_size NUMERIC(18,8) NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS remaining_size NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS average_fill_price NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS post_only BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS exchange_status TEXT,
ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_reconciled_at TIMESTAMPTZ;

UPDATE orders
SET status = 'created'
WHERE status = 'planned';

UPDATE orders
SET status = 'open'
WHERE status = 'submitted';

UPDATE orders
SET remaining_size = GREATEST(requested_size - filled_size, 0)
WHERE remaining_size IS NULL;

UPDATE orders
SET submitted_at = created_at
WHERE status IN (
    'submitted',
    'acknowledged',
    'open',
    'partially_filled',
    'filled',
    'cancel_pending',
    'cancelled'
)
AND submitted_at IS NULL;

UPDATE orders
SET filled_at = updated_at
WHERE status = 'filled'
  AND filled_at IS NULL;

UPDATE orders
SET cancelled_at = updated_at
WHERE status = 'cancelled'
  AND cancelled_at IS NULL;

ALTER TABLE orders
DROP CONSTRAINT IF EXISTS orders_status_check;

ALTER TABLE orders
ADD CONSTRAINT orders_status_check
CHECK (
    status IN (
        'created',
        'submitted',
        'acknowledged',
        'open',
        'partially_filled',
        'filled',
        'cancel_pending',
        'cancelled',
        'rejected',
        'expired'
    )
);

ALTER TABLE orders
DROP CONSTRAINT IF EXISTS orders_position_side_check;

ALTER TABLE orders
ADD CONSTRAINT orders_position_side_check
CHECK (
    position_side IS NULL
    OR position_side IN ('long', 'short')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_account_client_order_id
ON orders(account_id, client_order_id)
WHERE client_order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_exchange_order_id
ON orders(exchange, exchange_order_id)
WHERE exchange IS NOT NULL
  AND exchange_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_orders_account_status
ON orders(account_id, status);

CREATE INDEX IF NOT EXISTS idx_orders_active_entry
ON orders(account_id, symbol, role, status);

CREATE INDEX IF NOT EXISTS idx_orders_linked_position_status
ON orders(linked_position_id, status)
WHERE linked_position_id IS NOT NULL;
