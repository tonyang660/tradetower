"""
Phase 6 Step 10 — position-management idempotency helpers.

The primary idempotency guarantee for stop-management actions is still the
protective-stop improvement check:

- long stops only move upward
- short stops only move downward
- if the proposed stop is already applied or no longer improves protection, the
  manager returns NO_STOP_REPRICE / no-op

This module adds normalized summaries and keys so repeated automatic-cycle calls
are easier to inspect and safer to report.
"""

from __future__ import annotations

from typing import Any

POSITION_MANAGEMENT_IDEMPOTENCY_VERSION = "phase6_step10_position_management_idempotency"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def build_management_key(
    *,
    account_id: int,
    symbol: str,
    module: str,
    reason_code: str | None,
    proposed_stop: float | None,
) -> str:
    stop_part = "none" if proposed_stop is None else str(round(safe_float(proposed_stop), 8))
    reason = reason_code or "none"

    return ":".join([
        "pm",
        str(int(account_id)),
        str(symbol).upper(),
        str(module),
        reason,
        stop_part,
    ])


def summarize_management_result(
    *,
    account_id: int,
    symbol: str,
    module: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    decision = result.get("decision") or {}
    reason_code = (
        result.get("reason_code")
        or decision.get("reason_code")
        or (result.get("reason_codes") or [None])[0]
    )
    proposed_stop = result.get("new_stop")
    if proposed_stop is None:
        proposed_stop = decision.get("proposed_stop")

    key = build_management_key(
        account_id=account_id,
        symbol=symbol,
        module=module,
        reason_code=reason_code,
        proposed_stop=proposed_stop,
    )

    return {
        "position_management_idempotency_version": POSITION_MANAGEMENT_IDEMPOTENCY_VERSION,
        "management_key": key,
        "module": module,
        "ok": bool(result.get("ok", False)),
        "action": result.get("action"),
        "reason_code": reason_code,
        "proposed_stop": proposed_stop,
        "new_stop": result.get("new_stop"),
        "old_stop": result.get("old_stop"),
        "is_noop": result.get("action") in (
            "NO_STOP_REPRICE",
            "NO_ACTION",
            "DRY_RUN_STOP_REPRICE",
            "DRY_RUN_NEAR_TP_STOP_REPRICE",
            "DRY_RUN_REGIME_CHANGE_STOP_REPRICE",
        ),
        "raw_result": result,
    }


def build_position_management_idempotency_contract() -> dict[str, Any]:
    return {
        "position_management_idempotency_version": POSITION_MANAGEMENT_IDEMPOTENCY_VERSION,
        "primary_safety": "stop managers only apply protective improvements",
        "repeated_call_behavior": "same state should return no-op after stop already moved",
        "summary_key": "account + symbol + module + reason + proposed_stop",
    }
