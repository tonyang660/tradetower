from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now

DASHBOARD_AGGREGATION_V2_VERSION = "phase7_step8_dashboard_api_aggregation_v2"


def _safe_get(
    source: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}{path}",
        params=params or {},
        timeout=timeout,
    )

    if error:
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": error,
        }

    if status_code != 200:
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": payload,
        }

    if not isinstance(payload, dict):
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": "non_dict_payload",
        }

    return payload, None


def _service_block(payload: dict[str, Any] | None, error: dict[str, Any] | None) -> dict[str, Any]:
    if error:
        return {
            "ok": False,
            "data": None,
            "error": error,
        }

    return {
        "ok": True,
        "data": payload,
        "error": None,
    }


def _items(payload: dict[str, Any] | None, key: str = "items") -> list[Any]:
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _dict_value(payload: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def _normalize_performance(performance_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(performance_payload, dict):
        return {
            "summary": None,
            "latest_equity": None,
            "equity_curve": [],
            "drawdown_summary": None,
            "leg_summary": None,
            "cost_breakdown": None,
            "positions": [],
        }

    equity = performance_payload.get("equity") or {}
    positions = performance_payload.get("positions") or {}

    return {
        "summary": performance_payload.get("position_summary"),
        "latest_equity": performance_payload.get("latest_equity"),
        "equity_curve": _items(equity),
        "drawdown_summary": _dict_value(equity, "summary"),
        "leg_summary": performance_payload.get("leg_summary"),
        "cost_breakdown": performance_payload.get("cost_breakdown"),
        "positions": _items(positions),
        "pnl_convention": performance_payload.get("pnl_convention"),
    }


def _normalize_strategy(strategy_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(strategy_payload, dict):
        return {
            "summary": None,
            "regimes": [],
            "setups": [],
            "score_buckets": [],
            "symbols": [],
            "score_components": None,
            "risk_rejections": None,
        }

    return {
        "summary": strategy_payload.get("summary"),
        "regimes": _items(strategy_payload, "regimes"),
        "setups": _items(strategy_payload, "setups"),
        "score_buckets": _items(strategy_payload, "score_buckets"),
        "symbols": _items(strategy_payload, "symbols"),
        "score_components": strategy_payload.get("score_components"),
        "risk_rejections": strategy_payload.get("risk_rejections"),
    }


def _normalize_tp_analytics(tp_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(tp_payload, dict):
        return {
            "summary": None,
            "items": [],
        }

    return {
        "summary": tp_payload.get("summary"),
        "items": _items(tp_payload),
    }


def _normalize_stop_analytics(stop_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(stop_payload, dict):
        return {
            "summary": None,
            "items": [],
        }

    return {
        "summary": stop_payload.get("summary"),
        "items": _items(stop_payload),
    }


def get_dashboard_v2_snapshot(
    account_id: int,
    limit: int = 500,
    cycle_limit: int = 100,
    equity_limit: int = 10000,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    performance_payload, performance_error = _safe_get(
        "performance_v2",
        "/performance/v2",
        {
            "account_id": account_id,
            "limit": limit,
            "equity_limit": equity_limit,
        },
        timeout=30,
    )
    if performance_error:
        errors.append(performance_error)

    strategy_payload, strategy_error = _safe_get(
        "strategy_analytics_v2",
        "/strategy-analytics/v2",
        {
            "account_id": account_id,
            "limit": limit,
            "cycle_limit": cycle_limit,
        },
        timeout=30,
    )
    if strategy_error:
        errors.append(strategy_error)

    tp_payload, tp_error = _safe_get(
        "tp_leg_analytics",
        "/analytics/tp-legs",
        {
            "account_id": account_id,
            "limit": limit,
        },
        timeout=30,
    )
    if tp_error:
        errors.append(tp_error)

    stop_payload, stop_error = _safe_get(
        "stop_management_analytics",
        "/analytics/stop-management",
        {
            "account_id": account_id,
            "limit": limit,
        },
        timeout=30,
    )
    if stop_error:
        errors.append(stop_error)

    latest_cycle_payload, latest_cycle_error = _safe_get(
        "latest_cycle",
        "/cycles/latest",
        {"account_id": account_id},
        timeout=20,
    )
    if latest_cycle_error:
        errors.append(latest_cycle_error)

    open_positions_payload, open_positions_error = _safe_get(
        "open_positions",
        "/positions/open",
        {
            "account_id": account_id,
            "refresh": "true",
        },
        timeout=30,
    )
    if open_positions_error:
        errors.append(open_positions_error)

    open_orders_payload, open_orders_error = _safe_get(
        "open_orders",
        "/orders/open",
        {"account_id": account_id},
        timeout=20,
    )
    if open_orders_error:
        errors.append(open_orders_error)

    services = {
        "performance_v2": _service_block(performance_payload, performance_error),
        "strategy_analytics_v2": _service_block(strategy_payload, strategy_error),
        "tp_leg_analytics": _service_block(tp_payload, tp_error),
        "stop_management_analytics": _service_block(stop_payload, stop_error),
        "latest_cycle": _service_block(latest_cycle_payload, latest_cycle_error),
        "open_positions": _service_block(open_positions_payload, open_positions_error),
        "open_orders": _service_block(open_orders_payload, open_orders_error),
    }

    return {
        "ok": len(errors) == 0,
        "partial": len(errors) > 0,
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "params": {
            "limit": limit,
            "cycle_limit": cycle_limit,
            "equity_limit": equity_limit,
        },
        "performance": _normalize_performance(performance_payload),
        "strategy": _normalize_strategy(strategy_payload),
        "tp_analytics": _normalize_tp_analytics(tp_payload),
        "stop_analytics": _normalize_stop_analytics(stop_payload),
        "live": {
            "latest_cycle": latest_cycle_payload,
            "open_positions": _items(open_positions_payload),
            "open_positions_count": len(_items(open_positions_payload)),
            "open_orders": _items(open_orders_payload),
            "open_orders_count": len(_items(open_orders_payload)),
        },
        "services": services,
        "errors": errors,
    }


def get_dashboard_v2_overview(account_id: int, limit: int = 250, cycle_limit: int = 50, equity_limit: int = 500) -> dict[str, Any]:
    snapshot = get_dashboard_v2_snapshot(account_id, limit, cycle_limit, equity_limit)
    return {
        "ok": snapshot["ok"],
        "partial": snapshot["partial"],
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
        "account_id": account_id,
        "generated_at": snapshot["generated_at"],
        "performance_summary": snapshot["performance"]["summary"],
        "latest_equity": snapshot["performance"]["latest_equity"],
        "drawdown_summary": snapshot["performance"]["drawdown_summary"],
        "cost_breakdown": snapshot["performance"]["cost_breakdown"],
        "strategy_summary": snapshot["strategy"]["summary"],
        "tp_summary": snapshot["tp_analytics"]["summary"],
        "stop_summary": snapshot["stop_analytics"]["summary"],
        "live": snapshot["live"],
        "errors": snapshot["errors"],
    }



def get_dashboard_v2_performance(account_id: int, limit: int = 500, equity_limit: int = 10000) -> dict[str, Any]:
    performance_payload, performance_error = _safe_get(
        "performance_v2",
        "/performance/v2",
        {
            "account_id": account_id,
            "limit": limit,
            "equity_limit": equity_limit,
        },
        timeout=30,
    )

    return {
        "ok": performance_error is None,
        "partial": performance_error is not None,
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "performance": _normalize_performance(performance_payload),
        "service": _service_block(performance_payload, performance_error),
        "errors": [performance_error] if performance_error else [],
    }


def get_dashboard_v2_strategy(account_id: int, limit: int = 500, cycle_limit: int = 100) -> dict[str, Any]:
    strategy_payload, strategy_error = _safe_get(
        "strategy_analytics_v2",
        "/strategy-analytics/v2",
        {
            "account_id": account_id,
            "limit": limit,
            "cycle_limit": cycle_limit,
        },
        timeout=30,
    )

    return {
        "ok": strategy_error is None,
        "partial": strategy_error is not None,
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "strategy": _normalize_strategy(strategy_payload),
        "service": _service_block(strategy_payload, strategy_error),
        "errors": [strategy_error] if strategy_error else [],
    }


def get_dashboard_v2_live(account_id: int, limit: int = 50) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    latest_cycle_payload, latest_cycle_error = _safe_get(
        "latest_cycle",
        "/cycles/latest",
        {"account_id": account_id},
        timeout=20,
    )
    if latest_cycle_error:
        errors.append(latest_cycle_error)

    cycles_payload, cycles_error = _safe_get(
        "cycle_history",
        "/cycles/history",
        {"account_id": account_id, "limit": limit},
        timeout=20,
    )
    if cycles_error:
        errors.append(cycles_error)

    open_positions_payload, open_positions_error = _safe_get(
        "open_positions",
        "/positions/open",
        {"account_id": account_id, "refresh": "true"},
        timeout=30,
    )
    if open_positions_error:
        errors.append(open_positions_error)

    open_orders_payload, open_orders_error = _safe_get(
        "open_orders",
        "/orders/open",
        {"account_id": account_id},
        timeout=20,
    )
    if open_orders_error:
        errors.append(open_orders_error)

    return {
        "ok": len(errors) == 0,
        "partial": len(errors) > 0,
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "latest_cycle": latest_cycle_payload,
        "cycles": _items(cycles_payload),
        "open_positions": _items(open_positions_payload),
        "open_orders": _items(open_orders_payload),
        "services": {
            "latest_cycle": _service_block(latest_cycle_payload, latest_cycle_error),
            "cycle_history": _service_block(cycles_payload, cycles_error),
            "open_positions": _service_block(open_positions_payload, open_positions_error),
            "open_orders": _service_block(open_orders_payload, open_orders_error),
        },
        "errors": errors,
    }
