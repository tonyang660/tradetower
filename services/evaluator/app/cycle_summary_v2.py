from __future__ import annotations

from typing import Any

from event_contracts import EVALUATOR_EVENT_MODEL_VERSION
from time_utils import iso_now, parse_ts

CYCLE_SUMMARY_INGESTION_VERSION = "phase7_step2_cycle_summary_ingestion_v2"


def _account_id(payload: dict[str, Any]) -> int:
    entry_gate = payload.get("entry_gate") or {}
    if entry_gate.get("account_id") is not None:
        return int(entry_gate["account_id"])

    position_management = payload.get("position_management") or {}
    for item in position_management.get("results", []):
        raw_payload = item.get("payload") or {}
        if raw_payload.get("account_id") is not None:
            return int(raw_payload["account_id"])

    return 1


def _base_event(
    *,
    payload: dict[str, Any],
    event_family: str,
    event_type: str,
    account_id: int,
    symbol: str | None = None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_version": EVALUATOR_EVENT_MODEL_VERSION,
        "event_family": event_family,
        "event_type": event_type,
        "event_time": parse_ts(payload.get("completed_at") or payload.get("started_at")),
        "ingested_at": parse_ts(iso_now()),
        "account_id": account_id,
        "symbol": symbol.upper() if symbol else None,
        "position_id": None,
        "order_id": None,
        "cycle_id": payload.get("cycle_id"),
        "source_service": "scheduler",
        "source_version": payload.get("scheduler_version") or payload.get("runtime_version"),
        "strategy_name": None,
        "strategy_side": None,
        "regime": None,
        "execution_mode": payload.get("execution_mode"),
        "payload": event_payload or {},
    }


def _position_management_event_type(module: str | None, action: str | None, ok: bool) -> str:
    module = str(module or "").lower()
    action = str(action or "").upper()

    if not ok:
        return "position_management_error"

    if action in ("NO_ACTION", "NO_STOP_REPRICE", ""):
        return "position_management_noop"

    if module == "adaptive_stop":
        if "REPRICE" in action or "STOP_REPRICED" in action:
            return "adaptive_stop_repriced"
        return "adaptive_stop_evaluated"

    if module == "near_tp_reversal":
        if "REPRICE" in action or "STOP_REPRICED" in action:
            return "near_tp_stop_repriced"
        return "near_tp_reversal_evaluated"

    if module == "regime_change_stop":
        if "REPRICE" in action or "STOP_REPRICED" in action:
            return "regime_change_stop_repriced"
        return "regime_change_stop_evaluated"

    return "position_management_noop"


def normalize_position_management_events(payload: dict[str, Any], account_id: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    position_management = payload.get("position_management") or {}

    if not isinstance(position_management, dict):
        return events

    events.append(_base_event(
        payload=payload,
        event_family="cycle",
        event_type="position_management_completed",
        account_id=account_id,
        event_payload={
            "cycle_summary_ingestion_version": CYCLE_SUMMARY_INGESTION_VERSION,
            "checked": position_management.get("checked", 0),
            "actions_triggered": position_management.get("actions_triggered", 0),
            "no_action": position_management.get("no_action", 0),
            "errors": position_management.get("errors", 0),
            "skipped": position_management.get("skipped", 0),
            "compatibility_version": position_management.get("compatibility_version"),
            "scheduler_position_management_version": position_management.get("scheduler_position_management_version"),
        },
    ))

    for position_result in position_management.get("results", []):
        symbol = position_result.get("symbol")
        raw_result = position_result.get("result") or {}
        manager_results = raw_result.get("results", [])

        if not isinstance(manager_results, list):
            continue

        for module_result in manager_results:
            raw = module_result.get("raw_result") or {}
            decision = raw.get("decision") or {}
            module = module_result.get("module")
            action = module_result.get("action")
            ok = bool(module_result.get("ok", False))
            event_type = _position_management_event_type(module, action, ok)

            event_payload = {
                "cycle_summary_ingestion_version": CYCLE_SUMMARY_INGESTION_VERSION,
                "module": module,
                "action": action,
                "reason_code": module_result.get("reason_code"),
                "management_key": module_result.get("management_key"),
                "is_noop": module_result.get("is_noop"),
                "old_stop": module_result.get("old_stop"),
                "new_stop": module_result.get("new_stop"),
                "proposed_stop": module_result.get("proposed_stop"),
                "raw_result": raw,
                "decision": decision,
                "position_result": position_result,
            }

            event = _base_event(
                payload=payload,
                event_family="position_management",
                event_type=event_type,
                account_id=account_id,
                symbol=symbol,
                event_payload=event_payload,
            )
            event["position_id"] = raw.get("position_id") or decision.get("position_id")
            event["order_id"] = raw.get("stop_order_id") or decision.get("stop_order_id")
            events.append(event)

    return events


def normalize_cycle_summary_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    account_id = _account_id(payload)

    events = [
        _base_event(
            payload=payload,
            event_family="cycle",
            event_type="cycle_completed" if payload.get("completed_at") else "cycle_started",
            account_id=account_id,
            event_payload={
                "cycle_summary_ingestion_version": CYCLE_SUMMARY_INGESTION_VERSION,
                "ok": payload.get("ok"),
                "started_at": payload.get("started_at"),
                "completed_at": payload.get("completed_at"),
                "errors": payload.get("errors", []),
                "enabled_symbols_count": len(payload.get("enabled_symbols", [])),
                "open_positions_count": payload.get("open_positions_count"),
                "pending_entries_before_cycle": payload.get("pending_entries_before_cycle"),
                "pending_entries_after_cycle": payload.get("pending_entries_after_cycle"),
            },
        )
    ]

    events.extend(normalize_position_management_events(payload, account_id))
    return events
