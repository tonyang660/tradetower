from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_STOP_LOSS_MODEL_VERSION = "phase18g_stop_loss_missed_stop_simulation"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class StopLossSimulationConfig:
    stop_reprice_buffer_bps: float = 10.0
    max_stop_reprice_buffer_bps: float = 50.0
    version: str = PHASE18_STOP_LOSS_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "StopLossSimulationConfig":
        return cls(
            stop_reprice_buffer_bps=_clamp(_float(config.get("stop_reprice_buffer_bps"), 10.0), 0.0, 50.0),
            max_stop_reprice_buffer_bps=50.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stop_loss_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = StopLossSimulationConfig.from_config(config or {})
    return {
        "version": PHASE18_STOP_LOSS_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "Stop losses are modeled as protective stop-limit exits.",
            "If the candle closes beyond the original stop, the stop is treated as missed/breached and repriced through the latest close with a buffer.",
            "Repriced stop exits are urgent exits and use taker fee logic.",
            "This mirrors the paper-production stop-reprice behavior introduced before Phase 18.",
        ],
    }


def simulate_stop_loss_exit(
    *,
    position_side: str,
    original_stop_price: float,
    latest_price: float,
    requested_size: float,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = StopLossSimulationConfig.from_config(config)
    side = str(position_side).lower()
    original_stop_price = float(original_stop_price)
    latest_price = float(latest_price)
    requested_size = float(requested_size)
    buffer = cfg.stop_reprice_buffer_bps / 10000.0

    if side == "long":
        stop_is_breached = latest_price <= original_stop_price
        candidate_price = latest_price * (1.0 - buffer) if stop_is_breached else original_stop_price
        filled_price = min(original_stop_price, candidate_price)
        exit_side = "sell"
    elif side == "short":
        stop_is_breached = latest_price >= original_stop_price
        candidate_price = latest_price * (1.0 + buffer) if stop_is_breached else original_stop_price
        filled_price = max(original_stop_price, candidate_price)
        exit_side = "buy"
    else:
        raise ValueError(f"unsupported_position_side: {position_side}")

    action = "repriced_stop_fill" if stop_is_breached else "stop_limit_fill"
    price_impact = filled_price - original_stop_price

    return {
        "version": PHASE18_STOP_LOSS_MODEL_VERSION,
        "action": action,
        "execution_type": "exit",
        "order_type": "stop_limit_exit",
        "liquidity": "taker",
        "position_side": side,
        "side": exit_side,
        "original_stop_price": original_stop_price,
        "latest_price": latest_price,
        "requested_price": original_stop_price,
        "filled_price": filled_price,
        "requested_size": requested_size,
        "filled_size": requested_size,
        "unfilled_size": 0.0,
        "partial_fill": False,
        "fill_ratio": 1.0,
        "stop_is_breached": stop_is_breached,
        "stop_reprice_buffer_bps": cfg.stop_reprice_buffer_bps,
        "price_impact": price_impact,
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        "reason": "STOP_LOSS",
    }
