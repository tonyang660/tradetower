from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_PARTIAL_TP_MODEL_VERSION = "phase18f_partial_tp_execution"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class PartialTPConfig:
    tp1_close_pct: float = 50.0
    tp2_close_pct: float = 30.0
    tp3_close_pct: float = 20.0
    version: str = PHASE18_PARTIAL_TP_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PartialTPConfig":
        return cls(
            tp1_close_pct=_float(config.get("tp1_close_pct"), 50.0),
            tp2_close_pct=_float(config.get("tp2_close_pct"), 30.0),
            tp3_close_pct=_float(config.get("tp3_close_pct"), 20.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def partial_tp_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = PartialTPConfig.from_config(config or {})
    return {
        "version": PHASE18_PARTIAL_TP_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "TP1 and TP2 execute as partial limit exits.",
            "TP3 closes the remaining position.",
            "TP1/TP2/TP3 are evaluated in order, one target per source candle.",
            "Stop priority remains above TP priority to stay conservative and production-like.",
        ],
    }


def _tp_touched(*, side: str, target: float, candle_high: float, candle_low: float) -> bool:
    if side == "long":
        return float(candle_high) >= float(target)
    if side == "short":
        return float(candle_low) <= float(target)
    return False


def next_triggered_tp(position: dict[str, Any], *, candle_high: float, candle_low: float) -> dict[str, Any] | None:
    side = str(position["side"]).lower()
    filled = set(position.get("partial_tp_filled", []))

    for role in ("tp1", "tp2", "tp3"):
        if role in filled:
            continue
        target = float(position[role])
        if _tp_touched(side=side, target=target, candle_high=candle_high, candle_low=candle_low):
            return {
                "version": PHASE18_PARTIAL_TP_MODEL_VERSION,
                "role": role,
                "target_price": target,
                "side": side,
                "reason": role.upper(),
            }

    return None


def partial_tp_size(position: dict[str, Any], role: str, config: dict[str, Any]) -> float:
    cfg = PartialTPConfig.from_config(config)
    original_qty = float(position.get("original_qty") or position.get("qty") or 0.0)
    remaining_qty = float(position.get("qty") or 0.0)

    if role == "tp1":
        requested = original_qty * (cfg.tp1_close_pct / 100.0)
    elif role == "tp2":
        requested = original_qty * (cfg.tp2_close_pct / 100.0)
    elif role == "tp3":
        requested = remaining_qty
    else:
        requested = 0.0

    return max(0.0, min(remaining_qty, requested))


def realized_gross_for_exit(position: dict[str, Any], exit_price: float, exit_size: float) -> float:
    entry = float(position["entry"])
    side = str(position["side"]).lower()
    if side == "long":
        return (float(exit_price) - entry) * float(exit_size)
    return (entry - float(exit_price)) * float(exit_size)
