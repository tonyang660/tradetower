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
    if not position_ids:
        return {}

    position_id_texts = [str(position_id) for position_id in position_ids]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    details_json->>'position_id' AS position_id,
                    COALESCE(SUM(fee_paid), 0) AS fees_paid,
                    COALESCE(AVG(slippage_bps), 0) AS avg_slippage_bps,
                    COUNT(*) AS executions
                FROM execution_reports
                WHERE account_id = %s
                  AND details_json->>'position_id' = ANY(%s)
                GROUP BY details_json->>'position_id'
                """,
                (account_id, position_id_texts),
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
    if upper in ("TP1_HIT", "TP1_FILLED"):
        return "tp1"
    if upper in ("TP2_HIT", "TP2_FILLED"):
        return "tp2"
    if upper in ("TP3_HIT", "TP3_FILLED"):
        return "tp3"
    if upper in ("STOP_LOSS_HIT", "STOP_LOSS_FILLED", "SL_HIT"):
        return "stop_loss"
    return None


def build_position_performance_item(
    position: dict[str, Any],
    events: list[dict[str, Any]],
    costs: dict[str, Any] | None,
) -> dict[str, Any]:
    gross_realized_pnl = 0.0
    fees_from_events = 0.0
    slippage_values = []
    exit_reason = "open" if position.get("status") == "open" else "closed_unknown"

    tp_hits = {"tp1": bool(position.get("tp1_hit")), "tp2": bool(position.get("tp2_hit")), "tp3": bool(position.get("tp3_hit"))}
    leg_pnl = {"tp1": 0.0, "tp2": 0.0, "tp3": 0.0, "stop_loss": 0.0}

    for event in events:
        details = event.get("details") or {}
        event_type = event.get("event_type")
        level = _event_type_level(event_type)

        pnl = _to_float(details.get("realized_pnl"), 0.0)
        fee = _to_float(details.get("fee_paid"), 0.0)
        slippage = _to_float(details.get("slippage_bps"), None)

        gross_realized_pnl += pnl
        fees_from_events += fee
        if slippage is not None:
            slippage_values.append(float(slippage))

        if level:
            leg_pnl[level] += pnl
            if level in tp_hits:
                tp_hits[level] = True
            if level == "stop_loss":
                exit_reason = "stop_loss"
            elif level == "tp3":
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

    # Performance V2 convention:
    # closed-position realized PnL is net after actual fees.
    net_realized_pnl = gross_realized_pnl - total_fees

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
        "executions": int((costs or {}).get("executions", 0)),
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

    winners = [item for item in closed if _to_float(item.get("net_realized_pnl")) > 0]
    losers = [item for item in closed if _to_float(item.get("net_realized_pnl")) < 0]
    breakeven = [item for item in closed if _to_float(item.get("net_realized_pnl")) == 0]

    gross_realized = sum(_to_float(item.get("gross_realized_pnl")) for item in closed)
    fees = sum(_to_float(item.get("fees_paid")) for item in closed)
    net_realized = sum(_to_float(item.get("net_realized_pnl")) for item in closed)

    gross_wins = sum(_to_float(item.get("net_realized_pnl")) for item in winners)
    gross_losses_abs = abs(sum(_to_float(item.get("net_realized_pnl")) for item in losers))
    profit_factor = gross_wins / gross_losses_abs if gross_losses_abs > 0 else None

    realized_rs = [_to_float(item.get("realized_r"), None) for item in closed if item.get("realized_r") is not None]
    win_rs = [_to_float(item.get("realized_r"), None) for item in winners if item.get("realized_r") is not None]
    loss_rs = [_to_float(item.get("realized_r"), None) for item in losers if item.get("realized_r") is not None]

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
        "average_realized_r": _avg([float(value) for value in realized_rs if value is not None]),
        "average_win_r": _avg([float(value) for value in win_rs if value is not None]),
        "average_loss_r": _avg([float(value) for value in loss_rs if value is not None]),
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


def get_performance_v2(account_id: int, limit: int | None = None, equity_limit: int = 1000) -> dict[str, Any]:
    position_payload = build_position_performance(account_id, limit)
    items = position_payload["items"]
    latest_equity = fetch_latest_equity(account_id)
    equity = build_equity_drawdown_v2(account_id, equity_limit)

    return {
        "ok": True,
        "performance_v2_version": PERFORMANCE_V2_VERSION,
        "account_id": account_id,
        "pnl_convention": PNL_CONVENTION,
        "latest_equity": latest_equity,
        "position_summary": summarize_position_performance(items),
        "leg_summary": build_leg_performance(items),
        "cost_breakdown": build_cost_breakdown(items),
        "equity": equity,
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
