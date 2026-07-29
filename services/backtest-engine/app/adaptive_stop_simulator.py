from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_ADAPTIVE_STOP_MODEL_VERSION = "phase18i_hf1_adaptive_stop_parity"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class AdaptiveStopConfig:
    enabled: bool = True
    version: str = PHASE18_ADAPTIVE_STOP_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AdaptiveStopConfig":
        return cls(enabled=bool(config.get("adaptive_stop_enabled", True)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def adaptive_stop_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = AdaptiveStopConfig.from_config(config or {})
    return {
        "version": PHASE18_ADAPTIVE_STOP_MODEL_VERSION,
        "config": cfg.to_dict(),
        "implemented_rules": {
            "tp1_half_risk": "after TP1, move SL to 50% of original risk",
            "tp2_breakeven": "after TP2, move SL to breakeven / entry price",
        },
        "safety_rules": [
            "never move a long stop downward",
            "never move a short stop upward",
            "do nothing when proposed stop is not more protective",
        ],
    }


def _is_improvement(*, side: str, current_stop: float, candidate_stop: float) -> bool:
    if side == "long":
        return float(candidate_stop) > float(current_stop)
    if side == "short":
        return float(candidate_stop) < float(current_stop)
    return False


def _half_risk_stop(*, side: str, entry: float, original_stop: float) -> float:
    entry = float(entry)
    original_stop = float(original_stop)
    if side == "long":
        # Example: entry 100, original stop 90 => 95
        return original_stop + ((entry - original_stop) * 0.5)
    if side == "short":
        # Example: entry 100, original stop 110 => 105
        return original_stop - ((original_stop - entry) * 0.5)
    raise ValueError(f"unsupported_position_side: {side}")


def build_adaptive_stop_update(
    *,
    position: dict[str, Any],
    trigger_role: str,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    cfg = AdaptiveStopConfig.from_config(config)
    if not cfg.enabled:
        return None

    role = str(trigger_role).lower()
    side = str(position["side"]).lower()
    current_stop = float(position["stop"])
    entry = float(position["entry"])
    original_stop = float(position.get("original_stop", position.get("initial_stop", current_stop)))

    if role == "tp1":
        candidate_stop = _half_risk_stop(side=side, entry=entry, original_stop=original_stop)
        policy = "TP1_MOVE_STOP_TO_HALF_RISK"
        action_code = "tp1_half_risk"
    elif role == "tp2":
        candidate_stop = entry
        policy = "TP2_MOVE_STOP_TO_BREAKEVEN"
        action_code = "tp2_breakeven"
    else:
        return None

    if not _is_improvement(side=side, current_stop=current_stop, candidate_stop=candidate_stop):
        return {
            "version": PHASE18_ADAPTIVE_STOP_MODEL_VERSION,
            "action": "skipped_not_improvement",
            "action_code": action_code,
            "policy": policy,
            "trigger_role": role,
            "side": side,
            "entry": entry,
            "original_stop": original_stop,
            "current_stop": current_stop,
            "candidate_stop": candidate_stop,
            "new_stop": current_stop,
            "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        }

    return {
        "version": PHASE18_ADAPTIVE_STOP_MODEL_VERSION,
        "action": "adaptive_stop_updated",
        "action_code": action_code,
        "policy": policy,
        "trigger_role": role,
        "side": side,
        "entry": entry,
        "original_stop": original_stop,
        "old_stop": current_stop,
        "candidate_stop": candidate_stop,
        "new_stop": candidate_stop,
        "remaining_size": float(position.get("qty") or 0.0),
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
    }
