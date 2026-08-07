from __future__ import annotations

import json
import threading
from typing import Any

from db import get_conn

PHASE18_POSITION_LIFECYCLE_LEDGER_VERSION = "phase18m_position_lifecycle_ledger_v1"
_POSITION_LIFECYCLE_TABLE_READY = False
_POSITION_LIFECYCLE_TABLE_LOCK = threading.Lock()


def _json(value: Any) -> str:
    return json.dumps(value or {}, default=str)


def _empty_position_event_page(limit: int, offset: int, reason: str) -> dict[str, Any]:
    return {
        "rows": [],
        "total": 0,
        "count": 0,
        "limit": limit,
        "offset": offset,
        "has_more": False,
        "available": False,
        "reason": reason,
        "ledger_version": PHASE18_POSITION_LIFECYCLE_LEDGER_VERSION,
    }


def _position_lifecycle_table_exists(cur) -> bool:
    cur.execute("SELECT to_regclass('public.backtest_position_events')")
    row = cur.fetchone()
    return bool(row and row[0])


def ensure_position_lifecycle_table() -> None:
    global _POSITION_LIFECYCLE_TABLE_READY
    if _POSITION_LIFECYCLE_TABLE_READY:
        return

    with _POSITION_LIFECYCLE_TABLE_LOCK:
        if _POSITION_LIFECYCLE_TABLE_READY:
            return

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS backtest_position_events (
                    event_id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    position_id BIGINT,
                    symbol TEXT NOT NULL,
                    side TEXT,
                    event_type TEXT NOT NULL,
                    event_time TIMESTAMPTZ NOT NULL,
                    price NUMERIC,
                    quantity NUMERIC,
                    gross_pnl NUMERIC,
                    fee NUMERIC,
                    net_pnl NUMERIC,
                    remaining_size NUMERIC,
                    order_id BIGINT,
                    related_order_id BIGINT,
                    reason TEXT,
                    sequence_index BIGINT,
                    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                '''
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_position_events_run_position "
                "ON backtest_position_events(run_id, position_id, event_time, event_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_backtest_position_events_run_type "
                "ON backtest_position_events(run_id, event_type)"
            )
            conn.commit()
        _POSITION_LIFECYCLE_TABLE_READY = True


def lifecycle_ledger_contract() -> dict[str, Any]:
    return {
        "version": PHASE18_POSITION_LIFECYCLE_LEDGER_VERSION,
        "table": "backtest_position_events",
        "role": "position-level lifecycle event stream; TP/SL/SL2 rows are exit legs, not full trades",
        "event_types": [
            "POSITION_OPENED",
            "PROTECTIVE_ORDERS_CREATED",
            "TP1_FILLED",
            "TP2_FILLED",
            "TP3_FILLED",
            "STOP_LOSS_FILLED",
            "STOP_LIMIT_REPRICE_ATTEMPT",
            "REGIME_CHANGE_SL2_CREATED",
            "REGIME_CHANGE_SL2_FILLED",
            "VOLATILITY_SPIKE_SL2_CREATED",
            "VOLATILITY_SPIKE_SL2_FILLED",
            "ADAPTIVE_STOP_UPDATED",
            "POSITION_CLOSED",
            "END_OF_BACKTEST_CLOSED",
        ],
    }


def record_position_event(
    *,
    run_id: int,
    position: dict[str, Any],
    event_type: str,
    event_time,
    price: float | None = None,
    quantity: float | None = None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
    remaining_size: float | None = None,
    order_id: int | None = None,
    related_order_id: int | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    ensure_position_lifecycle_table()

    position_id = position.get("position_id")
    symbol = str(position.get("symbol") or "")
    side = str(position.get("side") or "")
    remaining = remaining_size
    if remaining is None and position.get("qty") is not None:
        remaining = float(position.get("qty") or 0.0)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            '''
            SELECT COALESCE(MAX(sequence_index), 0) + 1
            FROM backtest_position_events
            WHERE run_id = %s
              AND position_id IS NOT DISTINCT FROM %s
            ''',
            (run_id, position_id),
        )
        sequence_index = int(cur.fetchone()[0] or 1)

        cur.execute(
            '''
            INSERT INTO backtest_position_events(
                run_id, position_id, symbol, side, event_type, event_time,
                price, quantity, gross_pnl, fee, net_pnl, remaining_size,
                order_id, related_order_id, reason, sequence_index, details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING event_id
            ''',
            (
                run_id,
                position_id,
                symbol,
                side,
                event_type,
                event_time,
                price,
                quantity,
                gross_pnl,
                fee,
                net_pnl,
                remaining,
                order_id,
                related_order_id,
                reason,
                sequence_index,
                _json(
                    {
                        "ledger_version": PHASE18_POSITION_LIFECYCLE_LEDGER_VERSION,
                        **(details or {}),
                    }
                ),
            ),
        )
        event_id = int(cur.fetchone()[0])
        conn.commit()
        return event_id


def fetch_position_events(run_id: int, limit: int = 1000, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))

    with get_conn() as conn, conn.cursor() as cur:
        if not _position_lifecycle_table_exists(cur):
            return _empty_position_event_page(
                limit,
                offset,
                "position_lifecycle_table_missing",
            )

        cur.execute("SELECT COUNT(*) FROM backtest_position_events WHERE run_id=%s", (run_id,))
        total = int(cur.fetchone()[0] or 0)
        cur.execute(
            '''
            SELECT row_to_json(e)
            FROM backtest_position_events e
            WHERE run_id=%s
            ORDER BY position_id NULLS LAST, sequence_index, event_id
            LIMIT %s OFFSET %s
            ''',
            (run_id, limit, offset),
        )
        rows = [row[0] for row in cur.fetchall()]

    return {
        "rows": rows,
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "available": True,
        "reason": None,
        "ledger_version": PHASE18_POSITION_LIFECYCLE_LEDGER_VERSION,
    }
