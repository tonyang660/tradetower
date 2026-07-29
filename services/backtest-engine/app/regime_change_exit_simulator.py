from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_REGIME_CHANGE_MODEL_VERSION = "phase18j_hf1_regime_change_sl2_profit_guard"


@dataclass(frozen=True)
class RegimeChangeExitConfig:
    enabled: bool = True
    sl2_close_pct: float = 50.0
    require_profit: bool = True
    version: str = PHASE18_REGIME_CHANGE_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RegimeChangeExitConfig":
        close_pct = float(config.get("regime_change_sl2_close_pct", 50.0))
        return cls(
            enabled=bool(config.get("regime_change_exit_enabled", True)),
            sl2_close_pct=max(0.0, min(100.0, close_pct)),
            require_profit=bool(config.get("regime_change_require_profit", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def regime_change_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = RegimeChangeExitConfig.from_config(config or {})
    return {
        "version": PHASE18_REGIME_CHANGE_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "Detects adverse regime changes against an open position.",
            "SL2 is only activated when the position is currently in profit by default.",
            "On trigger, activates SL2 at breakeven/entry for 50% of remaining size by default.",
            "If the SL2 price is touched, the SL2 leg fills as a maker protective-limit exit.",
            "The primary protective stop remains active for the remaining size.",
        ],
    }


def normalize_regime(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def regime_supports_side(*, side: str, regime: str) -> bool:
    side = str(side).lower()
    regime = normalize_regime(regime)

    if side == "long":
        return regime in {"uptrend", "strong uptrend", "early uptrend", "trending up", "bull", "bullish"}
    if side == "short":
        return regime in {"downtrend", "strong downtrend", "early downtrend", "trending down", "bear", "bearish"}
    return False


def regime_is_adverse(*, side: str, entry_regime: str, current_regime: str | None) -> bool:
    if not current_regime:
        return False

    entry = normalize_regime(entry_regime)
    current = normalize_regime(current_regime)
    if not current or current == entry:
        return False

    return not regime_supports_side(side=side, regime=current)


def position_is_in_profit(*, side: str, entry_price: float, latest_price: float | None) -> bool:
    if latest_price is None:
        return False

    side = str(side).lower()
    entry = float(entry_price)
    latest = float(latest_price)

    if entry <= 0 or latest <= 0:
        return False

    if side == "long":
        return latest > entry
    if side == "short":
        return latest < entry
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
    side = str(position.get("side", "")).lower()
    entry = float(position.get("entry", 0.0) or 0.0)
    entry_regime = str(position.get("regime") or position.get("entry_regime") or "")
    active = bool(position.get("regime_change_sl2_active", False))

    adverse = cfg.enabled and not active and regime_is_adverse(
        side=side,
        entry_regime=entry_regime,
        current_regime=current_regime,
    )
    in_profit = position_is_in_profit(side=side, entry_price=entry, latest_price=latest_price)

    should_activate = bool(adverse and (in_profit or not cfg.require_profit))
    if should_activate:
        action = "activate_regime_change_sl2"
        reason_code = "ADVERSE_REGIME_CHANGE_POSITION_IN_PROFIT"
    elif adverse and cfg.require_profit and not in_profit:
        action = "no_action"
        reason_code = "ADVERSE_REGIME_CHANGE_BUT_POSITION_NOT_IN_PROFIT"
    elif active:
        action = "no_action"
        reason_code = "REGIME_CHANGE_SL2_ALREADY_ACTIVE"
    else:
        action = "no_action"
        reason_code = "NO_ADVERSE_REGIME_CHANGE"

    return {
        "version": PHASE18_REGIME_CHANGE_MODEL_VERSION,
        "enabled": cfg.enabled,
        "action": action,
        "reason_code": reason_code,
        "side": side,
        "entry": entry,
        "latest_price": latest_price,
        "entry_regime": entry_regime,
        "current_regime": current_regime,
        "is_adverse_regime_change": bool(adverse),
        "require_profit": cfg.require_profit,
        "position_in_profit": bool(in_profit),
        "sl2_price": entry,
        "sl2_close_pct": cfg.sl2_close_pct,
        "position_id": position.get("position_id"),
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    }
