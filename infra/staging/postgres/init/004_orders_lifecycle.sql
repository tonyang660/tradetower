-- 004_orders_lifecycle.sql
--
-- Reconciles the checked-in PostgreSQL init migrations with the actual
-- TradeTower schema currently used by trade-guardian.
--
-- This migration is intentionally limited to fields and constraints already
-- present in the exported running database. It does not introduce new v2
-- domain fields.

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'entry',
ADD COLUMN IF NOT EXISTS stop_loss NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp1 NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp2 NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp3 NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS linked_position_id INTEGER,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'orders_role_check'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
        ADD CONSTRAINT orders_role_check
        CHECK (
            role IN (
                'entry',
                'protective_bundle',
                'stop_loss',
                'take_profit',
                'tp1',
                'tp2',
                'tp3'
            )
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'orders_linked_position_id_fkey'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
        ADD CONSTRAINT orders_linked_position_id_fkey
        FOREIGN KEY (linked_position_id)
        REFERENCES positions(position_id)
        ON DELETE SET NULL;
    END IF;
END
$$;
