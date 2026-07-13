"""
Phase 4 Step 9 — proposed entry / stop-loss / take-profit levels.

This module ports v1 StopTPCalculator behavior to MarketSnapshot v2.

It builds a strategy proposal only. It does not size positions, approve risk, or
execute orders.
"""

from __future__ import annotations

from typing import Any

from snapshot_v1_adapter import (
    get_indicator,
    get_structure_value,
    get_volatility_value,
    latest_close,
    safe_float,
)

PROPOSED_TRADE_BUILDER_VERSION = "phase4_step9_v1_proposed_trade_levels"

ATR_STOP_MULTIPLIER = 2.5
MAX_STOP_ATR_DISTANCE = 3.0

TP1_RATIO = 1.5
TP1_CLOSE_PERCENT = 50
TP2_RATIO = 2.5
TP2_CLOSE_PERCENT = 30
TP3_RATIO = 3.5
TP3_CLOSE_PERCENT = 20

ENTRY_ORDER_TYPE_DEFAULT = "limit"


def smart_round(price: float) -> float:
    if price < 0.01:
        return round(price, 8)
    if price < 0.1:
        return round(price, 6)
    if price < 1:
        return round(price, 5)
    if price < 10:
        return round(price, 4)
    if price < 100:
        return round(price, 3)
    return round(price, 2)


def _atr(snapshot: dict[str, Any]) -> float:
    value = get_indicator(snapshot, "primary", "atr_14", None)
    if value is None:
        value = get_indicator(snapshot, "primary", "atr", None)
    if value is None:
        value = get_volatility_value(snapshot, "primary", "atr", 0.0)
    return safe_float(value, 0.0)


def _entry_price(snapshot: dict[str, Any], direction: str, entry_order_type: str = ENTRY_ORDER_TYPE_DEFAULT) -> float:
    # Strategy proposal uses latest 5m close as the snapshot-native entry anchor.
    # Risk/Execution may later reprice or reject.
    price = latest_close(snapshot, "entry")
    if price > 0:
        return smart_round(price)

    # Fallback to primary close if entry timeframe latest close is unavailable.
    return smart_round(latest_close(snapshot, "primary"))


def _structure_stop_candidate(snapshot: dict[str, Any], direction: str, entry_price: float, atr: float) -> tuple[float, str, dict[str, Any]]:
    buffer = atr * ATR_STOP_MULTIPLIER

    if direction == "long":
        swing_low = safe_float(get_structure_value(snapshot, "primary", "swing_low", 0.0), 0.0)
        if swing_low > 0:
            return swing_low - buffer, "swing_low_with_atr_buffer", {
                "swing_low": swing_low,
                "structure_buffer": buffer,
            }

        return entry_price - (atr * ATR_STOP_MULTIPLIER * 1.5), "atr_fallback_no_swing_low", {
            "swing_low": None,
            "structure_buffer": buffer,
        }

    swing_high = safe_float(get_structure_value(snapshot, "primary", "swing_high", 0.0), 0.0)
    if swing_high > 0:
        return swing_high + buffer, "swing_high_with_atr_buffer", {
            "swing_high": swing_high,
            "structure_buffer": buffer,
        }

    return entry_price + (atr * ATR_STOP_MULTIPLIER * 1.5), "atr_fallback_no_swing_high", {
        "swing_high": None,
        "structure_buffer": buffer,
    }


def calculate_stop_loss(snapshot: dict[str, Any], direction: str, entry_price: float, symbol: str = "") -> tuple[float, dict[str, Any]]:
    direction = str(direction or "").lower()
    atr = _atr(snapshot)

    details = {
        "symbol": str(symbol or "").upper(),
        "direction": direction,
        "entry_price": entry_price,
        "atr": atr,
        "atr_stop_multiplier": ATR_STOP_MULTIPLIER,
        "max_stop_atr_distance": MAX_STOP_ATR_DISTANCE,
    }

    if entry_price <= 0 or atr <= 0:
        details["method"] = "invalid_entry_or_atr"
        return 0.0, details

    stop_loss, method, method_details = _structure_stop_candidate(snapshot, direction, entry_price, atr)
    details["method"] = method
    details.update(method_details)

    max_stop_dist = atr * MAX_STOP_ATR_DISTANCE
    capped = False

    if direction == "long" and (entry_price - stop_loss) > max_stop_dist:
        stop_loss = entry_price - max_stop_dist
        capped = True
    elif direction == "short" and (stop_loss - entry_price) > max_stop_dist:
        stop_loss = entry_price + max_stop_dist
        capped = True

    details["capped_to_max_atr_distance"] = capped
    details["raw_stop_loss_before_round"] = stop_loss
    details["risk_per_unit"] = abs(entry_price - stop_loss)

    return smart_round(stop_loss), details


def _tp_ratios_for_regime(regime: str) -> tuple[float, float, float, str]:
    regime = str(regime or "").strip()

    if regime in ("trending", "strong_trend", "Uptrend", "Downtrend"):
        return TP1_RATIO, TP2_RATIO, TP3_RATIO, "full_targets_trending"

    if regime == "high_volatility":
        return TP1_RATIO * 0.8, TP2_RATIO * 0.8, TP3_RATIO * 0.8, "tight_targets_high_volatility"

    return TP1_RATIO * 0.6, TP2_RATIO * 0.6, TP3_RATIO * 0.6, "scalp_targets_choppy_low_volatility_or_mean_reversion"


def calculate_take_profits(
    entry_price: float,
    stop_loss: float,
    direction: str,
    regime: str = "trending",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    direction = str(direction or "").lower()
    tp1_ratio, tp2_ratio, tp3_ratio, regime_policy = _tp_ratios_for_regime(regime)

    if direction == "long":
        risk = entry_price - stop_loss
        tps = {
            "tp1": {
                "price": smart_round(entry_price + (risk * tp1_ratio)),
                "close_percent": TP1_CLOSE_PERCENT,
                "ratio": tp1_ratio,
            },
            "tp2": {
                "price": smart_round(entry_price + (risk * tp2_ratio)),
                "close_percent": TP2_CLOSE_PERCENT,
                "ratio": tp2_ratio,
            },
            "tp3": {
                "price": smart_round(entry_price + (risk * tp3_ratio)),
                "close_percent": TP3_CLOSE_PERCENT,
                "ratio": tp3_ratio,
            },
        }
    else:
        risk = stop_loss - entry_price
        tps = {
            "tp1": {
                "price": smart_round(entry_price - (risk * tp1_ratio)),
                "close_percent": TP1_CLOSE_PERCENT,
                "ratio": tp1_ratio,
            },
            "tp2": {
                "price": smart_round(entry_price - (risk * tp2_ratio)),
                "close_percent": TP2_CLOSE_PERCENT,
                "ratio": tp2_ratio,
            },
            "tp3": {
                "price": smart_round(entry_price - (risk * tp3_ratio)),
                "close_percent": TP3_CLOSE_PERCENT,
                "ratio": tp3_ratio,
            },
        }

    details = {
        "regime": regime,
        "regime_policy": regime_policy,
        "risk_per_unit": abs(entry_price - stop_loss),
        "tp_ratios": {
            "tp1": tp1_ratio,
            "tp2": tp2_ratio,
            "tp3": tp3_ratio,
        },
        "close_percents": {
            "tp1": TP1_CLOSE_PERCENT,
            "tp2": TP2_CLOSE_PERCENT,
            "tp3": TP3_CLOSE_PERCENT,
        },
    }

    return tps, details


def build_proposed_trade(
    snapshot: dict[str, Any],
    *,
    symbol: str,
    direction: str,
    selected_strategy: str,
    regime: str,
    score: float | None = None,
    entry_order_type: str = ENTRY_ORDER_TYPE_DEFAULT,
) -> dict[str, Any]:
    direction = str(direction or "").lower()
    entry_order_type = str(entry_order_type or ENTRY_ORDER_TYPE_DEFAULT).lower()

    entry_price = _entry_price(snapshot, direction, entry_order_type)
    stop_loss, stop_details = calculate_stop_loss(snapshot, direction, entry_price, symbol)
    take_profits, tp_details = calculate_take_profits(entry_price, stop_loss, direction, regime)

    risk_per_unit = abs(entry_price - stop_loss) if entry_price > 0 and stop_loss > 0 else 0.0

    valid = (
        direction in ("long", "short")
        and entry_price > 0
        and stop_loss > 0
        and risk_per_unit > 0
        and bool(take_profits)
    )

    invalid_reasons = []
    if direction not in ("long", "short"):
        invalid_reasons.append("INVALID_DIRECTION")
    if entry_price <= 0:
        invalid_reasons.append("INVALID_ENTRY_PRICE")
    if stop_loss <= 0:
        invalid_reasons.append("INVALID_STOP_LOSS")
    if risk_per_unit <= 0:
        invalid_reasons.append("INVALID_RISK_PER_UNIT")

    return {
        "builder_version": PROPOSED_TRADE_BUILDER_VERSION,
        "valid": valid,
        "invalid_reasons": invalid_reasons,
        "symbol": str(symbol or "").upper(),
        "selected_strategy": selected_strategy,
        "direction": direction,
        "position_side": direction,
        "entry_order_type": entry_order_type,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profits": take_profits,
        "risk_per_unit": smart_round(risk_per_unit),
        "score": score,
        "invalidation_reference": stop_details.get("method"),
        "notes": [
            "Strategy Engine proposes levels only.",
            "Risk Engine owns sizing and approval.",
            "Trade Guardian owns final safety gate.",
            "Execution may reprice or reject the order.",
        ],
        "details": {
            "stop_loss": stop_details,
            "take_profits": tp_details,
        },
    }


def build_proposed_trade_contract() -> dict[str, Any]:
    return {
        "builder_version": PROPOSED_TRADE_BUILDER_VERSION,
        "v1_source": "src/strategy/stop_tp_calculator.py",
        "atr_stop_multiplier": ATR_STOP_MULTIPLIER,
        "max_stop_atr_distance": MAX_STOP_ATR_DISTANCE,
        "tp_ratios": {
            "tp1": TP1_RATIO,
            "tp2": TP2_RATIO,
            "tp3": TP3_RATIO,
        },
        "tp_close_percents": {
            "tp1": TP1_CLOSE_PERCENT,
            "tp2": TP2_CLOSE_PERCENT,
            "tp3": TP3_CLOSE_PERCENT,
        },
        "entry_price_source": "latest entry timeframe close; execution may reprice",
        "does_not_size_positions": True,
        "does_not_approve_risk": True,
        "does_not_execute": True,
    }
