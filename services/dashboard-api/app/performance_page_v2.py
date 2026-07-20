from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now

PERFORMANCE_PAGE_V2_VERSION = "phase7_step12_performance_page_v2_hotfix6_7_v2_only"


def _safe_get(source: str, path: str, params: dict[str, Any] | None = None, timeout: int = 30):
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


def _num(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() != "":
        try:
            return float(value)
        except Exception:
            return fallback
    return fallback


def _service_block(payload: dict[str, Any] | None, error: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": payload if error is None else None,
        "error": error,
    }


def _map_equity_curve(performance_v2: dict[str, Any] | None) -> list[dict[str, Any]]:
    equity = performance_v2.get("equity") if isinstance(performance_v2, dict) else None
    rows = equity.get("items", []) if isinstance(equity, dict) else []

    mapped: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mapped.append({
            "recorded_at": row.get("recorded_at"),
            "equity": _num(row.get("equity")),
            "realized_pnl": _num(row.get("realized_pnl")),
            "unrealized_pnl": _num(row.get("unrealized_pnl")),
        })
    return mapped


def _map_drawdown_curve(performance_v2: dict[str, Any] | None) -> list[dict[str, Any]]:
    equity = performance_v2.get("equity") if isinstance(performance_v2, dict) else None
    rows = equity.get("items", []) if isinstance(equity, dict) else []

    mapped: list[dict[str, Any]] = []
    peak = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue

        equity_value = _num(row.get("equity"))
        if peak is None or equity_value > peak:
            peak = equity_value

        peak_value = peak if peak is not None else equity_value
        drawdown_value = equity_value - peak_value
        drawdown_pct = (drawdown_value / peak_value) * 100 if peak_value else 0.0

        mapped.append({
            "recorded_at": row.get("recorded_at"),
            "equity": equity_value,
            "peak_equity": peak_value,
            "drawdown_value": drawdown_value,
            "drawdown_pct": drawdown_pct,
        })
    return mapped


def _map_summary(performance_v2: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(performance_v2, dict):
        return None

    position_summary = performance_v2.get("position_summary") or performance_v2.get("summary") or {}
    equity_block = performance_v2.get("equity") or {}
    equity_summary = equity_block.get("summary") if isinstance(equity_block, dict) else {}
    cost_breakdown = performance_v2.get("cost_breakdown") or {}

    wins = int(_num(position_summary.get("wins")))
    losses = int(_num(position_summary.get("losses")))
    total_trades = int(_num(position_summary.get("positions_closed"), _num(position_summary.get("positions_total"))))
    net_pnl = _num(position_summary.get("net_realized_pnl"))
    gross_pnl = _num(position_summary.get("gross_realized_pnl"), net_pnl + _num(position_summary.get("fees_paid")))
    fees = _num(position_summary.get("fees_paid"), _num(cost_breakdown.get("fees_paid")))

    return {
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "total_fees_paid": fees,
        "equity_change_pct": _num(equity_summary.get("equity_change_pct")),
        "max_drawdown_pct": _num(equity_summary.get("max_drawdown_pct")),
        "max_drawdown_value": _num(equity_summary.get("max_drawdown_value")),
        "total_trades": total_trades,
        "win_rate": _num(position_summary.get("position_win_rate")),
        "expectancy": _num(position_summary.get("expectancy_net_pnl")),
        "profit_factor": position_summary.get("profit_factor"),
        "average_win": _num(position_summary.get("average_win_pnl"), _num(position_summary.get("average_win"))),
        "average_loss": _num(position_summary.get("average_loss_pnl"), _num(position_summary.get("average_loss"))),
        "average_rr": position_summary.get("average_rr", position_summary.get("average_realized_r")),
        "sharpe_ratio": position_summary.get("sharpe_ratio"),
        "best_trade": _num(position_summary.get("best_trade")),
        "worst_trade": _num(position_summary.get("worst_trade")),
        "wins": wins,
        "losses": losses,
    }


def _time_analytics(performance_v2: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(performance_v2, dict):
        return {}
    value = performance_v2.get("time_analytics")
    return value if isinstance(value, dict) else {}


def get_performance_page_v2(account_id: int, limit: int = 500, equity_limit: int = 10000) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    performance_v2, performance_error = _safe_get(
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

    analytics = _time_analytics(performance_v2)

    return {
        "ok": performance_error is None,
        "partial": len(errors) > 0,
        "performance_page_v2_version": PERFORMANCE_PAGE_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": _map_summary(performance_v2),
        "equity_curve": _map_equity_curve(performance_v2),
        "drawdown_curve": _map_drawdown_curve(performance_v2),
        "directional_breakdown": analytics.get("directional_breakdown"),
        "hourly_performance": analytics.get("hourly_performance") or [],
        "weekday_performance": analytics.get("weekday_performance") or [],
        "session_performance": analytics.get("session_performance") or [],
        "calendar_days": analytics.get("calendar_days") or [],
        "monthly_summary": analytics.get("monthly_summary"),
        "v2": {
            "performance": performance_v2,
            "pnl_convention": performance_v2.get("pnl_convention") if isinstance(performance_v2, dict) else None,
            "cost_breakdown": performance_v2.get("cost_breakdown") if isinstance(performance_v2, dict) else None,
            "leg_summary": performance_v2.get("leg_summary") if isinstance(performance_v2, dict) else None,
            "latest_equity": performance_v2.get("latest_equity") if isinstance(performance_v2, dict) else None,
            "time_analytics": analytics,
        },
        "services": {
            "performance_v2": _service_block(performance_v2, performance_error),
        },
        "errors": errors,
    }
