"""
Phase 6 Step 3 — pending limit order lifecycle and retry policy.

This module keeps the existing TradeTower behavior explicit:

- limit not touched and attempts remain -> keep order open / pending retry
- limit not touched and attempts exhausted -> market fallback
- filled limit/market entries are handled by Paper Execution entry fill model

It does not change Scheduler's 1-minute pending-entry loop.
"""

from __future__ import annotations

from typing import Any

PENDING_ENTRY_POLICY_VERSION = "phase6_step3_pending_limit_lifecycle"


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def evaluate_pending_limit_lifecycle(
    *,
    attempt_number: int,
    max_attempts: int,
    fill_result: dict[str, Any],
) -> dict[str, Any]:
    attempt_number = safe_int(attempt_number, 1)
    max_attempts = safe_int(max_attempts, 15)

    if fill_result.get("filled"):
        return {
            "ok": True,
            "pending_entry_policy_version": PENDING_ENTRY_POLICY_VERSION,
            "decision": "fill_now",
            "attempt_number": attempt_number,
            "max_attempts": max_attempts,
            "next_attempt_number": None,
            "reason_codes": [],
        }

    if attempt_number < max_attempts:
        return {
            "ok": True,
            "pending_entry_policy_version": PENDING_ENTRY_POLICY_VERSION,
            "decision": "keep_pending",
            "attempt_number": attempt_number,
            "max_attempts": max_attempts,
            "next_attempt_number": attempt_number + 1,
            "reason_codes": fill_result.get("reason_codes", ["LIMIT_NOT_TOUCHED"]),
        }

    return {
        "ok": True,
        "pending_entry_policy_version": PENDING_ENTRY_POLICY_VERSION,
        "decision": "market_fallback",
        "attempt_number": attempt_number,
        "max_attempts": max_attempts,
        "next_attempt_number": None,
        "reason_codes": ["LIMIT_MAX_ATTEMPTS_REACHED", *fill_result.get("reason_codes", [])],
    }


def build_pending_entry_policy_contract() -> dict[str, Any]:
    return {
        "pending_entry_policy_version": PENDING_ENTRY_POLICY_VERSION,
        "behavior": {
            "limit_not_touched_before_max": "mark entry order open and retry later",
            "limit_not_touched_at_max": "fallback to market entry",
            "limit_touched": "fill limit entry",
            "market_order": "fill immediately using market fill model",
        },
        "does_not_change": [
            "scheduler pending-entry loop cadence",
            "max attempts configuration",
            "adaptive stop management",
            "protective order lifecycle",
        ],
    }
