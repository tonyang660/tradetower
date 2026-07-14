# Schema Inventory

## Active schemas

```text
candidate_filter_v2.schema.json
market_snapshot_v2.schema.json
strategy_signal_v2.schema.json
risk_approval_payload_v2.schema.json
```

## Deprecated schemas

```text
risk_approval_v2.schema.json
```

`risk_approval_v2.schema.json` was the early Phase 5 Step 1-2 contract for a
future Risk Engine v2 approval shape.

It has been superseded by:

```text
risk_approval_payload_v2.schema.json
```

The replacement should be used by Scheduler, Paper Execution, Trade Guardian,
Evaluator, dashboard validation, and any future live execution path.

## Why the old file is not deleted yet

The old schema is left in place with explicit deprecation metadata so existing
references do not fail immediately during local development.

Delete it later only after a repo-wide search confirms no code, docs, tests, or
external scripts still reference it.
