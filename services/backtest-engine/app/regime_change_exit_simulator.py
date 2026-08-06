from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PHASE18_REGIME_CHANGE_MODEL_VERSION = "phase18j_hf5_production_parity_regime_change_stop"

DEFAULT_MIN_PROFIT_R = 0.4
DEFAULT_BREAKEVEN_BUFFER_PCT = 0.0015

# Production Trade Guardian parity:
# services/trade-guardian/app/regime_change_stop_policy.py
PRODUCTION_FAVORABLE_ENTRY_REGIMES = {"trending", "strong_trend", "early_trend"}
PRODUCTION_DETERIORATED_REGIMES = {"choppy", "ranging", "range", "sideways", "low_volatility"}

# Backtest strategy labels are often side-specific. These aliases preserve the
# production meaning without requiring the historical strategy to emit exactly
# "trending" / "strong_trend" / "early_trend".
LONG_FAVORABLE_ENTRY_REGIMES = {
    "uptrend",
    "strong_uptrend",
    "early_uptrend",
    "trending_up",
    "bull",
    "bullish",
}
SHORT_FAVORABLE_ENTRY_REGIMES = {
    "downtrend",
    "strong_downtrend",
    "early_downtrend",
    "trending_down",
    "bear",
    "bearish",
}


@dataclass(frozen=True)
class RegimeChangeExitConfig:
    enabled: bool = True
    sl2_close_pct: float = 50.0
    require_profit: bool = True
    min_profit_r: float = DEFAULT_MIN_PROFIT_R
    breakeven_buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT
    version: str = PHASE18_REGIME_CHANGE_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RegimeChangeExitConfig":
        close_pct = safe_float(config.get("regime_change_sl2_close_pct"), 50.0)
        return cls(
            enabled=bool(config.get("regime_change_exit_enabled", True)),
            sl2_close_pct=max(0.0, min(100.0, close_pct)),
            require_profit=bool(config.get("regime_change_require_profit", True)),
            min_profit_r=safe_float(config.get("regime_change_min_profit_r"), DEFAULT_MIN_PROFIT_R),
            breakeven_buffer_pct=safe_float(
                config.get("regime_change_breakeven_buffer_pct"),
                DEFAULT_BREAKEVEN_BUFFER_PCT,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def regime_change_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = RegimeChangeExitConfig.from_config(config or {})
    return {
        "version": PHASE18_REGIME_CHANGE_MODEL_VERSION,
        "config": cfg.to_dict(),
        "production_parity_reference": "trade-guardian/app/regime_change_stop_policy.py",
        "rules": {
            "entry_regime": "must be favorable/trending",
            "current_regime": "must deteriorate into choppy/ranging/sideways/low_volatility",
            "profit": "must be >= min_profit_r, default 0.4R",
            "sl2_price": "breakeven plus/minus buffer, default 0.15%",
            "one_time": "enforced by runner state: regime_change_sl2_consumed",
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


def normalize_regime(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    if side in {"long", "short"}:
        return side
    return "unknown"


def original_stop_from_position(position: dict[str, Any]) -> float | None:
    value = (
        position.get("original_stop")
        if position.get("original_stop") is not None
        else position.get("initial_stop")
    )
    if value is None:
        value = position.get("stop")
    stop = safe_float(value)
    return stop if stop > 0 else None


def current_stop_from_position(position: dict[str, Any]) -> float | None:
    value = position.get("stop")
    if value is None:
        value = position.get("stop_loss")
    stop = safe_float(value)
    return stop if stop > 0 else None


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

    initial_risk = abs(entry - safe_float(original_stop))
    if entry <= 0 or current <= 0 or initial_risk <= 0:
        return 0.0

    if side == "long":
        return (current - entry) / initial_risk
    if side == "short":
        return (entry - current) / initial_risk
    return 0.0


def favorable_entry_regime(*, side: str, entry_regime: str) -> bool:
    side = normalize_side(side)
    regime = normalize_regime(entry_regime)

    if regime in PRODUCTION_FAVORABLE_ENTRY_REGIMES:
        return True
    if side == "long" and regime in LONG_FAVORABLE_ENTRY_REGIMES:
        return True
    if side == "short" and regime in SHORT_FAVORABLE_ENTRY_REGIMES:
        return True
    return False


def regime_deteriorated(*, side: str, entry_regime: str, current_regime: str | None) -> bool:
    if not current_regime:
        return False

    if not favorable_entry_regime(side=side, entry_regime=entry_regime):
        return False

    current = normalize_regime(current_regime)
    return current in PRODUCTION_DETERIORATED_REGIMES


def breakeven_with_buffer(
    *,
    side: str,
    entry_price: float,
    buffer_pct: float = DEFAULT_BREAKEVEN_BUFFER_PCT,
) -> float:
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
    current = safe_float(current_stop)
    proposed = safe_float(proposed_stop)

    if side == "long":
        return proposed > current
    if side == "short":
        return proposed < current
    return False


def evaluate_regime_change_exit(
    *,
    position: dict[str, Any],
    current_regime: str | None,
    latest_price: float | None,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = RegimeChangeExitConfig.from_config(config)
    side = normalize_side(position.get("side") or position.get("position_side"))
    entry = safe_float(position.get("entry", position.get("entry_price")))
    current = safe_float(latest_price)
    entry_regime = str(position.get("regime") or position.get("entry_regime") or "unknown")
    active = bool(position.get("regime_change_sl2_active", False))
    consumed = bool(position.get("regime_change_sl2_consumed", False))

    original_stop = original_stop_from_position(position)
    current_stop = current_stop_from_position(position)

    pr = profit_r(
        side=side,
        entry_price=entry,
        current_price=current,
        original_stop=original_stop,
    )

    deterioration = cfg.enabled and regime_deteriorated(
        side=side,
        entry_regime=entry_regime,
        current_regime=current_regime,
    )
    enough_profit = (pr >= cfg.min_profit_r) if cfg.require_profit else True
    proposed_stop = breakeven_with_buffer(
        side=side,
        entry_price=entry,
        buffer_pct=cfg.breakeven_buffer_pct,
    )
    improvement = is_stop_improvement(
        side=side,
        current_stop=current_stop,
        proposed_stop=proposed_stop,
    )

    if consumed:
        action = "no_action"
        reason_code = "REGIME_CHANGE_STOP_ALREADY_TRIGGERED"
        proposed = None
    elif active:
        action = "no_action"
        reason_code = "REGIME_CHANGE_SL2_ALREADY_ACTIVE"
        proposed = None
    elif deterioration and enough_profit and improvement:
        action = "activate_regime_change_sl2"
        reason_code = "REGIME_DETERIORATION_PROFIT_PROTECTION"
        proposed = proposed_stop
    elif deterioration and enough_profit and not improvement:
        action = "no_action"
        reason_code = "REGIME_DETERIORATION_BUT_STOP_ALREADY_PROTECTED"
        proposed = proposed_stop
    elif deterioration and not enough_profit:
        action = "no_action"
        reason_code = "PROFIT_R_BELOW_REGIME_PROTECTION_THRESHOLD"
        proposed = None
    else:
        action = "no_action"
        reason_code = "REGIME_DID_NOT_DETERIORATE"
        proposed = None

    return {
        "version": PHASE18_REGIME_CHANGE_MODEL_VERSION,
        "enabled": cfg.enabled,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry": entry,
        "latest_price": current,
        "entry_regime": normalize_regime(entry_regime),
        "current_regime": normalize_regime(current_regime),
        "entry_regime_favorable": favorable_entry_regime(side=side, entry_regime=entry_regime),
        "regime_deteriorated": bool(deterioration),
        "original_stop": original_stop,
        "current_stop": current_stop,
        "proposed_stop": proposed,
        "is_stop_improvement": bool(improvement),
        "profit_r": round(pr, 8),
        "min_profit_r": cfg.min_profit_r,
        "require_profit": cfg.require_profit,
        "position_in_profit": bool(pr > 0),
        "breakeven_buffer_pct": cfg.breakeven_buffer_pct,
        "sl2_price": proposed if proposed is not None else entry,
        "sl2_close_pct": cfg.sl2_close_pct,
        "position_id": position.get("position_id"),
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    }
