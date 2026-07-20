from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL, TRADE_GUARDIAN_BASE_URL
from http_client import get_json
from time_utils import iso_now

PERFORMANCE_PAGE_V2_VERSION = "hotfix21_account_balances_pnl_source_of_truth"


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


def _first_nonzero_num(*values: Any) -> float:
    for value in values:
        n = _num(value, 0.0)
        if n != 0.0:
            return n
    return 0.0


def _first_present_num(*values: Any) -> float:
    for value in values:
        if value is None:
            continue
        return _num(value, 0.0)
    return 0.0


def _extract_fee_total(
    position_summary: dict[str, Any],
    cost_breakdown: dict[str, Any],
    latest_equity: dict[str, Any],
    gross_pnl: float | None = None,
) -> float:
    fees = _first_nonzero_num(
        position_summary.get("fees_paid"),
        position_summary.get("total_fees_paid"),
        position_summary.get("fees_paid_total"),
        position_summary.get("total_fees"),
        position_summary.get("fees"),
        cost_breakdown.get("fees_paid"),
        cost_breakdown.get("total_fees_paid"),
        cost_breakdown.get("fees_paid_total"),
        cost_breakdown.get("total_fees"),
        cost_breakdown.get("fees"),
        latest_equity.get("fees_paid_total"),
        latest_equity.get("total_fees_paid"),
        latest_equity.get("fees_paid"),
        latest_equity.get("total_fees"),
    )

    if fees != 0.0:
        return abs(fees)

    if gross_pnl is not None:
        for key in ("net_realized_pnl", "net_pnl"):
            if position_summary.get(key) is not None:
                implied = float(gross_pnl) - _num(position_summary.get(key))
                if implied != 0.0:
                    return abs(implied)

    return 0.0


def _extract_gross_pnl(
    position_summary: dict[str, Any],
    latest_equity: dict[str, Any],
    fees: float,
) -> float:
    return _first_present_num(
        position_summary.get("gross_realized_pnl"),
        position_summary.get("gross_pnl"),
        latest_equity.get("gross_realized_pnl"),
        latest_equity.get("realized_pnl"),
        position_summary.get("realized_pnl"),
        (
            _num(position_summary.get("net_realized_pnl"), _num(position_summary.get("net_pnl"))) + fees
            if position_summary.get("net_realized_pnl") is not None or position_summary.get("net_pnl") is not None
            else None
        ),
    )


def _account_balance_pnl_from_status(status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(status, dict):
        return None

    gross_realized_pnl = _num(status.get("realized_pnl"))
    fees_paid_total = abs(_num(status.get("fees_paid_total")))
    unrealized_pnl = _num(status.get("unrealized_pnl"))
    equity = _num(status.get("equity"))
    cash_balance = _num(status.get("cash_balance"))
    net_realized_pnl = gross_realized_pnl - fees_paid_total

    return {
        "source": "account_balances",
        "gross_realized_pnl": gross_realized_pnl,
        "fees_paid_total": fees_paid_total,
        "net_realized_pnl": net_realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "cash_balance": cash_balance,
        "equity": equity,
        "total_account_pnl": net_realized_pnl + unrealized_pnl,
        "formula": "net_realized_pnl = account_balances.realized_pnl - account_balances.fees_paid_total",
    }


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
        gross_realized = _num(row.get("gross_realized_pnl"), _num(row.get("realized_pnl")))
        fees_paid = _num(row.get("fees_paid_total"), _num(row.get("total_fees_paid")))
        net_realized = gross_realized - fees_paid

        mapped.append({
            "recorded_at": row.get("recorded_at"),
            "equity": _num(row.get("equity")),
            "realized_pnl": gross_realized,
            "gross_realized_pnl": gross_realized,
            "net_realized_pnl": net_realized,
            "unrealized_pnl": _num(row.get("unrealized_pnl")),
            "fees_paid_total": fees_paid,
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


def _sum_calendar_net_pnl(performance_v2: dict[str, Any]) -> float | None:
    analytics = _time_analytics(performance_v2)
    days = analytics.get("calendar_days") or []
    if not isinstance(days, list) or not days:
        return None

    total = 0.0
    found = False
    for day in days:
        if not isinstance(day, dict):
            continue
        if day.get("pnl") is None:
            continue
        total += _num(day.get("pnl"))
        found = True

    return total if found else None


def _sum_item_net_pnl(performance_v2: dict[str, Any]) -> float | None:
    items = performance_v2.get("items") if isinstance(performance_v2, dict) else None
    if not isinstance(items, list) or not items:
        return None

    total = 0.0
    found = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("net_realized_pnl") is not None:
            total += _num(item.get("net_realized_pnl"))
            found = True
        elif item.get("gross_realized_pnl") is not None:
            total += _num(item.get("gross_realized_pnl")) - _num(item.get("fees_paid"))
            found = True

    return total if found else None


def _canonical_net_pnl_for_summary(performance_v2: dict[str, Any], position_summary: dict[str, Any]) -> tuple[float, str]:
    # The calendar/monthly panels are already correct because they are based on
    # per-position net PnL after fees. Use the same net source for top summary
    # cards so Gross/Net cannot drift from calendar totals.
    calendar_net = _sum_calendar_net_pnl(performance_v2)
    if calendar_net is not None:
        return calendar_net, "calendar_days"

    items_net = _sum_item_net_pnl(performance_v2)
    if items_net is not None:
        return items_net, "position_items"

    if position_summary.get("net_realized_pnl") is not None:
        return _num(position_summary.get("net_realized_pnl")), "position_summary.net_realized_pnl"

    if position_summary.get("net_pnl") is not None:
        return _num(position_summary.get("net_pnl")), "position_summary.net_pnl"

    return 0.0, "missing"


def _map_summary(performance_v2: dict[str, Any] | None, account_balance_pnl: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(performance_v2, dict):
        return None

    position_summary = performance_v2.get("position_summary") or performance_v2.get("summary") or {}
    equity_block = performance_v2.get("equity") or {}
    equity_summary = equity_block.get("summary") if isinstance(equity_block, dict) else {}
    cost_breakdown = performance_v2.get("cost_breakdown") or {}
    latest_equity = performance_v2.get("latest_equity") or {}

    wins = int(_num(position_summary.get("wins")))
    losses = int(_num(position_summary.get("losses")))
    total_trades = int(_num(position_summary.get("positions_closed"), _num(position_summary.get("positions_total"))))

    # Hotfix 21:
    # Source of truth for top-line Performance PnL is account_balances.
    if isinstance(account_balance_pnl, dict):
        gross_pnl = _num(account_balance_pnl.get("gross_realized_pnl"))
        fees = abs(_num(account_balance_pnl.get("fees_paid_total")))
        net_pnl = gross_pnl - fees
        net_pnl_source = "account_balances"
    else:
        fees = _extract_fee_total(position_summary, cost_breakdown, latest_equity)
        net_pnl, net_pnl_source = _canonical_net_pnl_for_summary(performance_v2, position_summary)
        if fees == 0.0:
            stale_gross = _extract_gross_pnl(position_summary, latest_equity, fees)
            implied_fees = stale_gross - net_pnl
            if implied_fees != 0.0:
                fees = abs(implied_fees)
        gross_pnl = net_pnl + fees

    return {
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "total_fees_paid": fees,
        "net_pnl_source": net_pnl_source,
        "account_balance_pnl": account_balance_pnl,
        "pnl_convention": {
            "gross_pnl": "account_balances.realized_pnl when account balance status is available",
            "net_pnl": "account_balances.realized_pnl minus account_balances.fees_paid_total when available",
            "total_fees_paid": "actual execution fees deducted from net PnL",
        },
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

    guardian_status, guardian_status_status, guardian_status_raw_error = get_json(
        f"{TRADE_GUARDIAN_BASE_URL}/status",
        params={"account_id": account_id},
        timeout=20,
    )
    guardian_status_error = None
    if guardian_status_raw_error or guardian_status_status != 200 or not isinstance(guardian_status, dict):
        guardian_status_error = {
            "source": "trade_guardian_status",
            "path": "/status",
            "status_code": guardian_status_status,
            "error": guardian_status_raw_error or guardian_status,
        }
        errors.append(guardian_status_error)

    account_balance_pnl = _account_balance_pnl_from_status(guardian_status)
    analytics = _time_analytics(performance_v2)

    return {
        "ok": performance_error is None,
        "partial": len(errors) > 0,
        "performance_page_v2_version": PERFORMANCE_PAGE_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": _map_summary(performance_v2, account_balance_pnl),
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
            "account_balance_pnl": account_balance_pnl,
            "time_analytics": analytics,
        },
        "services": {
            "performance_v2": _service_block(performance_v2, performance_error),
            "trade_guardian_status": _service_block(guardian_status, guardian_status_error),
        },
        "errors": errors,
    }
