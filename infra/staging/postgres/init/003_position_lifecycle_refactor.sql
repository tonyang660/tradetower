ALTER TABLE positions
ADD COLUMN IF NOT EXISTS original_size NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS remaining_size NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS risk_amount NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp1_price NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp2_price NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp3_price NUMERIC(18,8),
ADD COLUMN IF NOT EXISTS tp1_hit BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS tp2_hit BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS tp3_hit BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE positions
SET original_size = size
WHERE original_size IS NULL;

UPDATE positions
SET remaining_size = size
WHERE remaining_size IS NULL;

UPDATE positions
SET risk_amount = 0
WHERE risk_amount IS NULL;

ALTER TABLE execution_reports
ADD COLUMN IF NOT EXISTS execution_type TEXT,
ADD COLUMN IF NOT EXISTS position_side TEXT;

UPDATE execution_reports
SET execution_type = 'ENTRY'
WHERE execution_type IS NULL;

UPDATE execution_reports
SET position_side = 'long'
WHERE position_side IS NULL;
