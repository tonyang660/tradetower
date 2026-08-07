from __future__ import annotations

from math import isfinite
from typing import Any


PHASE18N_EXECUTION_METRICS_VERSION = "phase18n_execution_metrics_expansion_v1"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _details(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("details_json")
    return value if isinstance(value, dict) else {}


def _nested(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def score_bucket(value: Any) -> str:
    score = _number(value)
    if score is None:
        return "unknown"
    if score < 50:
        return "<50 below observe"
    if score < 75:
        return "50-74 observe"
    if score < 85:
        return "75-84 trade"
    if score < 95:
        return "85-94 strong"
    return "95+ elite"


def trades_with_score_buckets(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **trade,
            "score_bucket": score_bucket(trade.get("strategy_score")),
        }
        for trade in trades
    ]


def _order_liquidity(order: dict[str, Any]) -> str:
    details = _details(order)
    candidates = [
        _nested(details, "fee_details", "liquidity"),
        _nested(details, "fill_model", "liquidity"),
        _nested(details, "entry_order_evaluation", "liquidity"),
        _nested(details, "entry_order_evaluation", "market_fill", "liquidity"),
        _nested(details, "stop_loss_event", "liquidity"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if value in {"maker", "taker"}:
            return value

    order_type = str(order.get("order_type") or "").strip().lower()
    if order_type.startswith("market"):
        return "taker"
    if order_type in {"limit_entry", "limit_exit", "protective_limit", "stop_limit_exit"}:
        return "maker"
    return "unknown"


def _is_entry_order(order: dict[str, Any]) -> bool:
    details = _details(order)
    return bool(
        str(order.get("order_type") or "").lower() == "limit_entry"
        or str(order.get("reason") or "").upper() == "ENTRY_ORDER_SUBMITTED"
        or str(_nested(details, "order_lifecycle", "role") or "").lower() == "entry"
    )


def _is_entry_market_fallback(order: dict[str, Any]) -> bool:
    details = _details(order)
    action = str(_nested(details, "entry_order_evaluation", "action") or "").lower()
    reason = str(_nested(details, "entry_order_evaluation", "reason") or "").upper()
    return action == "market_fallback" or "MARKET_FALLBACK" in reason


def _entry_wait_attempts(order: dict[str, Any]) -> float | None:
    details = _details(order)
    return _number(_nested(details, "entry_order_evaluation", "age_attempts"))


def _stop_action(order: dict[str, Any]) -> str:
    details = _details(order)
    for value in (
        _nested(details, "stop_loss_event", "action"),
        _nested(details, "fill_model", "action"),
    ):
        action = str(value or "").strip().lower()
        if action:
            return action
    return ""


def _sl2_trigger(order: dict[str, Any]) -> str:
    details = _details(order)
    value = str(
        _nested(details, "trigger_reason")
        or order.get("reason")
        or "unknown"
    ).strip().upper()
    if "REGIME" in value:
        return "regime_change"
    if "VOLATILITY" in value:
        return "volatility_spike"
    return "unknown"


def _is_sl2_order(order: dict[str, Any]) -> bool:
    details = _details(order)
    role = str(_nested(details, "role") or "").lower()
    reason = str(order.get("reason") or "").upper()
    return role == "sl2" or reason.endswith("SL2")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def build_execution_metrics(
    *,
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    logs: list[dict[str, Any]],
) -> dict[str, Any]:
    filled_orders = [order for order in orders if str(order.get("status") or "").lower() == "filled"]

    liquidity = {
        "maker": {"fill_count": 0, "fee_total": 0.0},
        "taker": {"fill_count": 0, "fee_total": 0.0},
        "unknown": {"fill_count": 0, "fee_total": 0.0},
    }
    for order in filled_orders:
        bucket = _order_liquidity(order)
        fee = abs(_number(order.get("fee")) or 0.0)
        liquidity[bucket]["fill_count"] += 1
        liquidity[bucket]["fee_total"] += fee

    entry_orders = [order for order in orders if _is_entry_order(order)]
    entry_filled = [order for order in entry_orders if str(order.get("status") or "").lower() == "filled"]
    entry_expired = [order for order in entry_orders if str(order.get("status") or "").lower() == "expired"]
    entry_fallbacks = [order for order in entry_orders if _is_entry_market_fallback(order)]
    wait_attempts = [value for value in (_entry_wait_attempts(order) for order in entry_orders) if value is not None]

    stop_orders = [
        order
        for order in filled_orders
        if "STOP_LOSS" in str(order.get("reason") or "").upper()
        or isinstance(_nested(_details(order), "stop_loss_event"), dict)
    ]
    stop_market_fallbacks = [order for order in stop_orders if _stop_action(order) == "market_stop_fallback"]
    stop_maker_fills = [order for order in stop_orders if _order_liquidity(order) == "maker"]
    stop_reprices = sum(
        1 for log in logs if str(log.get("event_type") or "").upper() == "STOP_LIMIT_REPRICE_ATTEMPT"
    )

    sl2_orders = [order for order in orders if _is_sl2_order(order)]
    sl2_by_trigger: list[dict[str, Any]] = []
    for trigger in ("regime_change", "volatility_spike", "unknown"):
        rows = [order for order in sl2_orders if _sl2_trigger(order) == trigger]
        if not rows:
            continue
        sl2_by_trigger.append(
            {
                "trigger": trigger,
                "created": len(rows),
                "filled": sum(1 for order in rows if str(order.get("status") or "").lower() == "filled"),
            }
        )

    leg_values = [value for value in (_number(trade.get("net_pnl")) for trade in trades) if value is not None]
    position_values = [
        value
        for position in positions
        if str(position.get("status") or "").lower() == "closed"
        for value in [_number(position.get("realized_pnl"))]
        if value is not None
    ]
    leg_wins = sum(1 for value in leg_values if value > 0)
    position_wins = sum(1 for value in position_values if value > 0)

    return {
        "version": PHASE18N_EXECUTION_METRICS_VERSION,
        "liquidity": {
            "maker_fill_count": liquidity["maker"]["fill_count"],
            "maker_fee_total": liquidity["maker"]["fee_total"],
            "taker_fill_count": liquidity["taker"]["fill_count"],
            "taker_fee_total": liquidity["taker"]["fee_total"],
            "unknown_fill_count": liquidity["unknown"]["fill_count"],
            "unknown_fee_total": liquidity["unknown"]["fee_total"],
        },
        "entry_orders": {
            "submitted": len(entry_orders),
            "filled": len(entry_filled),
            "expired": len(entry_expired),
            "market_fallbacks": len(entry_fallbacks),
            "average_wait_attempts": (sum(wait_attempts) / len(wait_attempts)) if wait_attempts else None,
            "wait_attempt_samples": len(wait_attempts),
        },
        "stop_loss": {
            "limit_reprice_attempts": stop_reprices,
            "limit_maker_fills": len(stop_maker_fills),
            "market_fallbacks": len(stop_market_fallbacks),
        },
        "sl2": {
            "created": len(sl2_orders),
            "filled": sum(1 for order in sl2_orders if str(order.get("status") or "").lower() == "filled"),
            "by_trigger": sl2_by_trigger,
        },
        "outcomes": {
            "exit_leg_count": len(leg_values),
            "exit_leg_wins": leg_wins,
            "exit_leg_win_rate": _ratio(leg_wins, len(leg_values)),
            "position_count": len(position_values),
            "position_wins": position_wins,
            "position_win_rate": _ratio(position_wins, len(position_values)),
        },
        "availability": {
            "liquidity": bool(filled_orders),
            "entry_orders": bool(entry_orders),
            "entry_wait_attempts": bool(wait_attempts),
            "stop_loss": bool(stop_orders or stop_reprices),
            "sl2": bool(sl2_orders),
            "position_outcomes": bool(position_values),
        },
    }
