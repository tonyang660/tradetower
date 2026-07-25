from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


PHASE18_FILL_MODEL_VERSION = "phase18c_fill_model_spread_slippage_fees"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class FillModelConfig:
    spread_bps: float = 0.0
    entry_slippage_bps: float = 0.0
    exit_slippage_bps: float = 0.0
    market_fill_ratio: float = 1.0
    partial_fill_enabled: bool = False
    version: str = PHASE18_FILL_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FillModelConfig":
        base_slippage = _float(config.get("slippage_bps"), 0.0)
        return cls(
            spread_bps=max(0.0, _float(config.get("spread_bps"), 0.0)),
            entry_slippage_bps=max(0.0, _float(config.get("entry_slippage_bps"), base_slippage)),
            exit_slippage_bps=max(0.0, _float(config.get("exit_slippage_bps"), base_slippage)),
            market_fill_ratio=_clamp(_float(config.get("market_fill_ratio"), 1.0), 0.0, 1.0),
            partial_fill_enabled=bool(config.get("partial_fill_enabled", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _side_multiplier_for_market_fill(*, position_side: str, execution_type: str) -> int:
    side = str(position_side).lower()
    kind = str(execution_type).lower()

    if kind == "entry":
        return 1 if side == "long" else -1
    if kind == "exit":
        return -1 if side == "long" else 1

    raise ValueError(f"unsupported_execution_type: {execution_type}")


def simulate_market_fill(
    *,
    config: dict[str, Any],
    position_side: str,
    execution_type: str,
    requested_price: float,
    requested_size: float,
    timestamp=None,
    reason: str | None = None,
) -> dict[str, Any]:
    fill_config = FillModelConfig.from_config(config)
    multiplier = _side_multiplier_for_market_fill(
        position_side=position_side,
        execution_type=execution_type,
    )

    slip_bps = (
        fill_config.entry_slippage_bps
        if str(execution_type).lower() == "entry"
        else fill_config.exit_slippage_bps
    )
    half_spread_bps = fill_config.spread_bps / 2.0
    total_adverse_bps = slip_bps + half_spread_bps
    filled_price = float(requested_price) * (1.0 + multiplier * total_adverse_bps / 10000.0)

    requested_size = float(requested_size)
    if fill_config.partial_fill_enabled:
        filled_size = round(requested_size * fill_config.market_fill_ratio, 12)
    else:
        filled_size = requested_size

    filled_size = max(0.0, min(requested_size, filled_size))
    unfilled_size = max(0.0, requested_size - filled_size)

    return {
        "ok": True,
        "version": PHASE18_FILL_MODEL_VERSION,
        "execution_type": str(execution_type).lower(),
        "liquidity": "taker",
        "position_side": str(position_side).lower(),
        "requested_price": float(requested_price),
        "filled_price": float(filled_price),
        "requested_size": requested_size,
        "filled_size": filled_size,
        "unfilled_size": unfilled_size,
        "partial_fill": bool(unfilled_size > 0),
        "fill_ratio": (filled_size / requested_size) if requested_size else 0.0,
        "spread_bps": fill_config.spread_bps,
        "half_spread_bps": half_spread_bps,
        "slippage_bps": slip_bps,
        "total_adverse_bps": total_adverse_bps,
        "price_impact": float(filled_price) - float(requested_price),
        "timestamp": timestamp,
        "reason": reason,
        "config": fill_config.to_dict(),
    }


def simulate_market_entry_fill(*, config: dict[str, Any], position_side: str, requested_price: float, requested_size: float, timestamp=None, reason: str = "STRATEGY_ENTRY") -> dict[str, Any]:
    return simulate_market_fill(
        config=config,
        position_side=position_side,
        execution_type="entry",
        requested_price=requested_price,
        requested_size=requested_size,
        timestamp=timestamp,
        reason=reason,
    )


def simulate_market_exit_fill(*, config: dict[str, Any], position_side: str, requested_price: float, requested_size: float, timestamp=None, reason: str = "EXIT") -> dict[str, Any]:
    return simulate_market_fill(
        config=config,
        position_side=position_side,
        execution_type="exit",
        requested_price=requested_price,
        requested_size=requested_size,
        timestamp=timestamp,
        reason=reason,
    )


def fill_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    fill_config = FillModelConfig.from_config(config or {})
    return {
        "version": PHASE18_FILL_MODEL_VERSION,
        "config": fill_config.to_dict(),
        "supported_liquidity": ["maker", "taker"],
        "supported_order_types": ["market"],
        "notes": [
            "Phase 18C models spread, slippage, fee liquidity type, and partial-fill metadata.",
            "Market fills are taker liquidity.",
            "By default market_fill_ratio is 1.0 and partial_fill_enabled is false.",
            "Phase 18D will use this model for resting entry order simulation.",
        ],
    }
