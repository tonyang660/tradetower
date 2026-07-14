"""
Phase 6 Step 6 — partial fill and partial close accounting policy.

This module makes the intended TradeTower accounting explicit:

- TP1 closes a percentage of original position size
- TP2 closes a percentage of original position size
- TP3 closes all remaining size
- STOP_LOSS closes all remaining size
- released margin is proportional for partial exits
- full exits release all remaining margin
- close size is always capped to remaining size

It does not add exchange-style partial fills yet. It prepares the accounting
contract so partial fill support can be introduced safely later.
"""

from __future__ import annotations

from typing import Any

PARTIAL_CLOSE_POLICY_VERSION = "phase6_step6_partial_close_accounting"

DEFAULT_TP_CLOSE_PERCENTS = {
    "TP1": 50.0,
    "TP2": 30.0,
    "TP3": 20.0,
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_execution_type(value: Any) -> str:
    return str(value or "").upper()


def calculate_close_size(
    *,
    execution_type: str,
    original_size: float,
    remaining_size: float,
    close_percent: float | None = None,
) -> float:
    execution_type = normalize_execution_type(execution_type)
    original_size = safe_float(original_size)
    remaining_size = safe_float(remaining_size)

    if remaining_size <= 0:
        return 0.0

    if execution_type in ("TP3", "STOP_LOSS"):
        return round(remaining_size, 8)

    if execution_type in ("TP1", "TP2"):
        pct = safe_float(
            close_percent,
            DEFAULT_TP_CLOSE_PERCENTS.get(execution_type, 0.0),
        )
        close_size = original_size * (pct / 100.0)
        return round(min(close_size, remaining_size), 8)

    return 0.0


def calculate_released_margin(
    *,
    execution_type: str,
    margin_used: float,
    close_size: float,
    remaining_size_before: float,
) -> float:
    execution_type = normalize_execution_type(execution_type)
    margin_used = safe_float(margin_used)
    close_size = safe_float(close_size)
    remaining_size_before = safe_float(remaining_size_before)

    if execution_type in ("TP3", "STOP_LOSS"):
        return round(margin_used, 8)

    if remaining_size_before <= 0:
        return 0.0

    return round(margin_used * (close_size / remaining_size_before), 8)


def calculate_remaining_after_close(
    *,
    remaining_size_before: float,
    close_size: float,
) -> float:
    return round(max(safe_float(remaining_size_before) - safe_float(close_size), 0.0), 8)


def build_partial_close_accounting(
    *,
    execution_type: str,
    original_size: float,
    remaining_size_before: float,
    margin_used_before: float,
    close_percent: float | None = None,
) -> dict[str, Any]:
    execution_type = normalize_execution_type(execution_type)
    close_size = calculate_close_size(
        execution_type=execution_type,
        original_size=original_size,
        remaining_size=remaining_size_before,
        close_percent=close_percent,
    )
    released_margin = calculate_released_margin(
        execution_type=execution_type,
        margin_used=margin_used_before,
        close_size=close_size,
        remaining_size_before=remaining_size_before,
    )
    remaining_size_after = calculate_remaining_after_close(
        remaining_size_before=remaining_size_before,
        close_size=close_size,
    )
    remaining_margin_after = round(max(safe_float(margin_used_before) - released_margin, 0.0), 8)

    is_full_close = execution_type in ("TP3", "STOP_LOSS") or remaining_size_after <= 0

    return {
        "partial_close_policy_version": PARTIAL_CLOSE_POLICY_VERSION,
        "execution_type": execution_type,
        "original_size": round(safe_float(original_size), 8),
        "remaining_size_before": round(safe_float(remaining_size_before), 8),
        "close_percent": (
            safe_float(close_percent)
            if close_percent is not None
            else DEFAULT_TP_CLOSE_PERCENTS.get(execution_type)
        ),
        "close_size": close_size,
        "remaining_size_after": remaining_size_after,
        "margin_used_before": round(safe_float(margin_used_before), 8),
        "released_margin": released_margin,
        "remaining_margin_after": remaining_margin_after,
        "is_full_close": is_full_close,
        "reason": (
            "close_remaining"
            if execution_type in ("TP3", "STOP_LOSS")
            else "close_percent_of_original_size"
        ),
    }


def build_partial_close_policy_contract() -> dict[str, Any]:
    return {
        "partial_close_policy_version": PARTIAL_CLOSE_POLICY_VERSION,
        "tp_close_percent_defaults": DEFAULT_TP_CLOSE_PERCENTS,
        "rules": {
            "TP1": "close configured percent of original size, capped by remaining size",
            "TP2": "close configured percent of original size, capped by remaining size",
            "TP3": "close all remaining size",
            "STOP_LOSS": "close all remaining size",
        },
        "margin_release": {
            "partial_exit": "margin_used * close_size / remaining_size_before",
            "full_exit": "all remaining margin",
        },
        "does_not_add": [
            "exchange-style partial fills",
            "adaptive stop loss",
            "breakeven movement",
            "near-TP reversal protection",
            "regime-change stop movement",
        ],
    }
