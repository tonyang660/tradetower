from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


PHASE18_ENTRY_ORDER_MODEL_VERSION = "phase18d_hf1_limit_entry_with_15_attempt_market_fallback"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class EntryOrderModelConfig:
    entry_order_preference: str = "limit"
    entry_limit_max_wait_attempts: int = 15
    entry_market_fallback_enabled: bool = True
    partial_fill_enabled: bool = False
    limit_order_fill_ratio: float = 1.0
    version: str = PHASE18_ENTRY_ORDER_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "EntryOrderModelConfig":
        attempts = config.get(
            "entry_limit_max_wait_attempts",
            config.get("entry_limit_max_wait_cycles", 15),
        )
        return cls(
            entry_order_preference=str(config.get("entry_order_preference", "limit")).lower(),
            entry_limit_max_wait_attempts=max(1, int(attempts)),
            entry_market_fallback_enabled=_bool(config.get("entry_market_fallback_enabled"), True),
            partial_fill_enabled=_bool(config.get("partial_fill_enabled"), False),
            limit_order_fill_ratio=max(0.0, min(1.0, _float(config.get("limit_order_fill_ratio"), 1.0))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def entry_order_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = EntryOrderModelConfig.from_config(config or {})
    return {
        "version": PHASE18_ENTRY_ORDER_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "Limit entry orders are preferred by default.",
            "The default wait is 15 virtual 1m execution attempts.",
            "With 5m source candles and virtual 1m execution, 15 attempts equals 3 source candles.",
            "After 15 attempts, market fallback is enabled by default.",
        ],
    }


def build_pending_limit_entry_order(
    *,
    run_id: int,
    symbol: str,
    side: str,
    limit_price: float,
    requested_size: float,
    created_cycle_index: int,
    created_at,
    plan: dict[str, Any],
    decision: dict[str, Any],
    guard: dict[str, Any],
    execution_slots: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = EntryOrderModelConfig.from_config(config)
    order_side = "buy" if side == "long" else "sell"
    return {
        "version": PHASE18_ENTRY_ORDER_MODEL_VERSION,
        "run_id": run_id,
        "symbol": symbol,
        "side": side,
        "order_side": order_side,
        "role": "entry",
        "order_type": "limit_entry",
        "status": "open",
        "limit_price": float(limit_price),
        "requested_size": float(requested_size),
        "filled_size": 0.0,
        "remaining_size": float(requested_size),
        "created_cycle_index": int(created_cycle_index),
        "created_at": created_at,
        "max_wait_attempts": cfg.entry_limit_max_wait_attempts,
        "market_fallback_enabled": cfg.entry_market_fallback_enabled,
        "plan": plan,
        "decision": decision,
        "guard": guard,
        "execution_slots": execution_slots,
        "lifecycle": {
            "version": PHASE18_ENTRY_ORDER_MODEL_VERSION,
            "role": "entry",
            "order_type": "limit_entry",
            "side": order_side,
            "requested_price": float(limit_price),
            "requested_size": float(requested_size),
            "status": "open",
            "events": [
                {"status": "created", "timestamp": created_at, "details": {"reason": "STRATEGY_ENTRY_LIMIT"}},
                {"status": "submitted", "timestamp": created_at, "details": {"reason": "STRATEGY_ENTRY_LIMIT"}},
                {"status": "open", "timestamp": created_at, "details": {"reason": "AWAITING_LIMIT_FILL", "max_wait_attempts": cfg.entry_limit_max_wait_attempts}},
            ],
        },
    }


def _limit_touched(*, side: str, limit_price: float, candle_high: float, candle_low: float) -> bool:
    if side == "long":
        return float(candle_low) <= float(limit_price)
    if side == "short":
        return float(candle_high) >= float(limit_price)
    return False


def evaluate_pending_entry_order(
    *,
    order: dict[str, Any],
    candle_high: float,
    candle_low: float,
    cycle_index: int,
    timestamp,
    config: dict[str, Any],
) -> dict[str, Any]:
    cfg = EntryOrderModelConfig.from_config(config)
    source_age_cycles = max(0, int(cycle_index) - int(order.get("created_cycle_index", cycle_index)))
    virtual_steps_per_cycle = max(1, int(config.get("virtual_execution_steps_per_decision", 1) or 1))
    age_attempts = source_age_cycles * virtual_steps_per_cycle

    limit_price = float(order["limit_price"])
    requested_size = float(order["requested_size"])
    side = str(order["side"]).lower()

    if _limit_touched(side=side, limit_price=limit_price, candle_high=candle_high, candle_low=candle_low):
        if cfg.partial_fill_enabled:
            filled_size = max(0.0, min(requested_size, requested_size * cfg.limit_order_fill_ratio))
        else:
            filled_size = requested_size

        status = "filled" if filled_size >= requested_size else "partially_filled"
        return {
            "action": "filled",
            "status": status,
            "liquidity": "maker",
            "filled_price": limit_price,
            "filled_size": filled_size,
            "remaining_size": max(0.0, requested_size - filled_size),
            "source_age_cycles": source_age_cycles,
            "age_attempts": age_attempts,
            "timestamp": timestamp,
            "fill_model": {
                "version": PHASE18_ENTRY_ORDER_MODEL_VERSION,
                "execution_type": "entry",
                "order_type": "limit_entry",
                "liquidity": "maker",
                "position_side": side,
                "requested_price": limit_price,
                "filled_price": limit_price,
                "requested_size": requested_size,
                "filled_size": filled_size,
                "unfilled_size": max(0.0, requested_size - filled_size),
                "partial_fill": filled_size < requested_size,
                "fill_ratio": (filled_size / requested_size) if requested_size else 0.0,
                "spread_bps": 0.0,
                "slippage_bps": 0.0,
                "total_adverse_bps": 0.0,
                "price_impact": 0.0,
                "reason": "LIMIT_ENTRY_TOUCHED",
            },
        }

    if age_attempts >= int(order.get("max_wait_attempts", cfg.entry_limit_max_wait_attempts)):
        if cfg.entry_market_fallback_enabled:
            return {
                "action": "market_fallback",
                "status": "expired",
                "source_age_cycles": source_age_cycles,
                "age_attempts": age_attempts,
                "timestamp": timestamp,
                "reason": "LIMIT_ENTRY_EXPIRED_MARKET_FALLBACK",
            }

        return {
            "action": "expired",
            "status": "expired",
            "source_age_cycles": source_age_cycles,
            "age_attempts": age_attempts,
            "timestamp": timestamp,
            "reason": "LIMIT_ENTRY_EXPIRED",
        }

    return {
        "action": "waiting",
        "status": "open",
        "source_age_cycles": source_age_cycles,
        "age_attempts": age_attempts,
        "timestamp": timestamp,
        "reason": "LIMIT_ENTRY_NOT_TOUCHED",
    }
