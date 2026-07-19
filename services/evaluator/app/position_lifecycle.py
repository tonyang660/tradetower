from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import get_conn

POSITION_LIFECYCLE_VERSION = "phase7_step3_position_lifecycle_reconstruction"


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _position_row_to_dict(row) -> dict[str, Any]:
    return {
        "position_id": int(row[0]),
        "account_id": int(row[1]),
        "symbol": row[2],
        "side": row[3],
        "size": _to_float(row[4]),
        "original_size": _to_float(row[5]),
        "remaining_size": _to_float(row[6]),
        "entry_price": _to_float(row[7]),
        "leverage": _to_float(row[8]),
        "margin_used": _to_float(row[9]),
        "stop_loss": _to_float(row[10], None),
        "take_profit": _to_float(row[11], None),
        "risk_amount": _to_float(row[12]),
        "tp1_price": _to_float(row[13], None),
        "tp2_price": _to_float(row[14], None),
        "tp3_price": _to_float(row[15], None),
        "tp1_hit": bool(row[16]),
        "tp2_hit": bool(row[17]),
        "tp3_hit": bool(row[18]),
        "opened_at": _iso(row[19]),
        "closed_at": _iso(row[20]),
        "status": row[21],
    }


def _event_row_to_dict(row) -> dict[str, Any]:
    return {
        "position_event_id": int(row[0]),
        "position_id": int(row[1]),
        "account_id": int(row[2]),
        "order_id": int(row[3]) if row[3] is not None else None,
        "execution_id": int(row[4]) if row[4] is not None else None,
        "event_type": row[5],
        "event_timestamp": _iso(row[6]),
        "price": _to_float(row[7], None),
        "size_before": _to_float(row[8], None),
        "size_delta": _to_float(row[9], None),
        "size_after": _to_float(row[10], None),
        "details": row[11] or {},
        "created_at": _iso(row[12]),
    }


def _execution_row_to_dict(row) -> dict[str, Any]:
    return {
        "execution_id": int(row[0]),
        "account_id": int(row[1]),
        "order_id": int(row[2]) if row[2] is not None else None,
        "symbol": row[3],
        "side": row[4],
        "execution_type": row[5],
        "fill_price": _to_float(row[6], None),
        "filled_size": _to_float(row[7], None),
        "fee_paid": _to_float(row[8], None),
        "slippage_bps": _to_float(row[9], None),
        "executed_at": _iso(row[10]),
        "details": row[11] or {},
    }


def _management_event_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "event_family": row[1],
        "event_type": row[2],
        "event_time": _iso(row[3]),
        "account_id": int(row[4]) if row[4] is not None else None,
        "symbol": row[5],
        "position_id": row[6],
        "order_id": row[7],
        "cycle_id": row[8],
        "payload": row[9] or {},
    }


def fetch_position(account_id: int, position_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT
                    position_id, account_id, symbol, side, size, original_size,
                    remaining_size, entry_price, leverage, margin_used,
                    stop_loss, take_profit, risk_amount, tp1_price, tp2_price,
                    tp3_price, tp1_hit, tp2_hit, tp3_hit, opened_at, closed_at,
                    status
                FROM positions
                WHERE account_id = %s
                  AND position_id = %s
                ''',
                (account_id, position_id),
            )
            row = cur.fetchone()

    return _position_row_to_dict(row) if row else None


def fetch_recent_positions_for_lifecycle(account_id: int, limit: int = 25) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT
                    position_id, account_id, symbol, side, size, original_size,
                    remaining_size, entry_price, leverage, margin_used,
                    stop_loss, take_profit, risk_amount, tp1_price, tp2_price,
                    tp3_price, tp1_hit, tp2_hit, tp3_hit, opened_at, closed_at,
                    status
                FROM positions
                WHERE account_id = %s
                ORDER BY COALESCE(closed_at, opened_at) DESC
                LIMIT %s
                ''',
                (account_id, limit),
            )
            rows = cur.fetchall()

    return [_position_row_to_dict(row) for row in rows]


def fetch_position_events(account_id: int, position_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT
                    position_event_id, position_id, account_id, order_id,
                    execution_id, event_type, event_timestamp, price, size_before,
                    size_delta, size_after, details_json, created_at
                FROM position_events
                WHERE account_id = %s
                  AND position_id = %s
                ORDER BY event_timestamp ASC, position_event_id ASC
                ''',
                (account_id, position_id),
            )
            rows = cur.fetchall()

    return [_event_row_to_dict(row) for row in rows]


def fetch_position_executions(account_id: int, position: dict[str, Any]) -> list[dict[str, Any]]:
    position_id = int(position["position_id"])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'execution_reports'
                """
            )
            columns = {str(row[0]) for row in cur.fetchall()}

            side_expr = (
                "er.side"
                if "side" in columns
                else "er.position_side"
                if "position_side" in columns
                else "NULL::text"
            )

            executed_at_expr = (
                "er.executed_at"
                if "executed_at" in columns
                else "er.execution_timestamp"
                if "execution_timestamp" in columns
                else "NULL::timestamptz"
            )

            details_expr = (
                "er.details_json"
                if "details_json" in columns
                else "jsonb_build_object('notes', er.notes)"
                if "notes" in columns
                else "NULL::jsonb"
            )

            # Prefer the normalized lifecycle link through position_events.
            # This works with the deployed execution_reports schema, which has no details_json.
            cur.execute(
                f"""
                WITH matched_executions AS (
                    SELECT DISTINCT execution_id
                    FROM position_events
                    WHERE account_id = %s
                      AND position_id = %s
                      AND execution_id IS NOT NULL
                )
                SELECT
                    er.execution_id,
                    er.account_id,
                    er.order_id,
                    er.symbol,
                    {side_expr} AS side,
                    er.execution_type,
                    er.fill_price,
                    er.filled_size,
                    er.fee_paid,
                    er.slippage_bps,
                    {executed_at_expr} AS executed_at,
                    {details_expr} AS details_json
                FROM execution_reports er
                JOIN matched_executions me
                  ON me.execution_id = er.execution_id
                WHERE er.account_id = %s
                ORDER BY executed_at ASC NULLS LAST, er.execution_id ASC
                """,
                (account_id, position_id, account_id),
            )
            rows = cur.fetchall()

    return [_execution_row_to_dict(row) for row in rows]

def fetch_position_management_events(account_id: int, position_id: int, symbol: str) -> list[dict[str, Any]]:
    position_id_text = str(position_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT
                    id, event_family, event_type, event_time, account_id, symbol,
                    position_id, order_id, cycle_id, payload_json
                FROM evaluator_events
                WHERE account_id = %s
                  AND event_family = 'position_management'
                  AND (
                        position_id = %s
                     OR payload_json->'raw_result'->>'position_id' = %s
                     OR payload_json->'decision'->>'position_id' = %s
                     OR symbol = %s
                  )
                ORDER BY event_time ASC, id ASC
                ''',
                (account_id, position_id_text, position_id_text, position_id_text, symbol),
            )
            rows = cur.fetchall()

    return [_management_event_row_to_dict(row) for row in rows]


def classify_position_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", "")).upper()

    if event_type in ("POSITION_OPENED", "ENTRY_FILLED"):
        return "entry"
    if event_type in ("TP1_HIT", "TP1_FILLED"):
        return "tp1"
    if event_type in ("TP2_HIT", "TP2_FILLED"):
        return "tp2"
    if event_type in ("TP3_HIT", "TP3_FILLED"):
        return "tp3"
    if event_type in ("STOP_LOSS_HIT", "STOP_LOSS_FILLED", "SL_HIT"):
        return "stop_loss"
    if event_type in ("POSITION_CLOSED",):
        return "close"
    if "STOP" in event_type and ("REPRICE" in event_type or "UPDATED" in event_type):
        return "stop_management"

    return "other"


def build_tp_summary(position: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    events_by_kind = defaultdict(list)
    for event in events:
        events_by_kind[classify_position_event(event)].append(event)

    return {
        "tp1": {"hit": bool(position.get("tp1_hit")), "price": position.get("tp1_price"), "events": events_by_kind.get("tp1", [])},
        "tp2": {"hit": bool(position.get("tp2_hit")), "price": position.get("tp2_price"), "events": events_by_kind.get("tp2", [])},
        "tp3": {"hit": bool(position.get("tp3_hit")), "price": position.get("tp3_price"), "events": events_by_kind.get("tp3", [])},
    }


def build_lifecycle_timeline(
    *,
    position_events: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    management_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timeline = []

    for event in position_events:
        timeline.append({
            "time": event.get("event_timestamp"),
            "source": "position_events",
            "kind": classify_position_event(event),
            "label": event.get("event_type"),
            "payload": event,
        })

    for execution in executions:
        timeline.append({
            "time": execution.get("executed_at"),
            "source": "execution_reports",
            "kind": str(execution.get("execution_type", "")).lower(),
            "label": execution.get("execution_type"),
            "payload": execution,
        })

    for event in management_events:
        payload = event.get("payload") or {}
        timeline.append({
            "time": event.get("event_time"),
            "source": "evaluator_events",
            "kind": "position_management",
            "label": event.get("event_type"),
            "payload": {
                **event,
                "module": payload.get("module"),
                "action": payload.get("action"),
                "reason_code": payload.get("reason_code"),
                "old_stop": payload.get("old_stop"),
                "new_stop": payload.get("new_stop"),
                "proposed_stop": payload.get("proposed_stop"),
            },
        })

    return sorted(timeline, key=lambda item: (item.get("time") or "", item.get("source") or ""))


def infer_exit_path(position: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    classifications = [classify_position_event(event) for event in events]
    if "stop_loss" in classifications:
        reason = "stop_loss"
    elif bool(position.get("tp3_hit")) or "tp3" in classifications:
        reason = "tp3"
    elif str(position.get("status")) == "closed":
        reason = "closed_unknown"
    else:
        reason = "open"

    return {
        "exit_reason": reason,
        "is_open": str(position.get("status")) == "open",
        "is_closed": str(position.get("status")) == "closed",
        "tp_sequence": [
            level for level in ("tp1", "tp2", "tp3")
            if bool(position.get(f"{level}_hit")) or level in classifications
        ],
        "stop_loss_hit": "stop_loss" in classifications,
    }


def build_position_lifecycle(account_id: int, position_id: int) -> dict[str, Any]:
    position = fetch_position(account_id, position_id)
    if position is None:
        return {
            "ok": False,
            "error": "position_not_found",
            "account_id": account_id,
            "position_id": position_id,
        }

    events = fetch_position_events(account_id, position_id)
    executions = fetch_position_executions(account_id, position)
    management_events = fetch_position_management_events(account_id, position_id, position["symbol"])
    timeline = build_lifecycle_timeline(
        position_events=events,
        executions=executions,
        management_events=management_events,
    )

    return {
        "ok": True,
        "position_lifecycle_version": POSITION_LIFECYCLE_VERSION,
        "account_id": account_id,
        "position_id": position_id,
        "symbol": position["symbol"],
        "position": position,
        "exit_path": infer_exit_path(position, events),
        "tp_summary": build_tp_summary(position, events),
        "position_events": events,
        "executions": executions,
        "position_management_events": management_events,
        "timeline": timeline,
        "counts": {
            "position_events": len(events),
            "executions": len(executions),
            "position_management_events": len(management_events),
            "timeline": len(timeline),
        },
    }


def build_recent_position_lifecycles(account_id: int, limit: int = 10) -> dict[str, Any]:
    positions = fetch_recent_positions_for_lifecycle(account_id, limit)
    items = [build_position_lifecycle(account_id, int(position["position_id"])) for position in positions]
    return {
        "ok": True,
        "position_lifecycle_version": POSITION_LIFECYCLE_VERSION,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
