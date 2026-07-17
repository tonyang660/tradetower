from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now

STRATEGY_ANALYTICS_PAGE_V2_VERSION = "phase7_step13_strategy_analytics_page_v2"


def _safe_get(source: str, path: str, params: dict[str, Any] | None = None, timeout: int = 30):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}{path}",
        params=params or {},
        timeout=timeout,
    )

    if error:
        return None, {"source": source, "path": path, "status_code": status_code, "error": error}

    if status_code != 200:
        return None, {"source": source, "path": path, "status_code": status_code, "error": payload}

    if not isinstance(payload, dict):
        return None, {"source": source, "path": path, "status_code": status_code, "error": "non_dict_payload"}

    return payload, None


def _items(payload: dict[str, Any] | None, key: str = "items") -> list[Any]:
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _num(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _service_block(payload: dict[str, Any] | None, error: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": payload if error is None else None,
        "error": error,
    }


def _v2_items(v2_payload: dict[str, Any] | None, key: str) -> list[Any]:
    if not isinstance(v2_payload, dict):
        return []
    value = v2_payload.get(key)
    return value if isinstance(value, list) else []


def _map_summary(v2_payload: dict[str, Any] | None, legacy_summary_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    legacy_summary = legacy_summary_payload.get("summary") if isinstance(legacy_summary_payload, dict) else None
    if isinstance(legacy_summary, dict):
        # Prefer legacy trade-outcome summary fields if available because the
        # existing UI labels are trade-outcome based.
        return legacy_summary

    if not isinstance(v2_payload, dict):
        return None

    summary = v2_payload.get("summary") or {}
    symbols = _v2_items(v2_payload, "symbols")

    best_symbol = None
    worst_symbol = None
    if symbols:
        sorted_symbols = sorted(symbols, key=lambda row: _num(row.get("filled"), _num(row.get("trade_candidates"))), reverse=True)
        best_symbol = sorted_symbols[0].get("symbol") if sorted_symbols else None
        worst_symbol = sorted_symbols[-1].get("symbol") if sorted_symbols else None

    return {
        "total_closed_trades": int(_num(summary.get("filled"))),
        "gross_pnl": 0,
        "net_pnl": 0,
        "total_fees": 0,
        "avg_trade_score": _num(summary.get("average_best_strategy_score"), _num(summary.get("average_candidate_score"))),
        "avg_hold_minutes": 0,
        "best_symbol": best_symbol,
        "worst_symbol": worst_symbol,
        "fee_to_gross_ratio": None,
    }


def _map_score_buckets(v2_payload: dict[str, Any] | None, legacy_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    legacy_items = _items(legacy_payload)
    if legacy_items:
        return legacy_items

    rows = _v2_items(v2_payload, "score_buckets")
    mapped = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped.append({
            "bucket_label": row.get("bucket") or row.get("bucket_label") or "unknown",
            "trades": int(_num(row.get("filled"), _num(row.get("rows")))),
            "gross_pnl": 0,
            "net_pnl": 0,
            "total_fees": 0,
            "win_rate": _num(row.get("fill_rate")),
            "expectancy": 0,
            "avg_hold_minutes": 0,
        })
    return mapped


def _map_symbols(v2_payload: dict[str, Any] | None, legacy_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    legacy_items = _items(legacy_payload)
    if legacy_items:
        return legacy_items

    rows = _v2_items(v2_payload, "symbols")
    mapped = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped.append({
            "symbol": row.get("symbol") or "-",
            "trades": int(_num(row.get("filled"), _num(row.get("rows")))),
            "gross_pnl": 0,
            "net_pnl": 0,
            "total_fees": 0,
            "win_rate": _num(row.get("fill_rate")),
            "expectancy": 0,
            "avg_hold_minutes": 0,
            "stop_out_rate": 0,
            "tp1_rate": 0,
            "tp2_rate": 0,
            "tp3_rate": 0,
            "fee_to_gross_ratio": None,
        })
    return mapped


def _empty_holding_times(legacy_payload: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(legacy_payload, dict):
        return {
            "summary": legacy_payload.get("summary"),
            "items": _items(legacy_payload),
        }
    return {"summary": None, "items": []}


def _empty_exit_outcomes(legacy_payload: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(legacy_payload, dict):
        return {
            "summary": legacy_payload.get("summary"),
            "items": _items(legacy_payload),
        }
    return {"summary": None, "items": []}


def _empty_fee_pressure(legacy_payload: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(legacy_payload, dict):
        return {
            "summary": legacy_payload.get("summary"),
            "items": _items(legacy_payload),
        }
    return {"summary": None, "items": []}


def get_strategy_analytics_page_v2(account_id: int, limit: int = 500, cycle_limit: int = 100) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    v2_payload, v2_error = _safe_get(
        "strategy_analytics_v2",
        "/strategy-analytics/v2",
        {"account_id": account_id, "limit": limit, "cycle_limit": cycle_limit},
        timeout=30,
    )
    if v2_error:
        errors.append(v2_error)

    # Legacy trade-outcome sections remain additive. The existing UI expects
    # them, so keep them if available without blocking the V2 page.
    legacy_summary, legacy_summary_error = _safe_get(
        "legacy_strategy_summary",
        "/strategy-analytics/summary",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_summary_error:
        errors.append(legacy_summary_error)

    legacy_score_buckets, legacy_score_error = _safe_get(
        "legacy_score_buckets",
        "/strategy-analytics/score-buckets",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_score_error:
        errors.append(legacy_score_error)

    legacy_symbols, legacy_symbols_error = _safe_get(
        "legacy_symbols",
        "/strategy-analytics/symbols",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_symbols_error:
        errors.append(legacy_symbols_error)

    legacy_holding, legacy_holding_error = _safe_get(
        "legacy_holding_times",
        "/strategy-analytics/holding-times",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_holding_error:
        errors.append(legacy_holding_error)

    legacy_exit, legacy_exit_error = _safe_get(
        "legacy_exit_outcomes",
        "/strategy-analytics/exit-outcomes",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_exit_error:
        errors.append(legacy_exit_error)

    legacy_fee, legacy_fee_error = _safe_get(
        "legacy_fee_pressure",
        "/strategy-analytics/fee-pressure",
        {"account_id": account_id},
        timeout=20,
    )
    if legacy_fee_error:
        errors.append(legacy_fee_error)

    return {
        "ok": v2_error is None,
        "partial": len(errors) > 0,
        "strategy_analytics_page_v2_version": STRATEGY_ANALYTICS_PAGE_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": _map_summary(v2_payload, legacy_summary),
        "score_buckets": _map_score_buckets(v2_payload, legacy_score_buckets),
        "symbols": _map_symbols(v2_payload, legacy_symbols),
        "holding_times": _empty_holding_times(legacy_holding),
        "exit_outcomes": _empty_exit_outcomes(legacy_exit),
        "fee_pressure": _empty_fee_pressure(legacy_fee),
        "v2": {
            "strategy_analytics": v2_payload,
            "summary": v2_payload.get("summary") if isinstance(v2_payload, dict) else None,
            "regimes": v2_payload.get("regimes") if isinstance(v2_payload, dict) else [],
            "setups": v2_payload.get("setups") if isinstance(v2_payload, dict) else [],
            "score_components": v2_payload.get("score_components") if isinstance(v2_payload, dict) else None,
            "risk_rejections": v2_payload.get("risk_rejections") if isinstance(v2_payload, dict) else None,
        },
        "services": {
            "strategy_analytics_v2": _service_block(v2_payload, v2_error),
            "legacy_strategy_summary": _service_block(legacy_summary, legacy_summary_error),
            "legacy_score_buckets": _service_block(legacy_score_buckets, legacy_score_error),
            "legacy_symbols": _service_block(legacy_symbols, legacy_symbols_error),
            "legacy_holding_times": _service_block(legacy_holding, legacy_holding_error),
            "legacy_exit_outcomes": _service_block(legacy_exit, legacy_exit_error),
            "legacy_fee_pressure": _service_block(legacy_fee, legacy_fee_error),
        },
        "errors": errors,
    }
