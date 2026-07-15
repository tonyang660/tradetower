"""
Phase 6 Step 8 — Near-TP reversal protection.

This ports the v1 "almost hit TP then reversed" protection into Trade Guardian
as a conservative policy module.

v1 reference behavior:
- identify next unhit TP
- track best price achieved since entry
- if best price reached >= near-TP threshold toward next TP
- and current price pulls back enough from best
- protect by proposing an early protective action

This module does not place orders by itself. It returns a decision for a future
position-management route/loop to apply.
"""

from __future__ import annotations

from typing import Any

NEAR_TP_REVERSAL_POLICY_VERSION = "phase6_step8_near_tp_reversal_protection"

DEFAULT_NEAR_TP_PROGRESS_THRESHOLD = 0.92
DEFAULT_NEAR_TP_PULLBACK_PCT = 0.005


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


def next_unhit_tp(position: dict[str, Any]) -> str | None:
    if not bool(position.get("tp1_hit")):
        return "tp1"
    if not bool(position.get("tp2_hit")):
        return "tp2"
    if not bool(position.get("tp3_hit")):
        return "tp3"
    return None


def tp_price(position: dict[str, Any], level: str) -> float | None:
    value = position.get(f"{level}_price")
    if value is None:
        return None
    result = safe_float(value)
    return result if result > 0 else None


def favorable_best_price(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    previous_best_price: float | None = None,
) -> float:
    side = normalize_side(side)
    entry = safe_float(entry_price)
    current = safe_float(current_price)
    previous = safe_float(previous_best_price, entry) if previous_best_price is not None else entry

    if side == "long":
        return max(previous, entry, current)
    if side == "short":
        return min(previous, entry, current)

    return current


def progress_to_tp(
    *,
    side: str,
    entry_price: float,
    best_price: float,
    target_price: float,
) -> float:
    side = normalize_side(side)
    entry = safe_float(entry_price)
    best = safe_float(best_price)
    target = safe_float(target_price)

    if side == "long":
        distance = target - entry
        achieved = best - entry
    elif side == "short":
        distance = entry - target
        achieved = entry - best
    else:
        return 0.0

    if distance <= 0:
        return 0.0

    return achieved / distance


def pullback_from_best(
    *,
    side: str,
    current_price: float,
    best_price: float,
) -> float:
    side = normalize_side(side)
    current = safe_float(current_price)
    best = safe_float(best_price)

    if best <= 0:
        return 0.0

    if side == "long":
        return max((best - current) / best, 0.0)
    if side == "short":
        return max((current - best) / best, 0.0)

    return 0.0


def breakeven_stop_price(
    *,
    side: str,
    entry_price: float,
    buffer_pct: float = 0.0,
) -> float:
    side = normalize_side(side)
    entry = safe_float(entry_price)
    buffer = entry * safe_float(buffer_pct)

    if side == "long":
        return round(entry + buffer, 8)
    if side == "short":
        return round(entry - buffer, 8)

    return round(entry, 8)


def is_stop_improvement(*, side: str, current_stop: float | None, proposed_stop: float | None) -> bool:
    if proposed_stop is None:
        return False
    if current_stop is None:
        return True

    side = normalize_side(side)
    current = safe_float(current_stop)
    proposed = safe_float(proposed_stop)

    if side == "long":
        return proposed > current
    if side == "short":
        return proposed < current

    return False


def evaluate_near_tp_reversal(
    *,
    position: dict[str, Any],
    current_price: float,
    previous_best_price: float | None = None,
    near_tp_progress_threshold: float = DEFAULT_NEAR_TP_PROGRESS_THRESHOLD,
    pullback_threshold_pct: float = DEFAULT_NEAR_TP_PULLBACK_PCT,
    breakeven_buffer_pct: float = 0.0,
) -> dict[str, Any]:
    side = normalize_side(position.get("side") or position.get("position_side"))
    entry = safe_float(position.get("entry_price"))
    current = safe_float(current_price)
    current_stop = position.get("stop_loss")

    level = next_unhit_tp(position)
    if level is None:
        return {
            "ok": True,
            "near_tp_reversal_policy_version": NEAR_TP_REVERSAL_POLICY_VERSION,
            "action": "NO_ACTION",
            "reason_code": "ALL_TPS_ALREADY_HIT",
        }

    target = tp_price(position, level)
    if target is None or entry <= 0 or current <= 0:
        return {
            "ok": False,
            "near_tp_reversal_policy_version": NEAR_TP_REVERSAL_POLICY_VERSION,
            "error": "invalid_position_or_price",
            "reason_code": "INVALID_POSITION_OR_PRICE",
            "next_tp_level": level,
        }

    best = favorable_best_price(
        side=side,
        entry_price=entry,
        current_price=current,
        previous_best_price=previous_best_price,
    )
    progress = progress_to_tp(
        side=side,
        entry_price=entry,
        best_price=best,
        target_price=target,
    )
    pullback = pullback_from_best(
        side=side,
        current_price=current,
        best_price=best,
    )

    threshold = safe_float(near_tp_progress_threshold, DEFAULT_NEAR_TP_PROGRESS_THRESHOLD)
    pullback_threshold = safe_float(pullback_threshold_pct, DEFAULT_NEAR_TP_PULLBACK_PCT)

    triggered = progress >= threshold and pullback >= pullback_threshold
    proposed_stop = breakeven_stop_price(
        side=side,
        entry_price=entry,
        buffer_pct=breakeven_buffer_pct,
    ) if triggered else None

    improvement = is_stop_improvement(
        side=side,
        current_stop=current_stop,
        proposed_stop=proposed_stop,
    )

    if triggered and improvement:
        action = "MOVE_STOP_TO_BREAKEVEN"
        reason_code = "NEAR_TP_REVERSAL_MOVE_STOP_TO_BREAKEVEN"
    elif triggered and not improvement:
        action = "NO_STOP_REPRICE"
        reason_code = "NEAR_TP_REVERSAL_DETECTED_BUT_STOP_ALREADY_PROTECTED"
    else:
        action = "NO_ACTION"
        reason_code = "NEAR_TP_REVERSAL_NOT_TRIGGERED"

    return {
        "ok": True,
        "near_tp_reversal_policy_version": NEAR_TP_REVERSAL_POLICY_VERSION,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry_price": round(entry, 8),
        "current_price": round(current, 8),
        "best_price": round(best, 8),
        "previous_best_price": previous_best_price,
        "current_stop": safe_float(current_stop) if current_stop is not None else None,
        "proposed_stop": proposed_stop,
        "is_stop_improvement": improvement,
        "next_tp_level": level,
        "next_tp_price": round(target, 8),
        "progress_to_next_tp": round(progress, 8),
        "near_tp_progress_threshold": threshold,
        "pullback_from_best_pct": round(pullback, 8),
        "pullback_threshold_pct": pullback_threshold,
        "breakeven_buffer_pct": safe_float(breakeven_buffer_pct),
        "triggered": triggered,
    }


def build_near_tp_reversal_policy_contract() -> dict[str, Any]:
    return {
        "near_tp_reversal_policy_version": NEAR_TP_REVERSAL_POLICY_VERSION,
        "owner": "trade_guardian",
        "default_progress_threshold": DEFAULT_NEAR_TP_PROGRESS_THRESHOLD,
        "default_pullback_threshold_pct": DEFAULT_NEAR_TP_PULLBACK_PCT,
        "behavior": {
            "track_best_price": "best favorable price since entry",
            "trigger": "best price reached near next TP and current price pulled back",
            "protective_action": "move stop to breakeven if it improves protection",
        },
        "does_not_add": [
            "early TP market exit",
            "ATR trailing stop",
            "regime-change stop movement",
            "automatic scheduler invocation",
        ],
    }
