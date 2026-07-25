"""
Phase 6 Step 1 — Paper Execution v2 contract and event model.

This module standardizes the paper execution report shape emitted by
paper-execution before it is sent to Trade Guardian.

It is intentionally execution-only:
- no strategy decisions
- no risk sizing
- no adaptive stop management
- no retry policy changes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PAPER_EXECUTION_VERSION = "paper_execution_v2"
PAPER_EXECUTION_REPORT_VERSION = "phase6_step1_paper_execution_report_v2"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_side(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    return "unknown"


def normalize_order_type(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("limit", "market"):
        return value
    return "limit"


def get_tp_close_percent(payload: dict[str, Any], key: str, default: float) -> float:
    direct_key = f"{key}_close_percent"

    try:
        if payload.get(direct_key) is not None:
            return float(payload[direct_key])

        take_profits = payload.get("take_profits") or {}
        item = take_profits.get(key) or {}
        if isinstance(item, dict) and item.get("close_percent") is not None:
            return float(item["close_percent"])
    except Exception:
        pass

    return float(default)



def reprice_entry_levels_to_fill(payload: dict[str, Any], fill_price: float) -> dict[str, Any]:
    """
    Paper-only level normalization.

    Risk engine levels are produced from the requested/planned entry price.
    Paper execution may fill at a different price, especially after market fallback.
    To preserve the originally planned R/R distance, rebuild SL and TP levels
    around the actual fill price before sending the execution event to
    trade-guardian.

    Live execution should not use this helper directly. In live mode, exchange
    fills/order events should be consumed as the source of truth.
    """
    side = normalize_side(payload.get("position_side"))
    planned_entry = safe_float(payload.get("entry_price"))
    actual_entry = safe_float(fill_price)

    original_stop = safe_float(payload.get("stop_loss"))
    original_tp1 = safe_float(payload.get("tp1_price"))
    original_tp2 = safe_float(payload.get("tp2_price"))
    original_tp3 = safe_float(payload.get("tp3_price"))

    stop_distance = abs(planned_entry - original_stop)
    tp1_distance = abs(original_tp1 - planned_entry)
    tp2_distance = abs(original_tp2 - planned_entry)
    tp3_distance = abs(original_tp3 - planned_entry)

    if side == "long":
        stop_loss = actual_entry - stop_distance
        tp1_price = actual_entry + tp1_distance
        tp2_price = actual_entry + tp2_distance
        tp3_price = actual_entry + tp3_distance
    elif side == "short":
        stop_loss = actual_entry + stop_distance
        tp1_price = actual_entry - tp1_distance
        tp2_price = actual_entry - tp2_distance
        tp3_price = actual_entry - tp3_distance
    else:
        stop_loss = original_stop
        tp1_price = original_tp1
        tp2_price = original_tp2
        tp3_price = original_tp3

    entry_delta = actual_entry - planned_entry
    applied = abs(entry_delta) > 1e-12

    return {
        "version": "paper_entry_levels_repriced_to_actual_fill_v1",
        "scope": "paper",
        "applied": applied,
        "side": side,
        "planned_entry": planned_entry,
        "actual_entry": actual_entry,
        "entry_delta": entry_delta,
        "original_levels": {
            "stop_loss": original_stop,
            "tp1_price": original_tp1,
            "tp2_price": original_tp2,
            "tp3_price": original_tp3,
        },
        "distances": {
            "stop_loss": stop_distance,
            "tp1_price": tp1_distance,
            "tp2_price": tp2_distance,
            "tp3_price": tp3_distance,
        },
        "repriced_levels": {
            "stop_loss": stop_loss,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp3_price": tp3_price,
        },
    }


def build_entry_execution_report_v2(
    *,
    payload: dict[str, Any],
    order_id: int,
    order_type: str,
    fill_price: float,
    filled_size: float,
    fee_paid: float,
    slippage_bps: float,
    fill_source: str,
    fill_reason: str,
    notes: str,
) -> dict[str, Any]:
    """
    Build a v2 entry execution report.

    Trade Guardian still receives the legacy-compatible fields it already
    expects, while downstream/evaluator consumers can use the versioned fields.
    """
    account_id = int(payload["account_id"])
    symbol = str(payload["symbol"]).upper()
    side = normalize_side(payload["position_side"])
    level_reprice = reprice_entry_levels_to_fill(payload, fill_price)
    repriced_levels = level_reprice["repriced_levels"]

    return {
        "ok": True,
        "paper_execution_version": PAPER_EXECUTION_VERSION,
        "paper_execution_report_version": PAPER_EXECUTION_REPORT_VERSION,
        "execution_report_type": "entry_fill",
        "execution_scope": "paper",
        "generated_at": iso_now(),

        "account_id": account_id,
        "order_id": int(order_id),
        "symbol": symbol,
        "position_side": side,
        "execution_type": "ENTRY",
        "order_type": normalize_order_type(order_type),
        "fill_price": round(safe_float(fill_price), 8),
        "filled_size": round(safe_float(filled_size), 8),
        "fee_paid": round(safe_float(fee_paid), 8),
        "slippage_bps": round(safe_float(slippage_bps), 8),
        "stop_loss": round(safe_float(repriced_levels["stop_loss"]), 8),
        "tp1_price": round(safe_float(repriced_levels["tp1_price"]), 8),
        "tp2_price": round(safe_float(repriced_levels["tp2_price"]), 8),
        "tp3_price": round(safe_float(repriced_levels["tp3_price"]), 8),
        "tp1_close_percent": get_tp_close_percent(payload, "tp1", 50),
        "tp2_close_percent": get_tp_close_percent(payload, "tp2", 30),
        "tp3_close_percent": get_tp_close_percent(payload, "tp3", 20),
        "risk_amount": safe_float(payload["risk_amount"]),
        "leverage": safe_float(payload.get("leverage", 1.0)),
        "entry_atr": safe_float(payload.get("entry_atr")),
        "notes": notes,

        "fill_source": fill_source,
        "fill_reason": fill_reason,
        "requested_entry_price": safe_float(payload.get("entry_price")),
        "levels_repriced_to_fill": bool(level_reprice["applied"]),
        "level_reprice": level_reprice,
        "original_levels": level_reprice["original_levels"],
        "repriced_levels": level_reprice["repriced_levels"],
        "requested_size": safe_float(payload.get("size")),
        "risk_approval_payload_version": payload.get("risk_approval_payload_version"),
        "risk_decision": payload.get("risk_decision"),
        "originating_cycle_id": payload.get("originating_cycle_id") or payload.get("cycle_id"),
        "attempt_number": int(payload.get("attempt_number", 1)),
        "max_attempts": int(payload.get("max_attempts", 15)),
        "execution_context": {
            "selected_strategy": payload.get("selected_strategy"),
            "regime": payload.get("regime"),
            "strategy_confidence": payload.get("strategy_confidence"),
            "risk_context": payload.get("risk_context", {}),
            "entry_atr": safe_float(payload.get("entry_atr")),
            "level_reprice": level_reprice,
        },
    }


def build_entry_pending_result(
    *,
    order_id: int,
    attempt_number: int,
    next_attempt_number: int,
    reason_codes: list[str],
    fill_model_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "paper_execution_version": PAPER_EXECUTION_VERSION,
        "paper_execution_report_version": PAPER_EXECUTION_REPORT_VERSION,
        "action": "ENTRY_PENDING",
        "order_id": int(order_id),
        "attempt_number": int(attempt_number),
        "next_attempt_number": int(next_attempt_number),
        "reason_codes": reason_codes,
        "fill_model_context": fill_model_context,
    }


def build_entry_filled_result(
    *,
    fill_method: str,
    execution_event: dict[str, Any],
    guardian_result: dict[str, Any],
    order_id: int,
    fill_model_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "paper_execution_version": PAPER_EXECUTION_VERSION,
        "paper_execution_report_version": PAPER_EXECUTION_REPORT_VERSION,
        "action": "ENTRY_FILLED",
        "fill_method": fill_method,
        "execution_event": execution_event,
        "guardian_result": guardian_result,
        "order_id": int(order_id),
        "fill_model_context": fill_model_context,
    }
