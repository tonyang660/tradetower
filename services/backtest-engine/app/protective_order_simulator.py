from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


PHASE18_PROTECTIVE_ORDER_MODEL_VERSION = "phase18e_protective_orders_repriced_to_actual_entry"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class ProtectiveOrderModelConfig:
    tp1_close_pct: float = 50.0
    tp2_close_pct: float = 30.0
    tp3_close_pct: float = 20.0
    stop_order_type: str = "protective_limit"
    take_profit_order_type: str = "limit_exit"
    version: str = PHASE18_PROTECTIVE_ORDER_MODEL_VERSION

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ProtectiveOrderModelConfig":
        return cls(
            tp1_close_pct=_float(config.get("tp1_close_pct"), 50.0),
            tp2_close_pct=_float(config.get("tp2_close_pct"), 30.0),
            tp3_close_pct=_float(config.get("tp3_close_pct"), 20.0),
            stop_order_type=str(config.get("protective_stop_order_type", "protective_limit")),
            take_profit_order_type=str(config.get("take_profit_order_type", "limit_exit")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def protective_order_model_contract(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ProtectiveOrderModelConfig.from_config(config or {})
    return {
        "version": PHASE18_PROTECTIVE_ORDER_MODEL_VERSION,
        "config": cfg.to_dict(),
        "notes": [
            "Protective orders are created when a backtest position opens.",
            "SL and TP levels are repriced from the actual filled entry price.",
            "This matters when a limit entry fills later or when market fallback changes the entry price.",
            "TP1/TP2/TP3 are created as resting limit-exit metadata; Phase 18F will execute partial TPs.",
            "Stop-loss is created as resting protective metadata; Phase 18G will execute missed-stop behavior.",
        ],
    }


def reprice_levels_to_actual_entry(
    *,
    side: str,
    planned_entry: float,
    actual_entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    tp3: float,
) -> dict[str, Any]:
    side = str(side).lower()
    planned_entry = float(planned_entry)
    actual_entry = float(actual_entry)
    stop = float(stop)
    tp1 = float(tp1)
    tp2 = float(tp2)
    tp3 = float(tp3)

    stop_distance = abs(planned_entry - stop)
    tp1_distance = abs(tp1 - planned_entry)
    tp2_distance = abs(tp2 - planned_entry)
    tp3_distance = abs(tp3 - planned_entry)

    if side == "long":
        repriced_stop = actual_entry - stop_distance
        repriced_tp1 = actual_entry + tp1_distance
        repriced_tp2 = actual_entry + tp2_distance
        repriced_tp3 = actual_entry + tp3_distance
    elif side == "short":
        repriced_stop = actual_entry + stop_distance
        repriced_tp1 = actual_entry - tp1_distance
        repriced_tp2 = actual_entry - tp2_distance
        repriced_tp3 = actual_entry - tp3_distance
    else:
        raise ValueError(f"unsupported_position_side: {side}")

    return {
        "version": PHASE18_PROTECTIVE_ORDER_MODEL_VERSION,
        "side": side,
        "planned_entry": planned_entry,
        "actual_entry": actual_entry,
        "entry_delta": actual_entry - planned_entry,
        "original_levels": {
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
        },
        "distances": {
            "stop": stop_distance,
            "tp1": tp1_distance,
            "tp2": tp2_distance,
            "tp3": tp3_distance,
        },
        "repriced_levels": {
            "stop": repriced_stop,
            "tp1": repriced_tp1,
            "tp2": repriced_tp2,
            "tp3": repriced_tp3,
        },
    }


def build_protective_orders_for_position(
    *,
    run_id: int,
    position_id: int,
    symbol: str,
    side: str,
    entry_price: float,
    size: float,
    stop: float,
    tp1: float,
    tp2: float,
    tp3: float,
    timestamp,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    cfg = ProtectiveOrderModelConfig.from_config(config)
    side = str(side).lower()
    exit_side = "sell" if side == "long" else "buy"

    size = float(size)
    tp1_size = round(size * (cfg.tp1_close_pct / 100.0), 12)
    tp2_size = round(size * (cfg.tp2_close_pct / 100.0), 12)
    tp3_size = round(max(size - tp1_size - tp2_size, 0.0), 12)

    common = {
        "version": PHASE18_PROTECTIVE_ORDER_MODEL_VERSION,
        "run_id": int(run_id),
        "position_id": int(position_id),
        "symbol": symbol,
        "position_side": side,
        "side": exit_side,
        "created_at": timestamp,
        "entry_price": float(entry_price),
        "status": "open",
    }

    return [
        {
            **common,
            "role": "stop_loss",
            "order_type": cfg.stop_order_type,
            "requested_price": float(stop),
            "requested_size": size,
            "reason": "PROTECTIVE_STOP_CREATED",
        },
        {
            **common,
            "role": "tp1",
            "order_type": cfg.take_profit_order_type,
            "requested_price": float(tp1),
            "requested_size": tp1_size,
            "close_pct": cfg.tp1_close_pct,
            "reason": "TP1_CREATED",
        },
        {
            **common,
            "role": "tp2",
            "order_type": cfg.take_profit_order_type,
            "requested_price": float(tp2),
            "requested_size": tp2_size,
            "close_pct": cfg.tp2_close_pct,
            "reason": "TP2_CREATED",
        },
        {
            **common,
            "role": "tp3",
            "order_type": cfg.take_profit_order_type,
            "requested_price": float(tp3),
            "requested_size": tp3_size,
            "close_pct": cfg.tp3_close_pct,
            "reason": "TP3_CREATED",
        },
    ]
