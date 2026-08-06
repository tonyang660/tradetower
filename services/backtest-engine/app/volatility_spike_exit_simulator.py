from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PHASE18_VOLATILITY_SPIKE_MODEL_VERSION = "phase18k_volatility_spike_sl2_production_parity"

DEFAULT_MIN_PROFIT_R = 0.4
DEFAULT_VOLATILITY_SPIKE_MULTIPLIER = 1.6
DEFAULT_BREAKEVEN_BUFFER_PCT = 0.0015
DEFAULT_ATR_PERIOD = 14


@dataclass(frozen=True)
class VolatilitySpikeExitConfig:
    enabled: bool = True
    sl2_close_pct: float = 50.0
    min_profit_r: float = DEFAULT_MIN_PROFIT_R
    spike_multiplier: float = DEFAULT_VOLATILITY_SPIKE_MULTIPLIER
    breakeven_buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT
    atr_period: int = DEFAULT_ATR_PERIOD
    version: str = PHASE18_VOLATILITY_SPIKE_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "VolatilitySpikeExitConfig":
        return cls(
            enabled=bool(config.get("volatility_spike_exit_enabled", True)),
            sl2_close_pct=max(0.0, min(100.0, safe_float(config.get("volatility_spike_sl2_close_pct"), 50.0))),
            min_profit_r=safe_float(config.get("volatility_spike_min_profit_r"), DEFAULT_MIN_PROFIT_R),
            spike_multiplier=safe_float(config.get("volatility_spike_multiplier"), DEFAULT_VOLATILITY_SPIKE_MULTIPLIER),
            breakeven_buffer_pct=safe_float(config.get("volatility_spike_breakeven_buffer_pct"), DEFAULT_BREAKEVEN_BUFFER_PCT),
            atr_period=max(2, int(safe_float(config.get("volatility_spike_atr_period"), DEFAULT_ATR_PERIOD))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def volatility_spike_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = VolatilitySpikeExitConfig.from_config(config or {})
    return {
        "version": PHASE18_VOLATILITY_SPIKE_MODEL_VERSION,
        "production_parity_reference": "trade-guardian/app/volatility_spike_stop_policy.py",
        "config": cfg.to_dict(),
        "rules": {
            "volatility_spike": "current_atr >= entry_atr * spike_multiplier",
            "profit": "profit_r >= min_profit_r, default 0.4R",
            "sl2_price": "breakeven plus/minus buffer, default 0.15%",
            "sl2_size": "50% of remaining position by default",
            "one_time": "runner state volatility_spike_sl2_consumed",
        },
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    return side if side in {"long", "short"} else "unknown"


def true_range_rows(rows: list[Any]) -> list[float]:
    trs: list[float] = []
    prev_close: float | None = None
    for row in rows:
        high = safe_float(getattr(row, "high", None) if not isinstance(row, dict) else row.get("high"))
        low = safe_float(getattr(row, "low", None) if not isinstance(row, dict) else row.get("low"))
        close = safe_float(getattr(row, "close", None) if not isinstance(row, dict) else row.get("close"))
        if high <= 0 or low <= 0:
            continue
        if prev_close is None or prev_close <= 0:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        if tr >= 0:
            trs.append(float(tr))
        prev_close = close if close > 0 else prev_close
    return trs


def atr_from_rows(rows: list[Any], period: int = DEFAULT_ATR_PERIOD) -> float | None:
    trs = true_range_rows(rows)
    if not trs:
        return None
    sample = trs[-max(1, int(period)):]
    return sum(sample) / len(sample)


def original_stop_from_position(position: dict[str, Any]) -> float | None:
    value = position.get("original_stop") if position.get("original_stop") is not None else position.get("initial_stop")
    if value is None:
        value = position.get("stop")
    stop = safe_float(value)
    return stop if stop > 0 else None


def current_stop_from_position(position: dict[str, Any]) -> float | None:
    stop = safe_float(position.get("stop"))
    return stop if stop > 0 else None


def profit_r(*, side: str, entry_price: float, current_price: float, original_stop: float | None) -> float:
    side = normalize_side(side)
    entry = safe_float(entry_price)
    current = safe_float(current_price)
    if original_stop is None:
        return 0.0
    initial_risk = abs(entry - safe_float(original_stop))
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
    buffer = entry * safe_float(buffer_pct, DEFAULT_BREAKEVEN_BUFFER_PCT)
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
    if side == "long":
        return safe_float(proposed_stop) > safe_float(current_stop)
    if side == "short":
        return safe_float(proposed_stop) < safe_float(current_stop)
    return False


def evaluate_volatility_spike_exit(
    *,
    position: dict[str, Any],
    latest_price: float,
    current_atr: float | None,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = VolatilitySpikeExitConfig.from_config(config)
    side = normalize_side(position.get("side") or position.get("position_side"))
    entry = safe_float(position.get("entry", position.get("entry_price")))
    current = safe_float(latest_price)
    entry_atr = safe_float(position.get("entry_atr"))
    cur_atr = safe_float(current_atr)

    original_stop = original_stop_from_position(position)
    current_stop = current_stop_from_position(position)
    pr = profit_r(side=side, entry_price=entry, current_price=current, original_stop=original_stop)

    already_triggered = bool(position.get("volatility_spike_sl2_consumed", False))
    active = bool(position.get("volatility_spike_sl2_active", False) or position.get("regime_change_sl2_active", False))
    spike = bool(entry_atr > 0 and cur_atr > 0 and cur_atr >= entry_atr * cfg.spike_multiplier)
    enough_profit = pr >= cfg.min_profit_r
    proposed_stop = breakeven_with_buffer(side=side, entry_price=entry, buffer_pct=cfg.breakeven_buffer_pct)
    improvement = is_stop_improvement(side=side, current_stop=current_stop, proposed_stop=proposed_stop)

    if not cfg.enabled:
        action = "no_action"
        reason_code = "VOLATILITY_SPIKE_DISABLED"
        proposed = None
    elif already_triggered:
        action = "no_action"
        reason_code = "VOLATILITY_SPIKE_STOP_ALREADY_TRIGGERED"
        proposed = None
    elif active:
        action = "no_action"
        reason_code = "SL2_ALREADY_ACTIVE"
        proposed = None
    elif spike and enough_profit and improvement:
        action = "activate_volatility_spike_sl2"
        spike_pct = ((cur_atr / entry_atr) - 1.0) * 100.0 if entry_atr > 0 else 0.0
        reason_code = f"VOLATILITY_SPIKE_PROFIT_PROTECTION_{spike_pct:.1f}PCT"
        proposed = proposed_stop
    elif spike and enough_profit and not improvement:
        action = "no_action"
        reason_code = "VOLATILITY_SPIKE_BUT_STOP_ALREADY_PROTECTED"
        proposed = proposed_stop
    elif not spike:
        action = "no_action"
        reason_code = "VOLATILITY_SPIKE_NOT_DETECTED"
        proposed = None
    else:
        action = "no_action"
        reason_code = "PROFIT_R_BELOW_VOLATILITY_PROTECTION_THRESHOLD"
        proposed = None

    atr_ratio = (cur_atr / entry_atr) if entry_atr > 0 and cur_atr > 0 else None
    return {
        "version": PHASE18_VOLATILITY_SPIKE_MODEL_VERSION,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry": entry,
        "latest_price": current,
        "current_stop": current_stop,
        "original_stop": original_stop,
        "proposed_stop": proposed,
        "is_stop_improvement": bool(improvement),
        "entry_atr": entry_atr,
        "current_atr": cur_atr,
        "atr_ratio": round(atr_ratio, 8) if atr_ratio is not None else None,
        "spike_multiplier": cfg.spike_multiplier,
        "volatility_spike_detected": bool(spike),
        "profit_r": round(pr, 8),
        "min_profit_r": cfg.min_profit_r,
        "breakeven_buffer_pct": cfg.breakeven_buffer_pct,
        "sl2_price": proposed if proposed is not None else entry,
        "sl2_close_pct": cfg.sl2_close_pct,
        "position_id": position.get("position_id"),
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    }
