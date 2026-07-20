"""
Phase 7.6b — Volatility-spike adaptive defensive SL2 policy.
"""

from __future__ import annotations

from typing import Any

VOLATILITY_SPIKE_STOP_POLICY_VERSION = "phase7_6b_volatility_spike_adaptive_sl2"
DEFAULT_MIN_PROFIT_R = 0.4
DEFAULT_VOLATILITY_SPIKE_MULTIPLIER = 1.6
DEFAULT_BREAKEVEN_BUFFER_PCT = 0.0015


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
    return value if value in ("long", "short") else "unknown"


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


def profit_r(*, side: str, entry_price: float, current_price: float, original_stop: float | None) -> float:
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


def breakeven_with_buffer(*, side: str, entry_price: float, buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT) -> float:
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


def volatility_spike_detected(*, entry_atr: float, current_atr: float, spike_multiplier: float = DEFAULT_VOLATILITY_SPIKE_MULTIPLIER) -> bool:
    entry = safe_float(entry_atr)
    current = safe_float(current_atr)
    multiplier = safe_float(spike_multiplier, DEFAULT_VOLATILITY_SPIKE_MULTIPLIER)
    if entry <= 0 or current <= 0 or multiplier <= 0:
        return False
    return current >= entry * multiplier


def evaluate_volatility_spike_stop_adjustment(
    *,
    position: dict[str, Any],
    current_price: float,
    entry_atr: float,
    current_atr: float,
    min_profit_r: float = DEFAULT_MIN_PROFIT_R,
    spike_multiplier: float = DEFAULT_VOLATILITY_SPIKE_MULTIPLIER,
    breakeven_buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT,
    already_triggered: bool = False,
) -> dict[str, Any]:
    side = normalize_side(position.get("side") or position.get("position_side"))
    entry = safe_float(position.get("entry_price"))
    current = safe_float(current_price)
    current_stop = position.get("stop_loss")
    original_stop = original_stop_from_position(position)

    pr = profit_r(side=side, entry_price=entry, current_price=current, original_stop=original_stop)
    enough_profit = pr >= safe_float(min_profit_r, DEFAULT_MIN_PROFIT_R)
    spike = volatility_spike_detected(entry_atr=entry_atr, current_atr=current_atr, spike_multiplier=spike_multiplier)
    atr_ratio = safe_float(current_atr) / safe_float(entry_atr) if safe_float(entry_atr) > 0 else None

    if already_triggered:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "VOLATILITY_SPIKE_STOP_ALREADY_TRIGGERED"
    elif spike and enough_profit:
        proposed_stop = breakeven_with_buffer(side=side, entry_price=entry, buffer_pct=breakeven_buffer_pct)
        improvement = is_stop_improvement(side=side, current_stop=current_stop, proposed_stop=proposed_stop)
        if improvement:
            action = "ACTIVATE_DEFENSIVE_SL2"
            spike_pct = ((safe_float(current_atr) / safe_float(entry_atr)) - 1.0) * 100.0 if safe_float(entry_atr) > 0 else 0.0
            reason_code = f"VOLATILITY_SPIKE_PROFIT_PROTECTION_{spike_pct:.1f}PCT"
        else:
            action = "NO_STOP_REPRICE"
            reason_code = "VOLATILITY_SPIKE_BUT_STOP_ALREADY_PROTECTED"
    elif not spike:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "VOLATILITY_SPIKE_NOT_DETECTED"
    else:
        proposed_stop = None
        action = "NO_ACTION"
        reason_code = "PROFIT_R_BELOW_VOLATILITY_PROTECTION_THRESHOLD"

    improvement = is_stop_improvement(side=side, current_stop=current_stop, proposed_stop=proposed_stop)

    return {
        "ok": True,
        "volatility_spike_stop_policy_version": VOLATILITY_SPIKE_STOP_POLICY_VERSION,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry_price": round(entry, 8),
        "current_price": round(current, 8),
        "current_stop": safe_float(current_stop) if current_stop is not None else None,
        "original_stop_estimate": original_stop,
        "proposed_stop": proposed_stop,
        "is_stop_improvement": improvement,
        "entry_atr": safe_float(entry_atr),
        "current_atr": safe_float(current_atr),
        "atr_ratio": round(atr_ratio, 8) if atr_ratio is not None else None,
        "spike_multiplier": safe_float(spike_multiplier, DEFAULT_VOLATILITY_SPIKE_MULTIPLIER),
        "volatility_spike_detected": spike,
        "profit_r": round(pr, 8),
        "min_profit_r": safe_float(min_profit_r, DEFAULT_MIN_PROFIT_R),
        "breakeven_buffer_pct": safe_float(breakeven_buffer_pct, DEFAULT_BREAKEVEN_BUFFER_PCT),
        "already_triggered": already_triggered,
    }


def build_volatility_spike_stop_policy_contract() -> dict[str, Any]:
    return {
        "volatility_spike_stop_policy_version": VOLATILITY_SPIKE_STOP_POLICY_VERSION,
        "owner": "trade_guardian",
        "min_profit_r": DEFAULT_MIN_PROFIT_R,
        "spike_multiplier": DEFAULT_VOLATILITY_SPIKE_MULTIPLIER,
        "breakeven_buffer_pct": DEFAULT_BREAKEVEN_BUFFER_PCT,
        "protective_action": "create/update defensive SL2 at breakeven buffer if current_atr >= entry_atr * 1.6 and profit >= 0.4R",
    }
