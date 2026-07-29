from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_SL2_MODEL_VERSION = "phase18h_sl2_support_foundation"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class SecondaryStopConfig:
    enabled: bool = True
    default_close_pct: float = 50.0
    version: str = PHASE18_SL2_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SecondaryStopConfig":
        enabled = bool(config.get("sl2_enabled", True))
        close_pct = max(0.0, min(100.0, _float(config.get("sl2_default_close_pct"), 50.0)))
        return cls(enabled=enabled, default_close_pct=close_pct)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sl2_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = SecondaryStopConfig.from_config(config or {})
    return {
        "version": PHASE18_SL2_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "SL2 is a secondary protective stop slot for later lifecycle phases.",
            "18H adds state, helper functions, and diagnostics only.",
            "18I/18J/18K can activate SL2 for adaptive stop, regime-change, or emergency exits.",
            "SL2 should not change trade outcomes until a later phase activates it.",
        ],
    }


def initialize_sl2_state(position: dict[str, Any]) -> dict[str, Any]:
    position.setdefault("sl2", None)
    position.setdefault("sl2_order_id", None)
    position.setdefault("sl2_events", [])
    position.setdefault("sl2_active", False)
    return position


def build_sl2_order_payload(
    *,
    run_id: int,
    position: dict[str, Any],
    trigger_reason: str,
    stop_price: float,
    close_pct: float,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = SecondaryStopConfig.from_config(config)
    remaining_qty = float(position.get("qty") or 0.0)
    close_pct = max(0.0, min(100.0, float(close_pct)))
    requested_size = remaining_qty * (close_pct / 100.0)
    if close_pct >= 99.999:
        requested_size = remaining_qty

    side = str(position["side"]).lower()
    order_side = "sell" if side == "long" else "buy"

    return {
        "version": PHASE18_SL2_MODEL_VERSION,
        "enabled": cfg.enabled,
        "run_id": run_id,
        "position_id": position.get("position_id"),
        "symbol": position["symbol"],
        "position_side": side,
        "side": order_side,
        "role": "sl2",
        "order_type": "protective_limit",
        "status": "open",
        "reason": "SL2_CREATED",
        "trigger_reason": trigger_reason,
        "requested_price": float(stop_price),
        "requested_size": max(0.0, requested_size),
        "close_pct": close_pct,
        "timestamp": timestamp,
    }


def mark_sl2_activated(position: dict[str, Any], *, order_id: int, order_payload: dict[str, Any], timestamp) -> dict[str, Any]:
    position["sl2"] = order_payload
    position["sl2_order_id"] = int(order_id)
    position["sl2_active"] = True
    position.setdefault("sl2_events", []).append({
        "event": "SL2_ACTIVATED",
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        "order_id": int(order_id),
        "order": order_payload,
    })
    return position


def sl2_touched(*, side: str, stop_price: float, candle_high: float, candle_low: float) -> bool:
    if str(side).lower() == "long":
        return float(candle_low) <= float(stop_price)
    if str(side).lower() == "short":
        return float(candle_high) >= float(stop_price)
    return False
