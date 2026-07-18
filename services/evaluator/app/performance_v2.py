from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import get_conn

PERFORMANCE_V2_VERSION = "phase7_step7_performance_v2"


PNL_CONVENTION = {
    "realized_pnl": "Net after actual trading fees. Use this as the main closed-trade PnL.",
    "unrealized_pnl": "Live gross mark/last PnL. Do not subtract estimated exit fees.",
    "fees": "Actual fees remain visible separately for transparency and cost pressure analysis.",
    "slippage": "Slippage should remain visible separately when execution data provides it.",
    "spread": "Spread should remain visible separately when pricing context provides it.",
    "funding": "Funding should remain separate later when available.",
}


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0), 4) if denominator else 0.0


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 8) if values else None


def fetch_positions(account_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            position_id,
            account_id,
            symbol,
            side,
            original_size,
            remaining_size,
            entry_price,
            leverage,
            margin_used,
            stop_loss,
            risk_amount,
            tp1_price,
            tp2_price,
            tp3_price,
            tp1_hit,
            tp2_hit,
            tp3_hit,
            opened_at,
            closed_at,
            status
        FROM positions
        WHERE account_id = %s
        ORDER BY COALESCE(closed_at, opened_at) DESC
    """
    params: list[Any] = [account_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    items = []
    for row in rows:
        items.append({
            "position_id": int(row[0]),
            "account_id": int(row[1]),
            "symbol": row[2],
            "side": row[3],
            "original_size": _to_float(row[4]),
            "remaining_size": _to_float(row[5]),
            "entry_price": _to_float(row[6]),
            "leverage": _to_float(row[7]),
            "margin_used": _to_float(row[8]),
            "stop_loss": _to_float(row[9], None),
            "risk_amount": _to_float(row[10]),
            "tp1_price": _to_float(row[11], None),
            "tp2_price": _to_float(row[12], None),
            "tp3_price": _to_float(row[13], None),
            "tp1_hit": bool(row[14]),
            "tp2_hit": bool(row[15]),
            "tp3_hit": bool(row[16]),
            "opened_at": _iso(row[17]),
            "closed_at": _iso(row[18]),
            "status": row[19],
        })
    return items


def fetch_position_events(account_id: int, position_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not position_ids:
        return {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    position_event_id,
                    position_id,
                    event_type,
                    event_timestamp,
                    price,
                    size_before,
                    size_delta,
                    size_after,
                    details_json
                FROM position_events
                WHERE account_id = %s
                  AND position_id = ANY(%s)
                ORDER BY event_timestamp ASC, position_event_id ASC
                """,
                (account_id, position_ids),
            )
            rows = cur.fetchall()

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        event = {
            "position_event_id": int(row[0]),
            "position_id": int(row[1]),
            "event_type": row[2],
            "event_timestamp": _iso(row[3]),
            "price": _to_float(row[4], None),
            "size_before": _to_float(row[5], None),
            "size_delta": _to_float(row[6], None),
            "size_after": _to_float(row[7], None),
            "details": row[8] or {},
        }
        grouped[int(event["position_id"])].append(event)

    return grouped



def fetch_execution_costs(account_id: int, position_ids: list[int]) -> dict[int, dict[str, Any]]:
    # Fetch actual execution costs per position without double-counting executions.
    if not position_ids:
        return {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_reports'
                      AND column_name = 'details_json'
                )
                """
            )
            has_execution_details_json = bool(cur.fetchone()[0])

            if has_execution_details_json:
                position_id_texts = [str(position_id) for position_id in position_ids]
                cur.execute(
                    """
                    WITH distinct_executions AS (
                        SELECT DISTINCT
                            details_json->>'position_id' AS position_id,
                            execution_id,
                            fee_paid,
                            slippage_bps
                        FROM execution_reports
                        WHERE account_id = %s
                          AND details_json->>'position_id' = ANY(%s)
                    )
                    SELECT
                        position_id,
                        COALESCE(SUM(fee_paid), 0) AS fees_paid,
                        COALESCE(AVG(slippage_bps), 0) AS avg_slippage_bps,
                        COUNT(execution_id) AS executions
                    FROM distinct_executions
                    GROUP BY position_id
                    """,
                    (account_id, position_id_texts),
                )
            else:
                cur.execute(
                    """
                    WITH distinct_executions AS (
                        SELECT DISTINCT
                            pe.position_id,
                            er.execution_id,
                            er.fee_paid,
                            er.slippage_bps
                        FROM position_events pe
                        JOIN execution_reports er
                          ON er.execution_id = pe.execution_id
                         AND er.account_id = pe.account_id
                        WHERE pe.account_id = %s
                          AND pe.position_id = ANY(%s)
                          AND pe.execution_id IS NOT NULL
                    )
                    SELECT
                        position_id,
                        COALESCE(SUM(fee_paid), 0) AS fees_paid,
                        COALESCE(AVG(slippage_bps), 0) AS avg_slippage_bps,
                        COUNT(execution_id) AS executions
                    FROM distinct_executions
                    GROUP BY position_id
                    """,
                    (account_id, position_ids),
                )

            rows = cur.fetchall()

    result = {}
    for row in rows:
        if row[0] is None:
            continue
        result[int(row[0])] = {
            "fees_paid": _to_float(row[1]),
            "avg_slippage_bps": _to_float(row[2], None),
            "executions": int(row[3]),
        }
    return result

def fetch_latest_equity(account_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    recorded_at,
                    cash_balance,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    fees_paid_total,
                    trading_enabled,
                    manual_halt,
                    daily_kill_switch,
                    weekly_kill_switch
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (account_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "recorded_at": _iso(row[0]),
        "cash_balance": _to_float(row[1]),
        "equity": _to_float(row[2]),
        "realized_pnl": _to_float(row[3]),
        "unrealized_pnl": _to_float(row[4]),
        "fees_paid_total": _to_float(row[5]),
        "trading_enabled": bool(row[6]),
        "manual_halt": bool(row[7]),
        "daily_kill_switch": bool(row[8]),
        "weekly_kill_switch": bool(row[9]),
    }


def fetch_equity_series(account_id: int, limit: int = 1000) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, equity, realized_pnl, unrealized_pnl, fees_paid_total
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at ASC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    return [
        {
            "recorded_at": _iso(row[0]),
            "equity": _to_float(row[1]),
            "realized_pnl": _to_float(row[2]),
            "unrealized_pnl": _to_float(row[3]),
            "fees_paid_total": _to_float(row[4]),
        }
        for row in rows
    ]


def _event_type_level(event_type: str) -> str | None:
    upper = str(event_type or "").upper()

    if upper in ("TP1_HIT", "TP1_FILLED", "TAKE_PROFIT_1", "TAKE_PROFIT_1_FILLED"):
        return "tp1"

    if upper in ("TP2_HIT", "TP2_FILLED", "TAKE_PROFIT_2", "TAKE_PROFIT_2_FILLED"):
        return "tp2"

    if upper in ("TP3_HIT", "TP3_FILLED", "TAKE_PROFIT_3", "TAKE_PROFIT_3_FILLED"):
        return "tp3"

    if upper in (
        "STOP_FILLED",
        "STOP_LOSS_HIT",
        "STOP_LOSS_FILLED",
        "STOP_LOSS_EXECUTED",
        "SL_HIT",
        "SL_FILLED",
    ):
        return "stop_loss"

    return None

def build_position_performance_item(
    position: dict[str, Any],
    events: list[dict[str, Any]],
    costs: dict[str, Any] | None,
) -> dict[str, Any]:
    realized_pnl = 0.0
    fees_from_events = 0.0
    slippage_values = []
    exit_reason = "open" if position.get("status") == "open" else "closed_unknown"

    tp_hits = {"tp1": bool(position.get("tp1_hit")), "tp2": bool(position.get("tp2_hit")), "tp3": bool(position.get("tp3_hit"))}
    leg_pnl = {"tp1": 0.0, "tp2": 0.0, "tp3": 0.0, "stop_loss": 0.0}

    counted_execution_ids: set[int] = set()

    for event in events:
        details = event.get("details") or {}
        event_type = str(event.get("event_type") or "").upper()
        level = _event_type_level(event_type)

        execution_id = event.get("execution_id")
        execution_key = None
        try:
            if execution_id is not None:
                execution_key = int(execution_id)
        except Exception:
            execution_key = None

        pnl = _to_float(details.get("realized_pnl"), 0.0)
        fee = _to_float(details.get("fee_paid"), 0.0)
        slippage = _to_float(details.get("slippage_bps"), None)

        # POSITION_CLOSED is an audit/lifecycle marker. Real realized PnL comes
        # from fill events only.
        is_close_audit_event = event_type == "POSITION_CLOSED"
        is_realization_event = level is not None and not is_close_audit_event

        if is_realization_event:
            if execution_key is None or execution_key not in counted_execution_ids:
                realized_pnl += pnl
                fees_from_events += fee
                if execution_key is not None:
                    counted_execution_ids.add(execution_key)

            if slippage is not None:
                slippage_values.append(float(slippage))

            leg_pnl[level] += pnl
            if level in tp_hits:
                tp_hits[level] = True
            if level == "stop_loss":
                exit_reason = "stop_loss"
            elif level == "tp3":
                exit_reason = "tp3_full_completion"

        elif event_type == "POSITION_OPENED":
            if execution_key is None or execution_key not in counted_execution_ids:
                fees_from_events += fee
                if execution_key is not None:
                    counted_execution_ids.add(execution_key)

        elif is_close_audit_event:
            close_reason = str(details.get("close_reason") or "").upper()
            if close_reason == "STOP_LOSS":
                exit_reason = "stop_loss"
            elif close_reason == "TP3":
                exit_reason = "tp3_full_completion"

    if position.get("status") == "closed" and exit_reason == "closed_unknown":
        if tp_hits["tp3"]:
            exit_reason = "tp3_full_completion"
        elif tp_hits["tp2"]:
            exit_reason = "closed_after_tp2_unknown"
        elif tp_hits["tp1"]:
            exit_reason = "closed_after_tp1_unknown"

    cost_fees = _to_float((costs or {}).get("fees_paid"), 0.0)
    total_fees = fees_from_events if fees_from_events else cost_fees

    # V2 page convention after Hotfix 10:
    # - event realized_pnl is the canonical realized PnL used by Overview/equity
    # - Performance panels should sum that value as net/account realized PnL
    # - Gross before fees is derived as net + fees
    net_realized_pnl = realized_pnl
    gross_realized_pnl = realized_pnl + total_fees

    risk_amount = _to_float(position.get("risk_amount"))
    realized_r = (net_realized_pnl / risk_amount) if risk_amount and risk_amount > 0 else None

    return {
        "position_id": position["position_id"],
        "symbol": position["symbol"],
        "side": position["side"],
        "status": position["status"],
        "opened_at": position.get("opened_at"),
        "closed_at": position.get("closed_at"),
        "entry_price": position.get("entry_price"),
        "original_size": position.get("original_size"),
        "remaining_size": position.get("remaining_size"),
        "risk_amount": risk_amount,
        "gross_realized_pnl": round(gross_realized_pnl, 8),
        "fees_paid": round(total_fees, 8),
        "net_realized_pnl": round(net_realized_pnl, 8),
        "realized_r": round(realized_r, 8) if realized_r is not None else None,
        "avg_slippage_bps": (costs or {}).get("avg_slippage_bps") if costs else (_avg(slippage_values) if slippage_values else None),
        "executions": int((costs or {}).get("executions", len(counted_execution_ids))),
        "tp_hits": tp_hits,
        "leg_gross_pnl": {key: round(value, 8) for key, value in leg_pnl.items()},
        "exit_reason": exit_reason,
    }

def build_position_performance(account_id: int, limit: int | None = None) -> dict[str, Any]:
    positions = fetch_positions(account_id, limit)
    position_ids = [int(position["position_id"]) for position in positions]
    events_by_position = fetch_position_events(account_id, position_ids)
    costs_by_position = fetch_execution_costs(account_id, position_ids)

    items = [
        build_position_performance_item(
            position,
            events_by_position.get(int(position["position_id"]), []),
            costs_by_position.get(int(position["position_id"])),
        )
        for position in positions
    ]

    return {
        "ok": True,
        "performance_v2_version": PERFORMANCE_V2_VERSION,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }



def summarize_position_performance(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [item for item in items if item.get("status") == "closed"]
    open_items = [item for item in items if item.get("status") == "open"]

    closed_pnls = [_to_float(item.get("net_realized_pnl")) for item in closed]
    winners = [item for item in closed if _to_float(item.get("net_realized_pnl")) > 0]
    losers = [item for item in closed if _to_float(item.get("net_realized_pnl")) < 0]
    breakeven = [item for item in closed if _to_float(item.get("net_realized_pnl")) == 0]

    win_pnls = [_to_float(item.get("net_realized_pnl")) for item in winners]
    loss_pnls = [_to_float(item.get("net_realized_pnl")) for item in losers]

    gross_realized = sum(_to_float(item.get("gross_realized_pnl")) for item in closed)
    fees = sum(_to_float(item.get("fees_paid")) for item in closed)
    net_realized = sum(closed_pnls)

    gross_wins = sum(win_pnls)
    gross_losses_abs = abs(sum(loss_pnls))
    profit_factor = gross_wins / gross_losses_abs if gross_losses_abs > 0 else None

    average_win_pnl = _avg(win_pnls) or 0.0
    average_loss_pnl = _avg(loss_pnls) or 0.0

    realized_rs = [_to_float(item.get("realized_r"), None) for item in closed if item.get("realized_r") is not None]
    win_rs = [_to_float(item.get("realized_r"), None) for item in winners if item.get("realized_r") is not None]
    loss_rs = [_to_float(item.get("realized_r"), None) for item in losers if item.get("realized_r") is not None]

    average_win_r = _avg([float(value) for value in win_rs if value is not None])
    average_loss_r = _avg([float(value) for value in loss_rs if value is not None])
    average_rr = None
    if average_win_pnl > 0 and average_loss_pnl < 0:
        average_rr = average_win_pnl / abs(average_loss_pnl)
    elif average_win_r is not None and average_loss_r is not None and average_loss_r < 0:
        average_rr = average_win_r / abs(average_loss_r)

    sharpe_ratio = None
    if len(closed_pnls) > 1:
        mean_val = sum(closed_pnls) / len(closed_pnls)
        variance = sum((value - mean_val) ** 2 for value in closed_pnls) / (len(closed_pnls) - 1)
        std_dev = variance ** 0.5
        if std_dev > 0:
            sharpe_ratio = mean_val / std_dev

    by_exit_reason: dict[str, int] = defaultdict(int)
    for item in closed:
        by_exit_reason[str(item.get("exit_reason") or "unknown")] += 1

    return {
        "positions_total": len(items),
        "positions_open": len(open_items),
        "positions_closed": len(closed),
        "wins": len(winners),
        "losses": len(losers),
        "breakeven": len(breakeven),
        "position_win_rate": _rate(len(winners), len(closed)),
        "gross_realized_pnl": round(gross_realized, 8),
        "fees_paid": round(fees, 8),
        "net_realized_pnl": round(net_realized, 8),
        "fee_to_gross_realized_ratio": round(fees / abs(gross_realized), 8) if gross_realized else None,
        "expectancy_net_pnl": round(net_realized / len(closed), 8) if closed else 0.0,
        "profit_factor": round(profit_factor, 8) if profit_factor is not None else None,
        "average_win_pnl": round(average_win_pnl, 8),
        "average_loss_pnl": round(average_loss_pnl, 8),
        "average_realized_r": _avg([float(value) for value in realized_rs if value is not None]),
        "average_win_r": average_win_r,
        "average_loss_r": average_loss_r,
        "average_rr": round(average_rr, 8) if average_rr is not None else None,
        "best_trade": round(max(closed_pnls), 8) if closed_pnls else 0.0,
        "worst_trade": round(min(closed_pnls), 8) if closed_pnls else 0.0,
        "sharpe_ratio": round(sharpe_ratio, 8) if sharpe_ratio is not None else None,
        "by_exit_reason": dict(by_exit_reason),
    }

def build_leg_performance(items: list[dict[str, Any]]) -> dict[str, Any]:
    levels = {}
    for level in ("tp1", "tp2", "tp3", "stop_loss"):
        if level == "stop_loss":
            hit_items = [item for item in items if item.get("exit_reason") in ("stop_loss", "direct_stop_loss", "tp1_then_stop", "tp2_then_stop")]
        else:
            hit_items = [item for item in items if item.get("tp_hits", {}).get(level)]

        gross_pnl = sum(_to_float(item.get("leg_gross_pnl", {}).get(level)) for item in hit_items)
        levels[level] = {
            "hits": len(hit_items),
            "hit_rate": _rate(len(hit_items), len(items)),
            "gross_pnl": round(gross_pnl, 8),
        }

    tp1_hits = [item for item in items if item.get("tp_hits", {}).get("tp1")]
    tp2_hits = [item for item in items if item.get("tp_hits", {}).get("tp2")]
    tp3_hits = [item for item in items if item.get("tp_hits", {}).get("tp3")]

    return {
        "levels": levels,
        "progression": {
            "tp1_to_tp2": {
                "base": len(tp1_hits),
                "continued": len(tp2_hits),
                "rate": _rate(len(tp2_hits), len(tp1_hits)),
            },
            "tp2_to_tp3": {
                "base": len(tp2_hits),
                "continued": len(tp3_hits),
                "rate": _rate(len(tp3_hits), len(tp2_hits)),
            },
        },
    }


def build_cost_breakdown(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [item for item in items if item.get("status") == "closed"]
    fees = sum(_to_float(item.get("fees_paid")) for item in closed)
    gross_realized = sum(_to_float(item.get("gross_realized_pnl")) for item in closed)

    slippage_values = [
        _to_float(item.get("avg_slippage_bps"), None)
        for item in items
        if item.get("avg_slippage_bps") is not None
    ]

    return {
        "fees_paid": round(fees, 8),
        "fee_to_gross_realized_ratio": round(fees / abs(gross_realized), 8) if gross_realized else None,
        "average_slippage_bps": _avg([float(value) for value in slippage_values if value is not None]),
        "spread_cost": None,
        "spread_note": "Spread cost is not aggregated yet; preserve pricing_context/spread fields for later extraction.",
        "funding_cost": None,
        "funding_note": "Funding is not available yet and should remain separate when added.",
    }


def build_equity_drawdown_v2(account_id: int, limit: int = 1000) -> dict[str, Any]:
    series = fetch_equity_series(account_id, limit)
    peak = None
    max_drawdown_value = 0.0
    max_drawdown_pct = 0.0
    items = []

    for row in series:
        equity = _to_float(row.get("equity"))
        if peak is None or equity > peak:
            peak = equity

        drawdown_value = max(0.0, peak - equity) if peak is not None else 0.0
        drawdown_pct = (drawdown_value / peak * 100.0) if peak and peak > 0 else 0.0
        max_drawdown_value = max(max_drawdown_value, drawdown_value)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        items.append({
            **row,
            "peak_equity": round(peak, 8) if peak is not None else None,
            "drawdown_value": round(drawdown_value, 8),
            "drawdown_pct": round(drawdown_pct, 4),
        })

    start_equity = _to_float(series[0]["equity"]) if series else None
    end_equity = _to_float(series[-1]["equity"]) if series else None
    equity_change_pct = ((end_equity - start_equity) / start_equity * 100.0) if start_equity and end_equity is not None else 0.0

    return {
        "count": len(items),
        "items": items,
        "summary": {
            "start_equity": round(start_equity, 8) if start_equity is not None else None,
            "end_equity": round(end_equity, 8) if end_equity is not None else None,
            "equity_change_pct": round(equity_change_pct, 4),
            "max_drawdown_value": round(max_drawdown_value, 8),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
        },
    }



def _parse_dt(value: Any):
    if value is None:
        return None
    if hasattr(value, "hour") and hasattr(value, "date"):
        return value
    try:
        from datetime import datetime
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _session_name_from_hour(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 21:
        return "New York"
    return "Late"


def _closed_v2_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("status") == "closed"]


def _side_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    trades = len(items)
    pnl_values = [_to_float(item.get("net_realized_pnl")) for item in items]
    pnl = sum(pnl_values)
    wins = sum(1 for value in pnl_values if value > 0)
    return {
        "trades": trades,
        "pnl": round(pnl, 8),
        "win_rate": _rate(wins, trades),
        "expectancy": round(pnl / trades, 8) if trades else 0.0,
    }


def build_directional_breakdown_v2(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = _closed_v2_items(items)
    long_items = [item for item in closed if str(item.get("side") or "").lower() == "long"]
    short_items = [item for item in closed if str(item.get("side") or "").lower() == "short"]
    return {
        "long": _side_stats(long_items),
        "short": _side_stats(short_items),
    }


def build_hourly_performance_v2(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in _closed_v2_items(items):
        closed_at = _parse_dt(item.get("closed_at"))
        if closed_at is None:
            continue
        buckets[int(closed_at.hour)].append(item)

    rows = []
    for hour in sorted(buckets):
        stats = _side_stats(buckets[hour])
        rows.append({
            "hour": hour,
            "pnl": stats["pnl"],
            "trades": stats["trades"],
            "win_rate": stats["win_rate"],
        })
    return rows


def build_weekday_performance_v2(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in _closed_v2_items(items):
        closed_at = _parse_dt(item.get("closed_at"))
        if closed_at is None:
            continue
        buckets[int(closed_at.weekday())].append(item)

    rows = []
    for weekday_index in sorted(buckets):
        stats = _side_stats(buckets[weekday_index])
        rows.append({
            "weekday": weekday_names[weekday_index],
            "pnl": stats["pnl"],
            "trades": stats["trades"],
            "win_rate": stats["win_rate"],
        })
    return rows


def build_session_performance_v2(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["Asia", "London", "New York", "Late"]
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in _closed_v2_items(items):
        closed_at = _parse_dt(item.get("closed_at"))
        if closed_at is None:
            continue
        buckets[_session_name_from_hour(int(closed_at.hour))].append(item)

    rows = []
    for session in order:
        if session not in buckets:
            continue
        stats = _side_stats(buckets[session])
        rows.append({
            "session": session,
            "pnl": stats["pnl"],
            "trades": stats["trades"],
            "win_rate": stats["win_rate"],
        })
    return rows


def build_calendar_performance_v2(items: list[dict[str, Any]], limit_days: int = 120) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in _closed_v2_items(items):
        closed_at = _parse_dt(item.get("closed_at"))
        if closed_at is None:
            continue
        buckets[closed_at.date().isoformat()].append(item)

    dates = sorted(buckets.keys())
    if limit_days and limit_days > 0:
        dates = dates[-limit_days:]

    rows = []
    for date in dates:
        stats = _side_stats(buckets[date])
        rows.append({
            "date": date,
            "pnl": stats["pnl"],
            "trades": stats["trades"],
            "win_rate": stats["win_rate"],
        })
    return rows


def build_monthly_summary_v2(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    calendar_days = build_calendar_performance_v2(items, limit_days=370)
    if not calendar_days:
        return None

    latest_month = max(str(day["date"])[:7] for day in calendar_days)
    month_days = [day for day in calendar_days if str(day["date"]).startswith(latest_month)]

    pnl = sum(_to_float(day.get("pnl")) for day in month_days)
    winning_days = sum(1 for day in month_days if _to_float(day.get("pnl")) > 0)
    losing_days = sum(1 for day in month_days if _to_float(day.get("pnl")) < 0)
    flat_days = sum(1 for day in month_days if _to_float(day.get("pnl")) == 0)
    pnl_values = [_to_float(day.get("pnl")) for day in month_days]

    return {
        "month": latest_month,
        "pnl": round(pnl, 8),
        "pnl_pct": 0.0,
        "winning_days": winning_days,
        "losing_days": losing_days,
        "flat_days": flat_days,
        "best_day": round(max(pnl_values), 8) if pnl_values else None,
        "worst_day": round(min(pnl_values), 8) if pnl_values else None,
    }


def build_time_analytics_v2(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "directional_breakdown": build_directional_breakdown_v2(items),
        "hourly_performance": build_hourly_performance_v2(items),
        "weekday_performance": build_weekday_performance_v2(items),
        "session_performance": build_session_performance_v2(items),
        "calendar_days": build_calendar_performance_v2(items, limit_days=120),
        "monthly_summary": build_monthly_summary_v2(items),
    }


def get_performance_v2(account_id: int, limit: int | None = None, equity_limit: int = 1000) -> dict[str, Any]:
    position_payload = build_position_performance(account_id, limit)
    items = position_payload["items"]
    latest_equity = fetch_latest_equity(account_id)
    equity = build_equity_drawdown_v2(account_id, equity_limit)

    position_summary = summarize_position_performance(items)

    # Align Performance V2 with the account/equity convention used by Overview.
    #
    # In the live paper account, evaluator_equity_history.realized_pnl is the
    # canonical realized PnL shown by Overview. Treat it as net realized PnL for
    # the Performance page, and derive gross as net + fees.
    #
    # This avoids subtracting fees a second time from event-level realized_pnl
    # and also makes the fee total match the account/equity snapshot instead of
    # relying on partial reconstruction from position_events.
    if isinstance(latest_equity, dict):
        canonical_net = latest_equity.get("realized_pnl")
        canonical_fees = latest_equity.get("fees_paid_total")

        if canonical_net is not None:
            net_value = _to_float(canonical_net)
            fee_value = _to_float(canonical_fees, _to_float(position_summary.get("fees_paid")))
            gross_value = net_value + fee_value

            closed = int(position_summary.get("positions_closed") or 0)
            wins = int(position_summary.get("wins") or 0)
            losses = int(position_summary.get("losses") or 0)

            # Rebuild aggregate PnL fields using the canonical account totals.
            position_summary["net_realized_pnl"] = round(net_value, 8)
            position_summary["fees_paid"] = round(fee_value, 8)
            position_summary["gross_realized_pnl"] = round(gross_value, 8)
            position_summary["expectancy_net_pnl"] = round(net_value / closed, 8) if closed else 0.0

            # If all closed trades are losers, use canonical net/closed as the
            # average loss. This keeps Trade Quality consistent with the summary.
            if wins == 0 and losses == closed and closed > 0:
                position_summary["average_win_pnl"] = 0.0
                position_summary["average_loss_pnl"] = round(net_value / closed, 8)
                position_summary["best_trade"] = max(_to_float(item.get("net_realized_pnl")) for item in items if item.get("status") == "closed") if closed else 0.0
                position_summary["worst_trade"] = min(_to_float(item.get("net_realized_pnl")) for item in items if item.get("status") == "closed") if closed else 0.0

            position_summary["fee_to_gross_realized_ratio"] = (
                round(fee_value / abs(gross_value), 8) if gross_value else None
            )

    time_analytics = build_time_analytics_v2(items)

    return {
        "ok": True,
        "performance_v2_version": PERFORMANCE_V2_VERSION,
        "account_id": account_id,
        "pnl_convention": {
            **PNL_CONVENTION,
            "realized_pnl_source": "evaluator_equity_history.realized_pnl",
            "realized_pnl_interpretation": "net_realized_pnl",
            "gross_realized_pnl_formula": "net_realized_pnl + fees_paid_total",
            "fees_source": "evaluator_equity_history.fees_paid_total",
        },
        "latest_equity": latest_equity,
        "position_summary": position_summary,
        "leg_summary": build_leg_performance(items),
        "cost_breakdown": build_cost_breakdown(items),
        "equity": equity,
        "time_analytics": time_analytics,
        "positions": {
            "count": len(items),
            "items": items,
        },
    }

def get_performance_v2_summary(account_id: int, limit: int | None = None) -> dict[str, Any]:
    position_payload = build_position_performance(account_id, limit)
    items = position_payload["items"]

    return {
        "ok": True,
        "performance_v2_version": PERFORMANCE_V2_VERSION,
        "account_id": account_id,
        "pnl_convention": PNL_CONVENTION,
        "latest_equity": fetch_latest_equity(account_id),
        "position_summary": summarize_position_performance(items),
        "leg_summary": build_leg_performance(items),
        "cost_breakdown": build_cost_breakdown(items),
    }


def get_performance_v2_positions(account_id: int, limit: int | None = None) -> dict[str, Any]:
    return build_position_performance(account_id, limit)


def get_performance_v2_equity(account_id: int, equity_limit: int = 1000) -> dict[str, Any]:
    return {
        "ok": True,
        "performance_v2_version": PERFORMANCE_V2_VERSION,
        "account_id": account_id,
        "pnl_convention": PNL_CONVENTION,
        "equity": build_equity_drawdown_v2(account_id, equity_limit),
    }
