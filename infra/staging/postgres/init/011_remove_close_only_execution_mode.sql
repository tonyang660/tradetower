-- 011_remove_close_only_execution_mode.sql
--
-- Removes close_only from execution_mode.
--
-- Existing live accounts in close_only are migrated to:
--   execution_mode = live
--   manual_halt = true
--
-- This preserves the previous safety behavior:
--   no new entries, while maintenance/reduction/close remain allowed.

UPDATE guardian_state gs
SET manual_halt = TRUE,
    updated_at = NOW()
FROM accounts a
WHERE a.account_id = gs.account_id
  AND a.account_type = 'live'
  AND a.execution_mode = 'close_only';

INSERT INTO guardian_events (
    account_id,
    event_type,
    reason_code,
    details_json,
    created_at
)
SELECT
    a.account_id,
    'MANUAL_HALT_UPDATED',
    'CLOSE_ONLY_MODE_MIGRATED',
    '{"enabled": true, "source": "execution_mode_cleanup"}'::jsonb,
    NOW()
FROM accounts a
WHERE a.account_type = 'live'
  AND a.execution_mode = 'close_only';

UPDATE accounts
SET execution_mode = 'live'
WHERE account_type = 'live'
  AND execution_mode = 'close_only';

ALTER TABLE accounts
DROP CONSTRAINT IF EXISTS accounts_type_execution_mode_check;

ALTER TABLE accounts
DROP CONSTRAINT IF EXISTS accounts_execution_mode_check;

ALTER TABLE accounts
ADD CONSTRAINT accounts_execution_mode_check
CHECK (execution_mode IN ('paper', 'shadow', 'live'));

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
