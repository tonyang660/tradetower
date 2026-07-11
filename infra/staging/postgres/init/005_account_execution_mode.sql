-- 005_account_execution_mode.sql
--
-- Adds the account execution mode used to select the execution path.
--
-- account_type describes what kind of account is represented:
--   paper | live
--
-- execution_mode describes how TradeTower is currently allowed to execute:
--   paper | shadow | live
--
-- This migration does not implement shadow or live execution. It only makes
-- execution mode persistent and enforces valid account/mode combinations.

ALTER TABLE accounts
ADD COLUMN IF NOT EXISTS execution_mode TEXT;

UPDATE accounts
SET execution_mode = CASE
    WHEN account_type = 'paper' THEN 'paper'
    WHEN account_type = 'live' THEN 'shadow'
    ELSE execution_mode
END
WHERE execution_mode IS NULL;

ALTER TABLE accounts
ALTER COLUMN execution_mode SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'accounts_execution_mode_check'
          AND conrelid = 'accounts'::regclass
    ) THEN
        ALTER TABLE accounts
        ADD CONSTRAINT accounts_execution_mode_check
        CHECK (execution_mode IN ('paper', 'shadow', 'live'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'accounts_type_execution_mode_check'
          AND conrelid = 'accounts'::regclass
    ) THEN
        ALTER TABLE accounts
        ADD CONSTRAINT accounts_type_execution_mode_check
        CHECK (
            (account_type = 'paper' AND execution_mode = 'paper')
            OR
            (
                account_type = 'live'
                AND execution_mode IN ('shadow', 'live')
            )
        );
    END IF;
END
$$;
