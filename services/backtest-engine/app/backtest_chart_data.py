
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from db import get_conn
from execution_metrics import trades_with_score_buckets


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _first(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return default


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _fetch_all(table: str, run_id: int, order_by: str) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT row_to_json(t)
            FROM (
                SELECT *
                FROM {table}
                WHERE run_id=%s
                ORDER BY {order_by}
            ) t
            """,
            (run_id,),
        )
        return [row[0] for row in cur.fetchall()]


def _fetch_run(run_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(r) FROM backtest_runs r WHERE run_id=%s", (run_id,))
        row = cur.fetchone()
        return row[0] if row else None


def _net(trade: dict[str, Any]) -> float:
    return _to_float(_first(trade, ["net_pnl", "pnl_net", "realized_pnl", "pnl", "profit_loss"], 0.0))


def _gross(trade: dict[str, Any]) -> float:
    gross = _first(trade, ["gross_pnl", "pnl_gross"], None)
    if gross is not None:
        return _to_float(gross)
    return _net(trade) + _fees(trade)


def _fees(trade: dict[str, Any]) -> float:
    if trade.get("fees") is not None:
        return abs(_to_float(trade.get("fees")))
    if trade.get("total_fees") is not None:
        return abs(_to_float(trade.get("total_fees")))
    return abs(_to_float(trade.get("entry_fee"))) + abs(_to_float(trade.get("exit_fee")))


def _hold_seconds(trade: dict[str, Any]) -> float | None:
    value = _first(trade, ["hold_seconds", "holding_seconds", "duration_seconds"], None)
    if value is not None:
        return max(0.0, _to_float(value))

    entry = _parse_dt(_first(trade, ["entry_time", "opened_at", "created_at", "entry_timestamp"], None))
    exit_ = _parse_dt(_first(trade, ["exit_time", "closed_at", "completed_at", "exit_timestamp"], None))
    if entry and exit_:
        return max(0.0, (exit_ - entry).total_seconds())

    bars = _first(trade, ["hold_bars", "bars_held"], None)
    if bars is not None:
        return max(0.0, _to_float(bars)) * 15 * 60

    return None


def _equity_value(point: dict[str, Any]) -> float:
    return _to_float(_first(point, ["equity", "equity_value", "balance", "portfolio_value"], 0.0))


def _timestamp(point: dict[str, Any]) -> str:
    value = _first(point, ["timestamp", "created_at"], None)
    return str(value) if value is not None else ""


def _reconcile_final_equity(
    run: dict[str, Any],
    raw_points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Report curve/summary accounting without inventing a chart point."""
    points = [dict(point) for point in raw_points]
    raw_values = [_equity_value(point) for point in raw_points]
    raw_last = raw_values[-1] if raw_values else None
    final_equity = _to_float(_first(run, ["final_equity"], None), None)
    starting_equity = _to_float(
        _first(run, ["starting_capital", "initial_capital", "starting_equity"], None),
        None,
    )
    final_delta = (
        final_equity - raw_last
        if final_equity is not None and raw_last is not None
        else None
    )
    summary_matches_curve = final_delta is not None and abs(final_delta) <= 0.01
    chart_values = raw_values
    status = "matched" if summary_matches_curve else "mismatch"
    if final_equity is None:
        status = "final_equity_unavailable"
    elif raw_last is None:
        status = "curve_unavailable"

    return points, {
        "starting_equity": starting_equity,
        "latest_equity_curve_value": raw_last,
        "raw_last_equity_curve_value": raw_last,
        "final_equity": final_equity,
        "final_equity_delta": final_delta,
        "raw_curve_min": min(raw_values) if raw_values else None,
        "raw_curve_max": max(raw_values) if raw_values else None,
        "equity_curve_min": min(chart_values) if chart_values else None,
        "equity_curve_max": max(chart_values) if chart_values else None,
        "raw_points": len(raw_points),
        "display_points": len(points),
        "final_point_appended": False,
        "summary_matches_curve": summary_matches_curve,
        "reconciliation_status": status,
    }


def _group_trades(trades: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0, "fees": 0.0, "wins": 0})
    for trade in trades:
        key = str(_first(trade, keys, "unknown") or "unknown")
        net = _net(trade)
        group = groups[key]
        group["trades"] += 1
        group["net_pnl"] += net
        group["gross_pnl"] += _gross(trade)
        group["fees"] += _fees(trade)
        group["wins"] += 1 if net > 0 else 0
    rows = []
    for key, value in groups.items():
        trades_count = max(1, int(value["trades"]))
        rows.append({
            "key": key,
            "trades": int(value["trades"]),
            "net_pnl": value["net_pnl"],
            "gross_pnl": value["gross_pnl"],
            "fees": value["fees"],
            "win_rate": value["wins"] / trades_count,
        })
    rows.sort(key=lambda row: row["net_pnl"], reverse=True)
    return rows


def _monthly_returns(equity_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    months: dict[str, dict[str, Any]] = {}
    for point in equity_points:
        ts = _parse_dt(_first(point, ["timestamp", "created_at"], None))
        if not ts:
            continue
        value = _equity_value(point)
        key = f"{ts.year:04d}-{ts.month:02d}"
        bucket = months.setdefault(key, {"month": key, "first_ts": ts, "last_ts": ts, "first_equity": value, "last_equity": value})
        if ts < bucket["first_ts"]:
            bucket["first_ts"] = ts
            bucket["first_equity"] = value
        if ts >= bucket["last_ts"]:
            bucket["last_ts"] = ts
            bucket["last_equity"] = value
    rows = []
    for key in sorted(months):
        bucket = months[key]
        first = bucket["first_equity"]
        last = bucket["last_equity"]
        rows.append({
            "month": key,
            "return_pct": ((last - first) / first * 100.0) if first else 0.0,
            "pnl": last - first,
            "first_equity": first,
            "last_equity": last,
        })
    return rows


def _equity_curve(equity_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    peak = None
    for index, point in enumerate(equity_points):
        value = _equity_value(point)
        peak = value if peak is None else max(peak, value)
        drawdown_pct = ((value - peak) / peak * 100.0) if peak else 0.0
        rows.append({
            "index": index,
            "timestamp": _timestamp(point),
            "equity": value,
            "drawdown_pct": drawdown_pct,
        })
    return rows


def _holding_time_buckets(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("<1h", 0, 3600),
        ("1-4h", 3600, 4 * 3600),
        ("4-12h", 4 * 3600, 12 * 3600),
        ("12-24h", 12 * 3600, 24 * 3600),
        (">24h", 24 * 3600, float("inf")),
    ]
    rows = {name: {"key": name, "trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0, "fees": 0.0, "win_rate": 0.0, "wins": 0} for name, _, _ in buckets}
    for trade in trades:
        hold = _hold_seconds(trade)
        if hold is None:
            key = "unknown"
            rows.setdefault(key, {"key": key, "trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0, "fees": 0.0, "win_rate": 0.0, "wins": 0})
        else:
            key = next(name for name, low, high in buckets if hold >= low and hold < high)
        row = rows[key]
        net = _net(trade)
        row["trades"] += 1
        row["net_pnl"] += net
        row["gross_pnl"] += _gross(trade)
        row["fees"] += _fees(trade)
        row["wins"] += 1 if net > 0 else 0

    output = []
    for row in rows.values():
        if row["trades"] <= 0:
            continue
        row["win_rate"] = row["wins"] / max(1, row["trades"])
        row.pop("wins", None)
        output.append(row)
    return output


def _fee_pressure(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("low", 0.0, 0.10),
        ("medium", 0.10, 0.35),
        ("high", 0.35, 0.75),
        ("extreme", 0.75, float("inf")),
    ]
    rows = {name: {"key": name, "trades": 0, "net_pnl": 0.0, "gross_pnl": 0.0, "fees": 0.0, "win_rate": 0.0, "wins": 0} for name, _, _ in buckets}
    for trade in trades:
        gross_abs = abs(_gross(trade))
        # Phase 18J-HF4:
        # REGIME_CHANGE_SL2 can be a breakeven-gross leg. Avoid StopIteration
        # when gross_abs is zero; classify pure fee-drag legs as extreme.
        if gross_abs <= 0:
            key = "extreme"
        else:
            ratio = _fees(trade) / gross_abs
            key = next((name for name, low, high in buckets if ratio >= low and ratio < high), "extreme")
        row = rows[key]
        net = _net(trade)
        row["trades"] += 1
        row["net_pnl"] += net
        row["gross_pnl"] += _gross(trade)
        row["fees"] += _fees(trade)
        row["wins"] += 1 if net > 0 else 0
    output = []
    for row in rows.values():
        if row["trades"] <= 0:
            continue
        row["win_rate"] = row["wins"] / max(1, row["trades"])
        row.pop("wins", None)
        output.append(row)
    return output


def _trade_distribution(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("large_loss", float("-inf"), -50),
        ("loss", -50, 0),
        ("small_win", 0, 50),
        ("large_win", 50, float("inf")),
    ]
    rows = []
    for name, low, high in buckets:
        values = [_net(trade) for trade in trades if _net(trade) >= low and _net(trade) < high]
        rows.append({
            "key": name,
            "trades": len(values),
            "net_pnl": sum(values),
            "average_pnl": sum(values) / len(values) if values else 0.0,
        })
    return rows



def _downsample_equity_points(
    equity_points: list[dict[str, Any]],
    max_points: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Average-bucket downsample for chart rendering.

    Keeps full raw data for run analytics, but limits chart payload size.
    Preserves the first and last point, then averages equity/cash/PnL fields
    inside evenly sized buckets.
    """
    total = len(equity_points)
    limit = int(max_points or 2000)
    limit = max(100, min(limit, 20000))

    if total <= limit:
        return equity_points, {
            "enabled": False,
            "method": "none",
            "raw_points": total,
            "returned_points": total,
            "max_points": limit,
        }

    if limit <= 2:
        return [equity_points[0], equity_points[-1]], {
            "enabled": True,
            "method": "average_bucket_preserve_edges",
            "raw_points": total,
            "returned_points": 2,
            "max_points": limit,
        }

    bucket_count = limit - 2
    middle = equity_points[1:-1]
    bucket_size = len(middle) / float(bucket_count)

    sampled = [equity_points[0]]
    for bucket_index in range(bucket_count):
        start = int(bucket_index * bucket_size)
        end = int((bucket_index + 1) * bucket_size)
        if bucket_index == bucket_count - 1:
            end = len(middle)

        bucket = middle[start:end]
        if not bucket:
            continue

        midpoint = bucket[len(bucket) // 2]
        row = dict(midpoint)

        numeric_keys = [
            "equity",
            "cash",
            "open_position_value",
            "realized_pnl",
            "unrealized_pnl",
            "drawdown_pct",
        ]
        for key in numeric_keys:
            values = [_to_float(item.get(key), None) for item in bucket if item.get(key) is not None]
            values = [value for value in values if value is not None]
            if values:
                row[key] = sum(values) / len(values)

        row["downsampled_bucket_size"] = len(bucket)
        sampled.append(row)

    sampled.append(equity_points[-1])

    return sampled, {
        "enabled": True,
        "method": "average_bucket_preserve_edges",
        "raw_points": total,
        "returned_points": len(sampled),
        "max_points": limit,
    }


def fetch_backtest_chart_data(run_id: int, max_points: int | None = None) -> dict[str, Any]:
    run = _fetch_run(run_id)
    if not run:
        return {"ok": False, "error": "run_not_found", "run_id": run_id}

    trades = _fetch_all("backtest_trades", run_id, "trade_id")
    raw_equity_points = _fetch_all("backtest_equity_curve", run_id, "timestamp, ctid")
    display_equity_points, equity_metadata = _reconcile_final_equity(run, raw_equity_points)
    equity_points, downsampling = _downsample_equity_points(display_equity_points, max_points=max_points)

    curve = _equity_curve(equity_points)

    return {
        "ok": True,
        "run_id": run_id,
        "downsampling": downsampling,
        "equity_metadata": equity_metadata,
        "charts": {
            "equity_curve": curve,
            "drawdown_curve": [{"index": row["index"], "timestamp": row["timestamp"], "drawdown_pct": row["drawdown_pct"]} for row in curve],
            "monthly_returns": _monthly_returns(display_equity_points),
            "pnl_by_symbol": _group_trades(trades, ["symbol", "asset", "market"]),
            "pnl_by_regime": _group_trades(trades, ["regime", "market_regime", "regime_name", "strategy_route"]),
            "score_bucket_performance": _group_trades(trades_with_score_buckets(trades), ["score_bucket"]),
            "holding_time_performance": _holding_time_buckets(trades),
            "fee_pressure": _fee_pressure(trades),
            "trade_distribution": _trade_distribution(trades),
        },
        "availability": {
            "equity_curve": bool(curve),
            "monthly_returns": bool(_monthly_returns(display_equity_points)),
            "pnl_by_symbol": bool(trades),
            "pnl_by_regime": bool(trades),
            "score_bucket_performance": bool(trades),
            "holding_time_performance": bool(_holding_time_buckets(trades)),
            "fee_pressure": bool(trades),
            "trade_distribution": bool(trades),
        },
    }
