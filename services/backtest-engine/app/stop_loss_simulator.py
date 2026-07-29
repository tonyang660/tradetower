from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

PHASE18_STOP_LOSS_MODEL_VERSION = "phase18g_hf1_stop_limit_maker_then_market_fallback"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class StopLossSimulationConfig:
    stop_reprice_buffer_bps: float = 10.0
    stop_limit_max_reprice_attempts: int = 3
    version: str = PHASE18_STOP_LOSS_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "StopLossSimulationConfig":
        return cls(
            stop_reprice_buffer_bps=_clamp(_float(config.get("stop_reprice_buffer_bps"), 10.0), 0.0, 50.0),
            stop_limit_max_reprice_attempts=max(0, _int(config.get("stop_limit_max_reprice_attempts"), 3)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stop_loss_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = StopLossSimulationConfig.from_config(config or {})
    return {
        "version": PHASE18_STOP_LOSS_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "Protective stop-limit fills at the stop price use maker fees.",
            "If price closes beyond the stop, the backtest records repricing attempts instead of instantly filling.",
            "After max reprice attempts, the position falls back to a market stop-loss exit using taker fees.",
            "Limit-order fill ratios are not used for stop-loss exits.",
        ],
    }


def _stop_is_breached(*, side: str, original_stop_price: float, latest_price: float) -> bool:
    if side == "long":
        return float(latest_price) <= float(original_stop_price)
    if side == "short":
        return float(latest_price) >= float(original_stop_price)
    raise ValueError(f"unsupported_position_side: {side}")


def _repriced_limit(*, side: str, latest_price: float, buffer_bps: float) -> float:
    buffer = float(buffer_bps) / 10000.0
    if side == "long":
        return float(latest_price) * (1.0 - buffer)
    if side == "short":
        return float(latest_price) * (1.0 + buffer)
    raise ValueError(f"unsupported_position_side: {side}")


def evaluate_stop_loss_order(
    *,
    position: dict[str, Any],
    original_stop_price: float,
    latest_price: float,
    requested_size: float,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = StopLossSimulationConfig.from_config(config)
    side = str(position["side"]).lower()
    original_stop_price = float(original_stop_price)
    latest_price = float(latest_price)
    requested_size = float(requested_size)
    prior_state = dict(position.get("stop_loss_state") or {})
    prior_attempts = int(prior_state.get("reprice_attempts", 0) or 0)

    breached = _stop_is_breached(side=side, original_stop_price=original_stop_price, latest_price=latest_price)
    exit_side = "sell" if side == "long" else "buy"

    base = {
        "version": PHASE18_STOP_LOSS_MODEL_VERSION,
        "execution_type": "exit",
        "position_side": side,
        "side": exit_side,
        "original_stop_price": original_stop_price,
        "latest_price": latest_price,
        "requested_size": requested_size,
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
        "stop_is_breached": breached,
        "stop_reprice_buffer_bps": cfg.stop_reprice_buffer_bps,
        "max_reprice_attempts": cfg.stop_limit_max_reprice_attempts,
        "reason": "STOP_LOSS",
    }

    if not breached:
        state = {
            **prior_state,
            "status": "filled",
            "reprice_attempts": prior_attempts,
            "last_event": "stop_limit_fill",
            "last_update": base["timestamp"],
        }
        return {
            **base,
            "action": "stop_limit_fill",
            "order_type": "stop_limit_exit",
            "liquidity": "maker",
            "requested_price": original_stop_price,
            "filled_price": original_stop_price,
            "filled_size": requested_size,
            "unfilled_size": 0.0,
            "partial_fill": False,
            "fill_ratio": 1.0,
            "price_impact": 0.0,
            "state": state,
        }

    reprice_attempts = prior_attempts + 1
    repriced_price = _repriced_limit(side=side, latest_price=latest_price, buffer_bps=cfg.stop_reprice_buffer_bps)
    state = {
        **prior_state,
        "status": "repricing",
        "reprice_attempts": reprice_attempts,
        "last_repriced_limit": repriced_price,
        "last_latest_price": latest_price,
        "last_event": "repriced_stop_limit_attempt",
        "last_update": base["timestamp"],
    }

    if reprice_attempts <= cfg.stop_limit_max_reprice_attempts:
        return {
            **base,
            "action": "repriced_stop_limit_attempt",
            "order_type": "stop_limit_exit",
            "liquidity": "maker",
            "requested_price": repriced_price,
            "filled_price": None,
            "filled_size": 0.0,
            "unfilled_size": requested_size,
            "partial_fill": False,
            "fill_ratio": 0.0,
            "price_impact": repriced_price - original_stop_price,
            "state": state,
        }

    state = {
        **state,
        "status": "market_fallback",
        "last_event": "market_stop_fallback",
    }
    return {
        **base,
        "action": "market_stop_fallback",
        "order_type": "market_exit",
        "liquidity": "taker",
        "requested_price": latest_price,
        "filled_price": None,
        "filled_size": 0.0,
        "unfilled_size": requested_size,
        "partial_fill": False,
        "fill_ratio": 0.0,
        "price_impact": latest_price - original_stop_price,
        "state": state,
    }
