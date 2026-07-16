from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import get_conn

STOP_MANAGEMENT_ANALYTICS_VERSION = "phase7_step5_stop_management_analytics"


STOP_REPRICE_EVENT_TYPES = {
    "adaptive_stop_repriced",
    "near_tp_stop_repriced",
    "regime_change_stop_repriced",
}

STOP_EVALUATION_EVENT_TYPES = {
    "adaptive_stop_evaluated",
    "near_tp_reversal_evaluated",
    "regime_change_stop_evaluated",
    "position_management_noop",
    "position_management_error",
}

MODULE_LABELS = {
    "adaptive_stop": "Adaptive stop",
    "near_tp_reversal": "Near-TP reversal",
    "regime_change_stop": "Regime-change stop",
}


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


def _event_row_to_dict(row) -> dict[str, Any]:
    payload = row[10] or {}
    raw_result = payload.get("raw_result") or {}
    decision = payload.get("decision") or {}

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
        "source_version": row[9],
        "payload": payload,
        "module": payload.get("module"),
        "module_label": MODULE_LABELS.get(payload.get("module"), payload.get("module")),
        "action": payload.get("action"),
        "reason_code": payload.get("reason_code"),
        "management_key": payload.get("management_key"),
        "is_noop": bool(payload.get("is_noop", False)),
        "old_stop": _to_float(payload.get("old_stop"), None),
        "new_stop": _to_float(payload.get("new_stop"), None),
        "proposed_stop": _to_float(payload.get("proposed_stop"), None),
        "raw_result": raw_result,
        "decision": decision,
    }


def fetch_stop_management_events(account_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            id,
            event_family,
            event_type,
            event_time,
            account_id,
            symbol,
            position_id,
            order_id,
            cycle_id,
            source_version,
            payload_json
        FROM evaluator_events
        WHERE account_id = %s
          AND event_family = 'position_management'
        ORDER BY event_time DESC, id DESC
    """
    params: list[Any] = [account_id]

    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [_event_row_to_dict(row) for row in rows]


def _stop_improvement(event: dict[str, Any]) -> float | None:
    old_stop = event.get("old_stop")
    new_stop = event.get("new_stop")
    if old_stop is None or new_stop is None:
        return None
    return abs(float(new_stop) - float(old_stop))


def _is_reprice(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    action = str(event.get("action") or "").upper()
    return event_type in STOP_REPRICE_EVENT_TYPES or "REPRICE" in action or "STOP_REPRICED" in action


def summarize_stop_management_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(events)
    reprice_events = [event for event in events if _is_reprice(event)]
    noop_events = [event for event in events if bool(event.get("is_noop")) or event.get("event_type") == "position_management_noop"]
    error_events = [event for event in events if event.get("event_type") == "position_management_error"]

    by_module: dict[str, dict[str, Any]] = {}
    grouped_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped_by_module[str(event.get("module") or "unknown")].append(event)

    for module, module_events in grouped_by_module.items():
        module_reprices = [event for event in module_events if _is_reprice(event)]
        module_noops = [
            event for event in module_events
            if bool(event.get("is_noop")) or event.get("event_type") == "position_management_noop"
        ]
        module_errors = [event for event in module_events if event.get("event_type") == "position_management_error"]
        improvements = [_stop_improvement(event) for event in module_reprices]
        improvements = [value for value in improvements if value is not None]

        by_module[module] = {
            "module": module,
            "label": MODULE_LABELS.get(module, module),
            "events": len(module_events),
            "reprices": len(module_reprices),
            "noops": len(module_noops),
            "errors": len(module_errors),
            "average_stop_improvement": round(sum(improvements) / len(improvements), 8) if improvements else None,
            "total_stop_improvement": round(sum(improvements), 8) if improvements else 0.0,
        }

    by_reason: dict[str, int] = defaultdict(int)
    by_symbol: dict[str, dict[str, Any]] = {}
    grouped_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in events:
        by_reason[str(event.get("reason_code") or "unknown")] += 1
        grouped_by_symbol[str(event.get("symbol") or "unknown")].append(event)

    for symbol, symbol_events in grouped_by_symbol.items():
        symbol_reprices = [event for event in symbol_events if _is_reprice(event)]
        symbol_errors = [event for event in symbol_events if event.get("event_type") == "position_management_error"]
        by_symbol[symbol] = {
            "symbol": symbol,
            "events": len(symbol_events),
            "reprices": len(symbol_reprices),
            "errors": len(symbol_errors),
            "last_event_time": symbol_events[0].get("event_time") if symbol_events else None,
        }

    improvements = [_stop_improvement(event) for event in reprice_events]
    improvements = [value for value in improvements if value is not None]

    return {
        "events": total,
        "reprices": len(reprice_events),
        "noops": len(noop_events),
        "errors": len(error_events),
        "reprice_rate": round((len(reprice_events) / total * 100.0), 4) if total else 0.0,
        "noop_rate": round((len(noop_events) / total * 100.0), 4) if total else 0.0,
        "average_stop_improvement": round(sum(improvements) / len(improvements), 8) if improvements else None,
        "total_stop_improvement": round(sum(improvements), 8) if improvements else 0.0,
        "by_module": by_module,
        "by_reason": dict(by_reason),
        "by_symbol": by_symbol,
    }


def get_stop_management_analytics(account_id: int, limit: int | None = None) -> dict[str, Any]:
    events = fetch_stop_management_events(account_id, limit)
    return {
        "ok": True,
        "stop_management_analytics_version": STOP_MANAGEMENT_ANALYTICS_VERSION,
        "account_id": account_id,
        "count": len(events),
        "summary": summarize_stop_management_events(events),
        "items": events,
        "pnl_note": {
            "realized_pnl": "Performance V2 should treat realized PnL as net after actual fees.",
            "unrealized_pnl": "Performance V2 should keep unrealized PnL as live gross mark/last PnL with no estimated fees subtracted.",
            "cost_breakdown": "Fees, slippage, spread and later funding should remain visible as separate fields.",
        },
    }


def get_stop_management_summary(account_id: int, limit: int | None = None) -> dict[str, Any]:
    analytics = get_stop_management_analytics(account_id, limit)
    return {
        "ok": True,
        "stop_management_analytics_version": STOP_MANAGEMENT_ANALYTICS_VERSION,
        "account_id": account_id,
        "summary": analytics["summary"],
        "pnl_note": analytics["pnl_note"],
    }
