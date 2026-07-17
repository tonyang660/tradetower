from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import get_conn

STRATEGY_ANALYTICS_V2_VERSION = "phase7_step6_strategy_analytics_v2"


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100.0), 4) if denominator else 0.0


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
    value = _to_float(score, -1)
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
    sql = '''
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
    '''
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
            "cycle_id": row[0],
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
                '''
                SELECT cycle_id, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY completed_at DESC NULLS LAST, started_at DESC
                LIMIT %s
                ''',
                (account_id, limit),
            )
            rows = cur.fetchall()

    return [{"cycle_id": row[0], "summary": row[1] or {}} for row in rows]


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


def get_strategy_analytics_v2_summary(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "summary": summarize_decision_rows(rows),
        "pnl_convention": {
            "realized_pnl": "net after actual trading fees in Performance V2",
            "unrealized_pnl": "live gross mark/last PnL; no estimated exit fees subtracted",
            "costs": "fees, slippage, spread, and funding should be shown separately",
        },
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
    items = group_rows(rows, lambda row: _score_bucket(row.get("best_strategy_score") or row.get("candidate_score")))
    order = {"unknown": -1, "<60": 0, "60-69": 1, "70-74": 2, "75-79": 3, "80-84": 4, "85-89": 5, "90+": 6}
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": sorted(items, key=lambda item: order.get(item["key"], -1)),
    }


def get_strategy_analytics_v2_symbols(account_id: int, limit: int | None = None) -> dict[str, Any]:
    rows = fetch_decision_rows(account_id, limit)
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "items": group_rows(rows, lambda row: str(row.get("symbol") or "unknown").upper()),
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
    return {
        "ok": True,
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
        "account_id": account_id,
        "summary": get_strategy_analytics_v2_summary(account_id, limit)["summary"],
        "regimes": get_strategy_analytics_v2_regimes(account_id, limit)["items"],
        "setups": get_strategy_analytics_v2_setups(account_id, limit)["items"],
        "score_buckets": get_strategy_analytics_v2_score_buckets(account_id, limit)["items"],
        "symbols": get_strategy_analytics_v2_symbols(account_id, limit)["items"],
        "score_components": get_strategy_analytics_v2_score_components(account_id, cycle_limit)["score_components"],
        "risk_rejections": get_strategy_analytics_v2_risk_rejections(account_id, cycle_limit)["risk_rejections"],
    }
