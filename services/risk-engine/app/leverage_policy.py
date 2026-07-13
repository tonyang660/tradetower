"""
Phase 5 Step 5 — leverage and liquidation safety model.

This module formalizes Risk Engine leverage selection as a standalone,
testable policy.

It does not know about Strategy Engine, Scheduler, Paper Execution, or Trade
Guardian HTTP. It only answers:

    Given side/entry/stop/notional/cash, which leverage is safe?

Runtime wiring happens in services/risk-engine/app/main.py.
"""

from __future__ import annotations

from typing import Any

LEVERAGE_POLICY_VERSION = "phase5_step5_leverage_liquidation_safety"

DEFAULT_MAX_LEVERAGE = 15.0
DEFAULT_MIN_LIQUIDATION_BUFFER_PCT = 0.35
DEFAULT_LEVERAGE_SEQUENCE = [15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_position_side(side: str) -> str | None:
    side = str(side or "").lower()
    if side in ("long", "short"):
        return side
    return None


def compute_stop_distance(side: str, entry: float, stop: float) -> float:
    side = normalize_position_side(side)
    entry = safe_float(entry)
    stop = safe_float(stop)

    if side == "long":
        return entry - stop
    if side == "short":
        return stop - entry
    return 0.0


def approximate_liquidation_price(side: str, entry: float, leverage: float) -> float | None:
    side = normalize_position_side(side)
    entry = safe_float(entry)
    leverage = safe_float(leverage)

    if side is None or entry <= 0 or leverage <= 0:
        return None

    # Simplified isolated-margin model for paper/risk pre-checks.
    if side == "long":
        return entry * (1.0 - (1.0 / leverage))
    if side == "short":
        return entry * (1.0 + (1.0 / leverage))
    return None


def liquidation_buffer_pct(side: str, stop: float, liquidation_price: float, entry: float) -> float:
    side = normalize_position_side(side)
    stop = safe_float(stop)
    liquidation_price = safe_float(liquidation_price)
    entry = safe_float(entry)

    if side is None or entry <= 0:
        return 0.0

    if side == "long":
        # Positive means liquidation is below stop, which is desired.
        return ((stop - liquidation_price) / entry) * 100.0

    if side == "short":
        # Positive means liquidation is above stop, which is desired.
        return ((liquidation_price - stop) / entry) * 100.0

    return 0.0


def build_leverage_candidates(
    max_leverage: float = DEFAULT_MAX_LEVERAGE,
    leverage_hint: float | None = None,
    leverage_sequence: list[float] | None = None,
) -> tuple[list[float], list[dict[str, Any]]]:
    max_leverage = safe_float(max_leverage, DEFAULT_MAX_LEVERAGE)
    sequence = list(leverage_sequence or DEFAULT_LEVERAGE_SEQUENCE)

    candidates = sorted({
        safe_float(value)
        for value in sequence
        if safe_float(value) > 0 and safe_float(value) <= max_leverage
    }, reverse=True)

    notes: list[dict[str, Any]] = []

    if leverage_hint is not None:
        hint = safe_float(leverage_hint)
        if hint <= 0:
            notes.append({"reason": "LEVERAGE_HINT_TOO_LOW", "leverage_hint": leverage_hint})
        elif hint > max_leverage:
            notes.append({
                "reason": "LEVERAGE_HINT_ABOVE_MAX",
                "leverage_hint": hint,
                "max_leverage": max_leverage,
            })
        else:
            candidates.append(hint)
            candidates = sorted(set(candidates), reverse=True)
            notes.append({"reason": "LEVERAGE_HINT_INCLUDED", "leverage_hint": hint})

    return candidates, notes


def evaluate_leverage_candidate(
    *,
    side: str,
    entry: float,
    stop: float,
    notional: float,
    cash_balance: float,
    leverage: float,
    min_liquidation_buffer_pct: float = DEFAULT_MIN_LIQUIDATION_BUFFER_PCT,
) -> dict[str, Any]:
    side = normalize_position_side(side)
    entry = safe_float(entry)
    stop = safe_float(stop)
    notional = safe_float(notional)
    cash_balance = safe_float(cash_balance)
    leverage = safe_float(leverage)
    min_liquidation_buffer_pct = safe_float(min_liquidation_buffer_pct, DEFAULT_MIN_LIQUIDATION_BUFFER_PCT)

    if side is None:
        return {"ok": False, "leverage": leverage, "reason": "INVALID_POSITION_SIDE"}

    if leverage <= 0:
        return {"ok": False, "leverage": leverage, "reason": "INVALID_LEVERAGE"}

    if notional <= 0:
        return {"ok": False, "leverage": leverage, "reason": "INVALID_NOTIONAL"}

    stop_distance = compute_stop_distance(side, entry, stop)
    if stop_distance <= 0:
        return {
            "ok": False,
            "leverage": leverage,
            "reason": "INVALID_STOP_DISTANCE",
            "stop_distance": round(stop_distance, 8),
        }

    margin_required = notional / leverage
    if margin_required > cash_balance:
        return {
            "ok": False,
            "leverage": leverage,
            "reason": "MARGIN_EXCEEDS_AVAILABLE_CAPITAL",
            "margin_required": round(margin_required, 8),
            "cash_balance": round(cash_balance, 8),
        }

    liquidation_price = approximate_liquidation_price(side, entry, leverage)
    if liquidation_price is None:
        return {
            "ok": False,
            "leverage": leverage,
            "reason": "INVALID_LIQUIDATION_MODEL",
        }

    buffer_pct = liquidation_buffer_pct(side, stop, liquidation_price, entry)
    if buffer_pct < min_liquidation_buffer_pct:
        return {
            "ok": False,
            "leverage": leverage,
            "reason": "LIQUIDATION_TOO_CLOSE_TO_STOP",
            "liquidation_price": round(liquidation_price, 8),
            "liquidation_buffer_pct": round(buffer_pct, 6),
            "min_liquidation_buffer_pct": min_liquidation_buffer_pct,
        }

    return {
        "ok": True,
        "leverage": leverage,
        "margin_required": round(margin_required, 8),
        "liquidation_price": round(liquidation_price, 8),
        "liquidation_buffer_pct": round(buffer_pct, 6),
        "stop_distance": round(stop_distance, 8),
    }


def select_safe_leverage(
    *,
    side: str,
    entry: float,
    stop: float,
    notional: float,
    cash_balance: float,
    max_leverage: float = DEFAULT_MAX_LEVERAGE,
    leverage_hint: float | None = None,
    min_liquidation_buffer_pct: float = DEFAULT_MIN_LIQUIDATION_BUFFER_PCT,
    leverage_sequence: list[float] | None = None,
) -> dict[str, Any]:
    candidates, candidate_notes = build_leverage_candidates(
        max_leverage=max_leverage,
        leverage_hint=leverage_hint,
        leverage_sequence=leverage_sequence,
    )

    rejections: list[dict[str, Any]] = []

    for leverage in candidates:
        result = evaluate_leverage_candidate(
            side=side,
            entry=entry,
            stop=stop,
            notional=notional,
            cash_balance=cash_balance,
            leverage=leverage,
            min_liquidation_buffer_pct=min_liquidation_buffer_pct,
        )

        if result.get("ok"):
            return {
                "ok": True,
                "leverage_policy_version": LEVERAGE_POLICY_VERSION,
                "chosen_leverage": result["leverage"],
                "margin_required": result["margin_required"],
                "liquidation_price_estimate": result["liquidation_price"],
                "liquidation_buffer_pct": result["liquidation_buffer_pct"],
                "candidates": candidates,
                "candidate_notes": candidate_notes,
                "leverage_rejections": rejections,
            }

        rejections.append(result)

    primary_reason = "NO_VALID_LEVERAGE_FOUND"
    if any(item.get("reason") == "LIQUIDATION_TOO_CLOSE_TO_STOP" for item in rejections):
        primary_reason = "LIQUIDATION_TOO_CLOSE_TO_STOP"
    elif any(item.get("reason") == "MARGIN_EXCEEDS_AVAILABLE_CAPITAL" for item in rejections):
        primary_reason = "MARGIN_EXCEEDS_AVAILABLE_CAPITAL"

    return {
        "ok": False,
        "leverage_policy_version": LEVERAGE_POLICY_VERSION,
        "reason": primary_reason,
        "candidates": candidates,
        "candidate_notes": candidate_notes,
        "leverage_rejections": rejections,
    }


def build_leverage_policy_contract() -> dict[str, Any]:
    return {
        "leverage_policy_version": LEVERAGE_POLICY_VERSION,
        "default_max_leverage": DEFAULT_MAX_LEVERAGE,
        "default_leverage_sequence": DEFAULT_LEVERAGE_SEQUENCE,
        "default_min_liquidation_buffer_pct": DEFAULT_MIN_LIQUIDATION_BUFFER_PCT,
        "selection_policy": (
            "Evaluate leverage candidates from highest to lowest. "
            "Choose the first leverage that fits available cash and keeps "
            "estimated liquidation safely beyond the stop."
        ),
        "rejection_reasons": [
            "INVALID_POSITION_SIDE",
            "INVALID_LEVERAGE",
            "INVALID_NOTIONAL",
            "INVALID_STOP_DISTANCE",
            "MARGIN_EXCEEDS_AVAILABLE_CAPITAL",
            "INVALID_LIQUIDATION_MODEL",
            "LIQUIDATION_TOO_CLOSE_TO_STOP",
            "NO_VALID_LEVERAGE_FOUND",
        ],
    }
