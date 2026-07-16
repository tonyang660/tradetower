from __future__ import annotations

from typing import Any

from json_utils import json_dumps

EVALUATOR_EVENT_STORE_VERSION = "phase7_step2_evaluator_event_store"


def ensure_evaluator_events_table(cur) -> None:
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS evaluator_events (
            id BIGSERIAL PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            event_version TEXT NOT NULL,
            event_family TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_time TIMESTAMPTZ,
            ingested_at TIMESTAMPTZ,
            account_id INTEGER,
            symbol TEXT,
            position_id TEXT,
            order_id TEXT,
            cycle_id TEXT,
            source_service TEXT,
            source_version TEXT,
            strategy_name TEXT,
            strategy_side TEXT,
            regime TEXT,
            execution_mode TEXT,
            payload_json JSONB NOT NULL
        )
        '''
    )
    cur.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_evaluator_events_account_time
        ON evaluator_events (account_id, event_time DESC)
        '''
    )
    cur.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_evaluator_events_family_type
        ON evaluator_events (event_family, event_type)
        '''
    )
    cur.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_evaluator_events_cycle
        ON evaluator_events (cycle_id)
        '''
    )
    cur.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_evaluator_events_symbol_time
        ON evaluator_events (symbol, event_time DESC)
        '''
    )


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def build_idempotency_key(event: dict[str, Any]) -> str:
    existing = event.get("idempotency_key")
    if existing:
        return str(existing)

    payload = event.get("payload", {})
    parts = [
        event.get("event_version"),
        event.get("event_family"),
        event.get("event_type"),
        event.get("cycle_id"),
        event.get("account_id"),
        event.get("symbol"),
        event.get("position_id"),
        event.get("order_id"),
        payload.get("module"),
        payload.get("management_key"),
        payload.get("action"),
    ]
    return "|".join(str(part) for part in parts if part is not None)


def upsert_evaluator_event(cur, event: dict[str, Any]) -> None:
    idempotency_key = build_idempotency_key(event)
    cur.execute(
        '''
        INSERT INTO evaluator_events (
            idempotency_key,
            event_version,
            event_family,
            event_type,
            event_time,
            ingested_at,
            account_id,
            symbol,
            position_id,
            order_id,
            cycle_id,
            source_service,
            source_version,
            strategy_name,
            strategy_side,
            regime,
            execution_mode,
            payload_json
        )
        VALUES (
            %(idempotency_key)s,
            %(event_version)s,
            %(event_family)s,
            %(event_type)s,
            %(event_time)s,
            %(ingested_at)s,
            %(account_id)s,
            %(symbol)s,
            %(position_id)s,
            %(order_id)s,
            %(cycle_id)s,
            %(source_service)s,
            %(source_version)s,
            %(strategy_name)s,
            %(strategy_side)s,
            %(regime)s,
            %(execution_mode)s,
            %(payload_json)s::jsonb
        )
        ON CONFLICT (idempotency_key)
        DO UPDATE SET
            event_time = EXCLUDED.event_time,
            ingested_at = EXCLUDED.ingested_at,
            source_version = EXCLUDED.source_version,
            payload_json = EXCLUDED.payload_json
        ''',
        {
            "idempotency_key": idempotency_key,
            "event_version": event["event_version"],
            "event_family": event["event_family"],
            "event_type": event["event_type"],
            "event_time": event.get("event_time"),
            "ingested_at": event.get("ingested_at"),
            "account_id": event.get("account_id"),
            "symbol": event.get("symbol"),
            "position_id": _text_or_none(event.get("position_id")),
            "order_id": _text_or_none(event.get("order_id")),
            "cycle_id": event.get("cycle_id"),
            "source_service": event.get("source_service"),
            "source_version": event.get("source_version"),
            "strategy_name": event.get("strategy_name"),
            "strategy_side": event.get("strategy_side"),
            "regime": event.get("regime"),
            "execution_mode": event.get("execution_mode"),
            "payload_json": json_dumps(event.get("payload", {})),
        },
    )


def store_evaluator_events(cur, events: list[dict[str, Any]]) -> int:
    ensure_evaluator_events_table(cur)
    for event in events:
        upsert_evaluator_event(cur, event)
    return len(events)
