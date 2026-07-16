from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import get_conn

TP_LEG_ANALYTICS_VERSION = "phase7_step4_tp_leg_analytics"

TP_EVENT_TYPES = {
    "tp1": ("TP1_HIT", "TP1_FILLED"),
    "tp2": ("TP2_HIT", "TP2_FILLED"),
    "tp3": ("TP3_HIT", "TP3_FILLED"),
}
STOP_EVENT_TYPES = ("STOP_LOSS_HIT", "STOP_LOSS_FILLED", "SL_HIT")
TP_CLOSE_PERCENTS = {"tp1": 50.0, "tp2": 30.0, "tp3": 20.0}


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


def _position_dict(row) -> dict[str, Any]:
    return {
        "position_id": int(row[0]),
        "account_id": int(row[1]),
        "symbol": row[2],
        "side": row[3],
        "original_size": _to_float(row[4]),
        "entry_price": _to_float(row[5]),
        "risk_amount": _to_float(row[6]),
        "tp1_price": _to_float(row[7]),
        "tp2_price": _to_float(row[8]),
        "tp3_price": _to_float(row[9]),
        "tp1_hit": bool(row[10]),
        "tp2_hit": bool(row[11]),
        "tp3_hit": bool(row[12]),
        "opened_at": _iso(row[13]),
        "closed_at": _iso(row[14]),
        "status": row[15],
    }


def _event_dict(row) -> dict[str, Any]:
    return {
        "position_event_id": int(row[0]),
        "position_id": int(row[1]),
        "account_id": int(row[2]),
        "order_id": int(row[3]) if row[3] is not None else None,
        "execution_id": int(row[4]) if row[4] is not None else None,
        "event_type": row[5],
        "event_timestamp": _iso(row[6]),
        "price": _to_float(row[7], None),
        "size_before": _to_float(row[8], None),
        "size_delta": _to_float(row[9], None),
        "size_after": _to_float(row[10], None),
        "details": row[11] or {},
    }


def fetch_positions_for_tp_analytics(account_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT position_id, account_id, symbol, side, original_size, entry_price,
               risk_amount, tp1_price, tp2_price, tp3_price, tp1_hit, tp2_hit,
               tp3_hit, opened_at, closed_at, status
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

    return [_position_dict(row) for row in rows]


def fetch_tp_position_events(account_id: int, position_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not position_ids:
        return {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT position_event_id, position_id, account_id, order_id,
                       execution_id, event_type, event_timestamp, price,
                       size_before, size_delta, size_after, details_json
                FROM position_events
                WHERE account_id = %s
                  AND position_id = ANY(%s)
                  AND (
                        event_type IN ('TP1_HIT', 'TP1_FILLED', 'TP2_HIT', 'TP2_FILLED', 'TP3_HIT', 'TP3_FILLED')
                     OR event_type IN ('STOP_LOSS_HIT', 'STOP_LOSS_FILLED', 'SL_HIT')
                  )
                ORDER BY event_timestamp ASC, position_event_id ASC
                """,
                (account_id, position_ids),
            )
            rows = cur.fetchall()

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        event = _event_dict(row)
        grouped[int(event["position_id"])].append(event)
    return grouped


def classify_tp_event(event_type: str) -> str | None:
    event_type = str(event_type or "").upper()
    for level, event_types in TP_EVENT_TYPES.items():
        if event_type in event_types:
            return level
    if event_type in STOP_EVENT_TYPES:
        return "stop_loss"
    return None


def tp_ratio_from_position(position: dict[str, Any], level: str) -> float | None:
    entry = _to_float(position.get("entry_price"))
    risk_amount = _to_float(position.get("risk_amount"))
    size = _to_float(position.get("original_size"))
    tp_price = _to_float(position.get(f"{level}_price"), 0.0)
    if entry <= 0 or risk_amount <= 0 or size <= 0 or tp_price <= 0:
        return None
    risk_per_unit = risk_amount / size
    if risk_per_unit <= 0:
        return None
    return round(abs(tp_price - entry) / risk_per_unit, 8)


def infer_final_outcome(position: dict[str, Any], levels: dict[str, Any], stop_events: list[dict[str, Any]]) -> str:
    if levels["tp3"]["hit"]:
        return "tp3_full_completion"
    if stop_events:
        if levels["tp2"]["hit"]:
            return "tp2_then_stop"
        if levels["tp1"]["hit"]:
            return "tp1_then_stop"
        return "direct_stop_loss"
    if str(position.get("status")) == "open":
        return "open"
    if levels["tp2"]["hit"]:
        return "closed_after_tp2_unknown"
    if levels["tp1"]["hit"]:
        return "closed_after_tp1_unknown"
    return "closed_unknown"


def build_position_tp_detail(position: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    event_by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        level = classify_tp_event(event.get("event_type", ""))
        if level:
            event_by_level[level].append(event)

    levels: dict[str, Any] = {}
    for level in ("tp1", "tp2", "tp3"):
        level_events = event_by_level.get(level, [])
        hit = bool(position.get(f"{level}_hit")) or bool(level_events)
        first_event = level_events[0] if level_events else None
        realized_pnl = 0.0
        fee_paid = 0.0
        close_size = None
        for event in level_events:
            details = event.get("details") or {}
            realized_pnl += _to_float(details.get("realized_pnl"), 0.0)
            fee_paid += _to_float(details.get("fee_paid"), 0.0)
            if close_size is None:
                close_size = _to_float(details.get("close_size"), None)
                if close_size is None:
                    close_size = abs(_to_float(event.get("size_delta"), 0.0)) or None
        levels[level] = {
            "level": level,
            "hit": hit,
            "hit_at": first_event.get("event_timestamp") if first_event else None,
            "target_price": position.get(f"{level}_price"),
            "tp_ratio": tp_ratio_from_position(position, level),
            "close_percent": TP_CLOSE_PERCENTS[level],
            "close_size": close_size,
            "realized_pnl": round(realized_pnl, 8),
            "fee_paid": round(fee_paid, 8),
            "events": level_events,
        }

    stop_events = event_by_level.get("stop_loss", [])
    stop_pnl = 0.0
    stop_fees = 0.0
    for event in stop_events:
        details = event.get("details") or {}
        stop_pnl += _to_float(details.get("realized_pnl"), 0.0)
        stop_fees += _to_float(details.get("fee_paid"), 0.0)

    return {
        "position_id": position["position_id"],
        "account_id": position["account_id"],
        "symbol": position["symbol"],
        "side": position["side"],
        "opened_at": position.get("opened_at"),
        "closed_at": position.get("closed_at"),
        "status": position.get("status"),
        "levels": levels,
        "stop_loss": {
            "hit": bool(stop_events),
            "hit_at": stop_events[0].get("event_timestamp") if stop_events else None,
            "realized_pnl": round(stop_pnl, 8),
            "fee_paid": round(stop_fees, 8),
            "events": stop_events,
        },
        "tp_sequence": [level for level in ("tp1", "tp2", "tp3") if levels[level]["hit"]],
        "final_outcome": infer_final_outcome(position, levels, stop_events),
    }


def summarize_tp_details(details: list[dict[str, Any]]) -> dict[str, Any]:
    total_positions = len(details)
    summary: dict[str, Any] = {
        "positions": total_positions,
        "levels": {},
        "progression": {},
        "outcomes": defaultdict(int),
    }
    for detail in details:
        summary["outcomes"][detail["final_outcome"]] += 1

    for level in ("tp1", "tp2", "tp3"):
        hit_details = [detail for detail in details if detail["levels"][level]["hit"]]
        pnl = sum(_to_float(detail["levels"][level]["realized_pnl"]) for detail in hit_details)
        fees = sum(_to_float(detail["levels"][level]["fee_paid"]) for detail in hit_details)
        ratios = [detail["levels"][level]["tp_ratio"] for detail in hit_details if detail["levels"][level]["tp_ratio"] is not None]
        summary["levels"][level] = {
            "hits": len(hit_details),
            "hit_rate": round((len(hit_details) / total_positions * 100.0), 4) if total_positions else 0.0,
            "realized_pnl": round(pnl, 8),
            "fee_paid": round(fees, 8),
            "average_tp_ratio": round(sum(ratios) / len(ratios), 8) if ratios else None,
            "close_percent": TP_CLOSE_PERCENTS[level],
        }

    tp1_hits = [detail for detail in details if detail["levels"]["tp1"]["hit"]]
    tp2_hits = [detail for detail in details if detail["levels"]["tp2"]["hit"]]
    tp3_hits = [detail for detail in details if detail["levels"]["tp3"]["hit"]]
    summary["progression"] = {
        "tp1_to_tp2": {
            "base": len(tp1_hits),
            "continued": len(tp2_hits),
            "rate": round((len(tp2_hits) / len(tp1_hits) * 100.0), 4) if tp1_hits else 0.0,
        },
        "tp2_to_tp3": {
            "base": len(tp2_hits),
            "continued": len(tp3_hits),
            "rate": round((len(tp3_hits) / len(tp2_hits) * 100.0), 4) if tp2_hits else 0.0,
        },
    }
    summary["outcomes"] = dict(summary["outcomes"])
    return summary


def get_tp_leg_analytics(account_id: int, limit: int | None = None) -> dict[str, Any]:
    positions = fetch_positions_for_tp_analytics(account_id, limit)
    events_by_position = fetch_tp_position_events(account_id, [int(position["position_id"]) for position in positions])
    details = [
        build_position_tp_detail(position, events_by_position.get(int(position["position_id"]), []))
        for position in positions
    ]
    return {
        "ok": True,
        "tp_leg_analytics_version": TP_LEG_ANALYTICS_VERSION,
        "account_id": account_id,
        "count": len(details),
        "summary": summarize_tp_details(details),
        "items": details,
    }


def get_tp_progression(account_id: int, limit: int | None = None) -> dict[str, Any]:
    analytics = get_tp_leg_analytics(account_id, limit)
    return {
        "ok": True,
        "tp_leg_analytics_version": TP_LEG_ANALYTICS_VERSION,
        "account_id": account_id,
        "progression": analytics["summary"]["progression"],
        "levels": analytics["summary"]["levels"],
        "outcomes": analytics["summary"]["outcomes"],
    }
