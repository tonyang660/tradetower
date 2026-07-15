"""
Phase 6 Step 9 — Regime-change protective stop adjustment.

Ports the v1 regime deterioration adaptive stop behavior into Trade Guardian.

v1 reference:
- adaptive stop activates when trade is profitable by at least 0.4R
- and market regime deteriorates from trending/strong_trend into choppy/ranging
- protective stop moves to breakeven plus/minus a small buffer
- only tightens stops; never widens
- one-time adjustment should be enforced by the caller/state layer

No ATR trailing is implemented here.
"""

from __future__ import annotations

from typing import Any

REGIME_CHANGE_STOP_POLICY_VERSION = "phase6_step9_regime_change_stop_adjustment"

DEFAULT_MIN_PROFIT_R = 0.4
DEFAULT_BREAKEVEN_BUFFER_PCT = 0.0015

FAVORABLE_ENTRY_REGIMES = {"trending", "strong_trend", "early_trend"}
DETERIORATED_REGIMES = {"choppy", "ranging", "range", "sideways", "low_volatility"}


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


def normalize_regime(value: Any) -> str:
    return str(value or "unknown").strip().lower()


def original_stop_from_position(position: dict[str, Any]) -> float | None:
    entry = safe_float(position.get("entry_price"))
    side = normalize_side(position.get("side") or position.get("position_side"))
    size = safe_float(position.get("original_size", position.get("size", 0.0)))
    risk_amount = safe_float(position.get("risk_amount"))

    if entry <= 0 or size <= 0 or risk_amount <= 0:
        current_stop = position.get("stop_loss")
        return safe_float(current_stop) if current_stop is not None else None

    risk_per_unit = risk_amount / size

    if side == "long":
        return round(entry - risk_per_unit, 8)
    if side == "short":
        return round(entry + risk_per_unit, 8)

    return None


def profit_r(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    original_stop: float | None,
) -> float:
    side = normalize_side(side)
    entry = safe_float(entry_price)
    current = safe_float(current_price)

    if original_stop is None:
        return 0.0

    stop = safe_float(original_stop)
    initial_risk = abs(entry - stop)

    if initial_risk <= 0:
        return 0.0

    if side == "long":
        return (current - entry) / initial_risk
    if side == "short":
        return (entry - current) / initial_risk

    return 0.0


def regime_deteriorated(*, entry_regime: str, current_regime: str) -> bool:
    entry = normalize_regime(entry_regime)
    current = normalize_regime(current_regime)
    return entry in FAVORABLE_ENTRY_REGIMES and current in DETERIORATED_REGIMES


def breakeven_with_buffer(
    *,
    side: str,
    entry_price: float,
    buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT,
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


def evaluate_regime_change_stop_adjustment(
    *,
    position: dict[str, Any],
    current_price: float,
    entry_regime: str,
    current_regime: str,
    min_profit_r: float = DEFAULT_MIN_PROFIT_R,
    breakeven_buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT,
    already_triggered: bool = False,
) -> dict[str, Any]:
    side = normalize_side(position.get("side") or position.get("position_side"))
    entry = safe_float(position.get("entry_price"))
    current = safe_float(current_price)
    current_stop = position.get("stop_loss")
    original_stop = original_stop_from_position(position)

    pr = profit_r(
        side=side,
        entry_price=entry,
        current_price=current,
        original_stop=original_stop,
    )

    deterioration = regime_deteriorated(
        entry_regime=entry_regime,
        current_regime=current_regime,
    )

    enough_profit = pr >= safe_float(min_profit_r, DEFAULT_MIN_PROFIT_R)

    if already_triggered:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "REGIME_CHANGE_STOP_ALREADY_TRIGGERED"
    elif deterioration and enough_profit:
        proposed_stop = breakeven_with_buffer(
            side=side,
            entry_price=entry,
            buffer_pct=breakeven_buffer_pct,
        )
        improvement = is_stop_improvement(
            side=side,
            current_stop=current_stop,
            proposed_stop=proposed_stop,
        )
        if improvement:
            action = "MOVE_STOP_TO_BREAKEVEN_BUFFER"
            reason_code = "REGIME_DETERIORATION_PROFIT_PROTECTION"
        else:
            action = "NO_STOP_REPRICE"
            reason_code = "REGIME_DETERIORATION_BUT_STOP_ALREADY_PROTECTED"
    elif not deterioration:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "REGIME_DID_NOT_DETERIORATE"
    else:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "PROFIT_R_BELOW_REGIME_PROTECTION_THRESHOLD"

    improvement = is_stop_improvement(
        side=side,
        current_stop=current_stop,
        proposed_stop=proposed_stop,
    )

    return {
        "ok": True,
        "regime_change_stop_policy_version": REGIME_CHANGE_STOP_POLICY_VERSION,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry_price": round(entry, 8),
        "current_price": round(current, 8),
        "current_stop": safe_float(current_stop) if current_stop is not None else None,
        "original_stop_estimate": original_stop,
        "proposed_stop": proposed_stop,
        "is_stop_improvement": improvement,
        "entry_regime": normalize_regime(entry_regime),
        "current_regime": normalize_regime(current_regime),
        "regime_deteriorated": deterioration,
        "profit_r": round(pr, 8),
        "min_profit_r": safe_float(min_profit_r, DEFAULT_MIN_PROFIT_R),
        "breakeven_buffer_pct": safe_float(breakeven_buffer_pct, DEFAULT_BREAKEVEN_BUFFER_PCT),
        "already_triggered": already_triggered,
    }


def build_regime_change_stop_policy_contract() -> dict[str, Any]:
    return {
        "regime_change_stop_policy_version": REGIME_CHANGE_STOP_POLICY_VERSION,
        "owner": "trade_guardian",
        "min_profit_r": DEFAULT_MIN_PROFIT_R,
        "breakeven_buffer_pct": DEFAULT_BREAKEVEN_BUFFER_PCT,
        "entry_regimes_that_can_deteriorate": sorted(FAVORABLE_ENTRY_REGIMES),
        "deteriorated_regimes": sorted(DETERIORATED_REGIMES),
        "protective_action": "move stop to breakeven plus/minus buffer if protective",
        "does_not_add": [
            "ATR trailing stop",
            "volatility-spike adaptive trigger",
            "early TP market exit",
            "automatic scheduler invocation",
        ],
    }
