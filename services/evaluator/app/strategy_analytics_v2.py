from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from db import get_conn

STRATEGY_ANALYTICS_V2_VERSION = "phase7_step6_strategy_analytics_v2_hotfix13b_trade_outcomes"


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0), 4) if denominator else 0.0


def _avg(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return round(sum(clean) / len(clean), 8) if clean else None


def _parse_dt(value: Any):
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return value
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _normalize_strategy_name(value: Any) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower().replace("_", "-").replace(" ", "-")
    if "mean" in lowered and "reversion" in lowered:
        return "mean_reversion"
    if "trend" in lowered:
        return "trend_following"
    if lowered in ("long", "short"):
        return "direction_only"
    if not lowered or lowered == "none":
        return "unknown"
    return lowered


def _regime_bucket(regime: Any) -> str:
    lowered = str(regime or "").strip().lower()
    if lowered in ("trending", "strong_trend", "uptrend", "downtrend", "early_trend"):
        return "trend_regime"
    if lowered in ("choppy", "ranging", "range", "sideways", "low_volatility"):
        return "mean_reversion_style_regime"
    if lowered == "high_volatility":
        return "high_volatility"
    if not lowered or lowered == "none":
        return "unknown"
    return lowered


def _score_bucket(score: Any) -> str:
    value = _to_float(score, None)
    if value is None:
        return "unknown"
    if value >= 90:
        return "90+"
    if value >= 85:
        return "85-89"
    if value >= 80:
        return "80-84"
    if value >= 75:
        return "75-79"
    if value >= 70:
        return "70-74"
    if value >= 60:
        return "60-69"
    if value >= 0:
        return "<60"
    return "unknown"


def fetch_decision_rows(account_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    # The deployed schema has no decision_timestamp column.
    # cycle_id is an ISO timestamp string, e.g. 2026-07-19T05:25:08.064634Z.
    sql = """
        SELECT
            cycle_id,
            account_id,
            symbol,
            candidate_score,
            candidate_bias,
            candidate_reasons_json,
            candidate_sub_scores_json,
            strategy_regime,
            strategy_macro_bias,
            strategy_setup_confidence,
            strategy_decision_confidence,
            best_strategy_candidate,
            best_strategy_score,
            strategy_reason_tags_json,
            final_decision,
            risk_approved,
            guardian_allowed,
            paper_submitted,
            filled
        FROM evaluator_decision_history
        WHERE account_id = %s
        ORDER BY id DESC
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
        cycle_id = row[0]
        items.append({
            "cycle_id": cycle_id,
            "decision_timestamp": cycle_id,
            "account_id": int(row[1]),
            "symbol": row[2],
            "candidate_score": _to_float(row[3], None),
            "candidate_bias": row[4],
            "candidate_reasons": row[5] or [],
            "candidate_sub_scores": row[6] or {},
            "strategy_regime": row[7],
            "strategy_macro_bias": row[8],
            "strategy_setup_confidence": _to_float(row[9], None),
            "strategy_decision_confidence": _to_float(row[10], None),
            "best_strategy_candidate": row[11],
            "best_strategy_score": _to_float(row[12], None),
            "strategy_reason_tags": row[13] or [],
            "final_decision": row[14],
            "risk_approved": row[15],
            "guardian_allowed": row[16],
            "paper_submitted": row[17],
            "filled": row[18],
        })
    return items

def fetch_cycle_summaries(account_id: int, limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cycle_id, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY completed_at DESC NULLS LAST, started_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    return [{"cycle_id": row[0], "summary": row[1] or {}} for row in rows]


def fetch_position_items_from_performance_v2(account_id: int, limit: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        from performance_v2 import build_position_performance

        payload = build_position_performance(account_id, limit)
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            return items, None

        return [], {
            "error": "performance_v2_items_missing",
            "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
        }
    except Exception as exc:
        return [], {
            "error": "performance_v2_position_items_failed",
            "details": str(exc),
        }

def summarize_decision_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    trade_candidates = [row for row in rows if str(row.get("final_decision") or "").lower() == "trade"]
    risk_approved = [row for row in rows if row.get("risk_approved") is True]
    guardian_allowed = [row for row in rows if row.get("guardian_allowed") is True]
    paper_submitted = [row for row in rows if row.get("paper_submitted") is True]
    filled = [row for row in rows if row.get("filled") is True]

    best_scores = [_to_float(row.get("best_strategy_score"), None) for row in rows if row.get("best_strategy_score") is not None]
    candidate_scores = [_to_float(row.get("candidate_score"), None) for row in rows if row.get("candidate_score") is not None]

    return {
        "rows": total,
        "trade_candidates": len(trade_candidates),
        "risk_approved": len(risk_approved),
        "guardian_allowed": len(guardian_allowed),
        "paper_submitted": len(paper_submitted),
        "filled": len(filled),
        "trade_candidate_rate": _rate(len(trade_candidates), total),
        "risk_approval_rate": _rate(len(risk_approved), len(trade_candidates)),
        "guardian_allow_rate": _rate(len(guardian_allowed), len(risk_approved)),
        "paper_submit_rate": _rate(len(paper_submitted), len(guardian_allowed)),
        "fill_rate": _rate(len(filled), len(paper_submitted)),
        "average_best_strategy_score": round(sum(best_scores) / len(best_scores), 4) if best_scores else None,
        "average_candidate_score": round(sum(candidate_scores) / len(candidate_scores), 4) if candidate_scores else None,
    }


def group_rows(rows: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(key_fn(row))].append(row)

    items = [{"key": key, **summarize_decision_rows(values)} for key, values in grouped.items()]
    return sorted(items, key=lambda item: (item.get("filled", 0), item.get("trade_candidates", 0), item["key"]), reverse=True)


def extract_strategy_results_from_cycles(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for cycle in cycles:
        cycle_id = cycle["cycle_id"]
        summary = cycle.get("summary") or {}
        strategy_section = summary.get("strategy_engine") or {}
        for item in strategy_section.get("results", []):
            if isinstance(item, dict):
                enriched = dict(item)
                enriched["cycle_id"] = cycle_id
                results.append(enriched)
    return results


def extract_risk_results_from_cycles(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for cycle in cycles:
        cycle_id = cycle["cycle_id"]
        summary = cycle.get("summary") or {}
        risk_section = summary.get("risk_engine") or {}
        for item in risk_section.get("results", []):
            if isinstance(item, dict):
                enriched = dict(item)
                enriched["cycle_id"] = cycle_id
                results.append(enriched)
    return results


def score_component_summary(strategy_results: list[dict[str, Any]]) -> dict[str, Any]:
    component_values: dict[str, list[float]] = defaultdict(list)
    component_hits: dict[str, int] = defaultdict(int)

    for item in strategy_results:
        breakdown = item.get("score_breakdown") or item.get("breakdown") or item.get("best_strategy_breakdown") or {}
        if not isinstance(breakdown, dict):
            continue

        for key, value in breakdown.items():
            if isinstance(value, bool):
                if value:
                    component_hits[str(key)] += 1
            elif isinstance(value, (int, float)):
                component_values[str(key)].append(float(value))
            elif isinstance(value, dict):
                score = value.get("score") or value.get("points") or value.get("value")
                if isinstance(score, (int, float)):
                    component_values[str(key)].append(float(score))
                if value.get("passed") is True or value.get("active") is True:
                    component_hits[str(key)] += 1

    items = []
    for key in sorted(set(component_values.keys()) | set(component_hits.keys())):
        values = component_values.get(key, [])
        items.append({
            "component": key,
            "count": len(values),
            "average_score": round(sum(values) / len(values), 4) if values else None,
            "max_score": round(max(values), 4) if values else None,
            "min_score": round(min(values), 4) if values else None,
            "hits": component_hits.get(key, 0),
        })

    return {
        "count": len(items),
        "items": items,
        "note": "Score component extraction is best-effort because strategy result payloads may vary by phase.",
    }


def risk_rejection_summary(risk_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_reason: dict[str, int] = defaultdict(int)
    by_symbol: dict[str, int] = defaultdict(int)
    rejected = []

    for item in risk_results:
        approved = bool(item.get("approved", item.get("risk_decision") == "approved"))
        if approved:
            continue

        rejected.append(item)
        symbol = str(item.get("symbol") or "unknown").upper()
        by_symbol[symbol] += 1

        reasons = item.get("reason_codes") or item.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        if not reasons:
            reasons = ["unknown"]

        for reason in reasons:
            by_reason[str(reason)] += 1

    return {
        "rejections": len(rejected),
        "by_reason": dict(sorted(by_reason.items(), key=lambda x: x[1], reverse=True)),
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda x: x[1], reverse=True)),
        "items": rejected[:100],
    }


def _closed_position_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if str(item.get("status") or "").lower() == "closed"]


def _hold_minutes(item: dict[str, Any]) -> float | None:
    opened = _parse_dt(item.get("opened_at"))
    closed = _parse_dt(item.get("closed_at"))
    if opened is None or closed is None:
        return None
    try:
        return max((closed - opened).total_seconds() / 60.0, 0.0)
    except Exception:
        return None


def _score_from_decision(row: dict[str, Any]) -> float | None:
    # Strategy Analytics score buckets must represent the actual strategy trade
    # score, not the earlier candidate/filter score. candidate_score can be below
    # the trade threshold because it is used to decide whether a symbol should be
    # preserved for strategy review.
    for key in (
        "best_strategy_score",
        "strategy_decision_confidence",
        "strategy_setup_confidence",
    ):
        value = _to_float(row.get(key), None)
        if value is not None:
            return value
    return None


def _is_trade_like_decision(row: dict[str, Any]) -> bool:
    final_decision = str(row.get("final_decision") or "").strip().lower()
    return (
        row.get("paper_submitted") is True
        or row.get("filled") is True
        or final_decision in {"trade", "paper_submitted", "submitted", "approved"}
    )


def _trade_score_for_item(item: dict[str, Any], decisions: list[dict[str, Any]]) -> float | None:
    symbol = str(item.get("symbol") or "").upper()
    opened_at = _parse_dt(item.get("opened_at"))

    candidates = []

    for index, row in enumerate(decisions):
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        if not _is_trade_like_decision(row):
            continue

        score = _score_from_decision(row)
        if score is None:
            continue

        decision_time = _parse_dt(row.get("decision_timestamp"))

        # If we have both timestamps, only use decisions at/before position open.
        # Do not use future same-symbol rows; they are unrelated later decisions.
        if opened_at is not None and decision_time is not None and decision_time > opened_at:
            continue

        candidates.append((decision_time, -index, row))

    if not candidates:
        return None

    candidates.sort(
        key=lambda pair: (
            pair[0] is not None,
            pair[0] or datetime.min,
            pair[1],
        ),
        reverse=True,
    )
    return _score_from_decision(candidates[0][2])

def _trade_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    trades = len(items)
    gross = sum(_to_float(item.get("gross_realized_pnl")) for item in items)
    net = sum(_to_float(item.get("net_realized_pnl")) for item in items)
    fees = sum(_to_float(item.get("fees_paid")) for item in items)
    wins = sum(1 for item in items if _to_float(item.get("net_realized_pnl")) > 0)
    hold_values = [value for value in (_hold_minutes(item) for item in items) if value is not None]

    return {
        "trades": trades,
        "gross_pnl": round(gross, 8),
        "net_pnl": round(net, 8),
        "total_fees": round(fees, 8),
        "win_rate": _rate(wins, trades),
        "expectancy": round(net / trades, 8) if trades else 0.0,
        "avg_hold_minutes": round(sum(hold_values) / len(hold_values), 4) if hold_values else 0.0,
    }


def build_strategy_trade_summary_v2(items: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    closed = _closed_position_items(items)
    stats = _trade_stats(closed)

    scores = [
        score for score in (_trade_score_for_item(item, decisions) for item in closed)
        if score is not None
    ]

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        by_symbol[str(item.get("symbol") or "unknown").upper()].append(item)

    symbol_pnls = [
        (symbol, sum(_to_float(item.get("net_realized_pnl")) for item in rows))
        for symbol, rows in by_symbol.items()
    ]
    symbol_pnls.sort(key=lambda pair: pair[1], reverse=True)

    gross = stats["gross_pnl"]
    fees = stats["total_fees"]

    return {
        "total_closed_trades": stats["trades"],
        "gross_pnl": stats["gross_pnl"],
        "net_pnl": stats["net_pnl"],
        "total_fees": stats["total_fees"],
        "avg_trade_score": round(sum(scores) / len(scores), 4) if scores else None,
        "avg_hold_minutes": stats["avg_hold_minutes"],
        "best_symbol": symbol_pnls[0][0] if symbol_pnls else None,
        "worst_symbol": symbol_pnls[-1][0] if symbol_pnls else None,
        "fee_to_gross_ratio": round(fees / abs(gross), 6) if gross else None,
    }


def build_strategy_score_buckets_v2(items: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed = _closed_position_items(items)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in closed:
        score = _trade_score_for_item(item, decisions)
        grouped[_score_bucket(score)].append(item)

    order = {"unknown": -1, "<60": 0, "60-69": 1, "70-74": 2, "75-79": 3, "80-84": 4, "85-89": 5, "90+": 6}
    rows = []

    for bucket, bucket_items in grouped.items():
        stats = _trade_stats(bucket_items)
        rows.append({"bucket_label": bucket, **stats})

    return sorted(rows, key=lambda row: order.get(row["bucket_label"], -1))


def build_strategy_symbols_v2(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed = _closed_position_items(items)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        grouped[str(item.get("symbol") or "unknown").upper()].append(item)

    rows = []
    for symbol, symbol_items in grouped.items():
        stats = _trade_stats(symbol_items)

        stop_hits = 0
        tp1_hits = 0
        tp2_hits = 0
        tp3_hits = 0
        for item in symbol_items:
            exit_reason = str(item.get("exit_reason") or "").lower()
            tp_hits = item.get("tp_hits") or {}
            if "stop" in exit_reason:
                stop_hits += 1
            if bool(tp_hits.get("tp1")):
                tp1_hits += 1
            if bool(tp_hits.get("tp2")):
                tp2_hits += 1
            if bool(tp_hits.get("tp3")):
                tp3_hits += 1

        trades = stats["trades"]
        gross = stats["gross_pnl"]
        fees = stats["total_fees"]

        rows.append({
            "symbol": symbol,
            **stats,
            "stop_out_rate": _rate(stop_hits, trades),
            "tp1_rate": _rate(tp1_hits, trades),
            "tp2_rate": _rate(tp2_hits, trades),
            "tp3_rate": _rate(tp3_hits, trades),
            "fee_to_gross_ratio": round(fees / abs(gross), 6) if gross else None,
        })

    return sorted(rows, key=lambda row: row["net_pnl"], reverse=True)


def build_holding_times_v2(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = _closed_position_items(items)
    hold_values = [value for value in (_hold_minutes(item) for item in closed) if value is not None]
    winner_holds = [
        value for item in closed
        if _to_float(item.get("net_realized_pnl")) > 0
        for value in [_hold_minutes(item)]
        if value is not None
    ]
    loser_holds = [
        value for item in closed
        if _to_float(item.get("net_realized_pnl")) < 0
        for value in [_hold_minutes(item)]
        if value is not None
    ]

    median = None
    if hold_values:
        ordered = sorted(hold_values)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        hold = _hold_minutes(item)
        if hold is None:
            continue
        if hold < 5:
            label = "<5m"
        elif hold < 15:
            label = "5-15m"
        elif hold < 30:
            label = "15-30m"
        elif hold < 60:
            label = "30-60m"
        elif hold < 240:
            label = "1-4h"
        else:
            label = "4h+"
        buckets[label].append(item)

    order = {"<5m": 0, "5-15m": 1, "15-30m": 2, "30-60m": 3, "1-4h": 4, "4h+": 5}
    bucket_rows = []
    for label, bucket_items in buckets.items():
        bucket_rows.append({
            "bucket_label": label,
            "trades": len(bucket_items),
            "winners": sum(1 for item in bucket_items if _to_float(item.get("net_realized_pnl")) > 0),
            "losers": sum(1 for item in bucket_items if _to_float(item.get("net_realized_pnl")) < 0),
            "gross_pnl": round(sum(_to_float(item.get("gross_realized_pnl")) for item in bucket_items), 8),
            "net_pnl": round(sum(_to_float(item.get("net_realized_pnl")) for item in bucket_items), 8),
        })

    return {
        "summary": {
            "avg_hold_minutes": _avg(hold_values) or 0.0,
            "median_hold_minutes": round(median, 4) if median is not None else 0.0,
            "avg_winner_hold_minutes": _avg(winner_holds) or 0.0,
            "avg_loser_hold_minutes": _avg(loser_holds) or 0.0,
            "immediate_stopouts_count": sum(
                1 for item in closed
                if _to_float(item.get("net_realized_pnl")) < 0
                and (_hold_minutes(item) is not None and _hold_minutes(item) < 5)
            ),
            "fast_winners_count": sum(
                1 for item in closed
                if _to_float(item.get("net_realized_pnl")) > 0
                and (_hold_minutes(item) is not None and _hold_minutes(item) < 15)
            ),
        },
        "items": sorted(bucket_rows, key=lambda row: order.get(row["bucket_label"], 99)),
    }


def build_exit_outcomes_v2(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = _closed_position_items(items)
    total = len(closed)

    exit_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stop_count = 0
    tp1_count = 0
    tp2_count = 0
    tp3_count = 0

    for item in closed:
        exit_reason = str(item.get("exit_reason") or "").lower()
        tp_hits = item.get("tp_hits") or {}

        if "stop" in exit_reason:
            exit_type = "STOP_LOSS"
            stop_count += 1
        elif bool(tp_hits.get("tp3")):
            exit_type = "TP3"
        elif bool(tp_hits.get("tp2")):
            exit_type = "TP2"
        elif bool(tp_hits.get("tp1")):
            exit_type = "TP1"
        else:
            exit_type = "UNKNOWN"

        if bool(tp_hits.get("tp1")):
            tp1_count += 1
        if bool(tp_hits.get("tp2")):
            tp2_count += 1
        if bool(tp_hits.get("tp3")):
            tp3_count += 1

        exit_groups[exit_type].append(item)

    rows = []
    order = {"STOP_LOSS": 0, "TP1": 1, "TP2": 2, "TP3": 3, "UNKNOWN": 4}
    for exit_type, group_items in exit_groups.items():
        net_values = [_to_float(item.get("net_realized_pnl")) for item in group_items]
        rows.append({
            "exit_type": exit_type,
            "executions": len(group_items),
            "avg_realized_pnl": round(sum(net_values) / len(net_values), 8) if net_values else None,
            "total_realized_pnl": round(sum(net_values), 8),
            "total_fees": round(sum(_to_float(item.get("fees_paid")) for item in group_items), 8),
        })

    return {
        "summary": {
            "stop_loss_rate": _rate(stop_count, total),
            "tp1_rate": _rate(tp1_count, total),
            "tp2_rate": _rate(tp2_count, total),
            "tp3_rate": _rate(tp3_count, total),
        },
        "items": sorted(rows, key=lambda row: order.get(row["exit_type"], 99)),
    }


def build_fee_pressure_v2(items: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = build_strategy_symbols_v2(items)
    total_fees = sum(_to_float(row.get("total_fees")) for row in symbols)
    gross = sum(_to_float(row.get("gross_pnl")) for row in symbols)
    trades = sum(int(row.get("trades") or 0) for row in symbols)

    worst_fee_symbol = None
    best_fee_efficiency_symbol = None
    if symbols:
        worst_fee_symbol = max(symbols, key=lambda row: _to_float(row.get("total_fees")))["symbol"]
        efficient = [row for row in symbols if row.get("fee_to_gross_ratio") is not None]
        if efficient:
            best_fee_efficiency_symbol = min(efficient, key=lambda row: _to_float(row.get("fee_to_gross_ratio")))["symbol"]

    rows = [
        {
            "symbol": row["symbol"],
            "gross_pnl": row["gross_pnl"],
            "total_fees": row["total_fees"],
            "net_pnl": row["net_pnl"],
            "avg_fees_per_trade": round(_to_float(row.get("total_fees")) / int(row.get("trades") or 1), 8),
            "fee_to_gross_ratio": row.get("fee_to_gross_ratio"),
        }
        for row in symbols
    ]

    return {
        "summary": {
            "total_fees": round(total_fees, 8),
            "fee_to_gross_ratio": round(total_fees / abs(gross), 6) if gross else None,
            "avg_fees_per_trade": round(total_fees / trades, 8) if trades else 0.0,
            "worst_fee_symbol": worst_fee_symbol,
            "best_fee_efficiency_symbol": best_fee_efficiency_symbol,
        },
        "items": sorted(rows, key=lambda row: _to_float(row.get("fee_to_gross_ratio"), -1), reverse=True),
    }


def get_strategy_analytics_v2_summary(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    position_items, position_error = fetch_position_items_from_performance_v2(account_id, limit)
    return {
        "ok": position_error is None,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "summary": build_strategy_trade_summary_v2(position_items, rows),
        "decision_summary": summarize_decision_rows(rows),
        "position_source_error": position_error,
    }


def get_strategy_analytics_v2_regimes(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": group_rows(rows, lambda row: _regime_bucket(row.get("strategy_regime"))),
    }


def get_strategy_analytics_v2_setups(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": group_rows(rows, lambda row: _normalize_strategy_name(row.get("best_strategy_candidate"))),
        "note": "best_strategy_candidate is normalized into trend_following / mean_reversion where possible.",
    }


def get_strategy_analytics_v2_score_buckets(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    position_items, position_error = fetch_position_items_from_performance_v2(account_id, limit)
    return {
        "ok": position_error is None,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": build_strategy_score_buckets_v2(position_items, rows),
        "position_source_error": position_error,
    }


def get_strategy_analytics_v2_symbols(account_id: int, limit: int | None = None) -> dict[str, Any]:
    position_items, position_error = fetch_position_items_from_performance_v2(account_id, limit)
    return {
        "ok": position_error is None,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": build_strategy_symbols_v2(position_items),
        "position_source_error": position_error,
    }


def get_strategy_analytics_v2_score_components(account_id: int, cycle_limit: int = 100) -> dict[str, Any]:
    cycles = fetch_cycle_summaries(account_id, cycle_limit)
    strategy_results = extract_strategy_results_from_cycles(cycles)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "cycle_count": len(cycles),
        "strategy_result_count": len(strategy_results),
        "score_components": score_component_summary(strategy_results),
    }


def get_strategy_analytics_v2_risk_rejections(account_id: int, cycle_limit: int = 100) -> dict[str, Any]:
    cycles = fetch_cycle_summaries(account_id, cycle_limit)
    risk_results = extract_risk_results_from_cycles(cycles)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "cycle_count": len(cycles),
        "risk_result_count": len(risk_results),
        "risk_rejections": risk_rejection_summary(risk_results),
    }


def get_strategy_analytics_v2_bundle(account_id: int, limit: int | None = None, cycle_limit: int = 100) -> dict[str, Any]:
    decisions = fetch_decision_rows(account_id, limit)
    position_items, position_error = fetch_position_items_from_performance_v2(account_id, limit)

    trade_summary = build_strategy_trade_summary_v2(position_items, decisions)
    score_buckets = build_strategy_score_buckets_v2(position_items, decisions)
    symbols = build_strategy_symbols_v2(position_items)
    holding_times = build_holding_times_v2(position_items)
    exit_outcomes = build_exit_outcomes_v2(position_items)
    fee_pressure = build_fee_pressure_v2(position_items)

    return {
        "ok": position_error is None,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "summary": trade_summary,
        "trade_summary": trade_summary,
        "decision_summary": summarize_decision_rows(decisions),
        "regimes": get_strategy_analytics_v2_regimes(account_id, limit)["items"],
        "setups": get_strategy_analytics_v2_setups(account_id, limit)["items"],
        "score_buckets": score_buckets,
        "symbols": symbols,
        "holding_times": holding_times,
        "exit_outcomes": exit_outcomes,
        "fee_pressure": fee_pressure,
        "score_components": get_strategy_analytics_v2_score_components(account_id, cycle_limit)["score_components"],
        "risk_rejections": get_strategy_analytics_v2_risk_rejections(account_id, cycle_limit)["risk_rejections"],
        "positions": {
            "count": len(position_items),
            "closed_count": len(_closed_position_items(position_items)),
        },
        "position_source_error": position_error,
        "pnl_convention": {
            "source": "Performance V2 position items",
            "net_realized_pnl": "account/equity realized pnl convention",
            "gross_realized_pnl": "net_realized_pnl + fees_paid",
            "fees": "actual execution fees counted once",
        },
    }
