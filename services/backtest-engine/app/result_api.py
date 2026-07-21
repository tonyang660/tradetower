
from __future__ import annotations

from typing import Any

from db import get_conn


MAX_LIMIT = 5000


def clamp_limit(value: int, default: int = 200, maximum: int = MAX_LIMIT) -> int:
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(1, min(limit, maximum))


def clamp_offset(value: int, default: int = 0) -> int:
    try:
        offset = int(value)
    except Exception:
        offset = default
    return max(0, offset)


def run_exists(run_id: int) -> bool:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM backtest_runs WHERE run_id=%s)", (run_id,))
        return bool(cur.fetchone()[0])


def fetch_run_summary(run_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(r) FROM backtest_runs r WHERE run_id=%s", (run_id,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_rows(
    *,
    run_id: int,
    table: str,
    order_by: str,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)

    allowed = {
        "backtest_trades": "trade_id",
        "backtest_orders": "order_id",
        "backtest_positions": "position_id",
        "backtest_equity_curve": "timestamp",
        "backtest_metrics": "metric_name",
        "backtest_logs": "timestamp, log_id",
    }

    if table not in allowed:
        raise ValueError(f"unsupported_table:{table}")

    if order_by != allowed[table]:
        order_by = allowed[table]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*)::int FROM {table} WHERE run_id=%s", (run_id,))
        total = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT row_to_json(t)
            FROM (
                SELECT *
                FROM {table}
                WHERE run_id=%s
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
            ) t
            """,
            (run_id, limit, offset),
        )
        rows = [row[0] for row in cur.fetchall()]

    return {
        "run_id": run_id,
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "rows": rows,
    }


def fetch_trades(run_id: int, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_trades", order_by="trade_id", limit=limit, offset=offset)


def fetch_orders(run_id: int, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_orders", order_by="order_id", limit=limit, offset=offset)


def fetch_positions(run_id: int, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_positions", order_by="position_id", limit=limit, offset=offset)


def fetch_equity_curve(run_id: int, limit: int = 1000, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_equity_curve", order_by="timestamp", limit=limit, offset=offset)


def fetch_metrics(run_id: int, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_metrics", order_by="metric_name", limit=limit, offset=offset)


def fetch_logs(run_id: int, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    return fetch_rows(run_id=run_id, table="backtest_logs", order_by="timestamp, log_id", limit=limit, offset=offset)


def fetch_result_bundle(run_id: int) -> dict[str, Any] | None:
    summary = fetch_run_summary(run_id)
    if not summary:
        return None

    return {
        "run": summary,
        "metrics": fetch_metrics(run_id, limit=500, offset=0),
        "trades": fetch_trades(run_id, limit=200, offset=0),
        "equity_curve": fetch_equity_curve(run_id, limit=1000, offset=0),
        "logs": fetch_logs(run_id, limit=200, offset=0),
    }
