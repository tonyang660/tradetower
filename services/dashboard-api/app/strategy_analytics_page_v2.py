from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now

STRATEGY_ANALYTICS_PAGE_V2_VERSION = "phase7_step13_strategy_analytics_page_v2_hotfix13b_v2_only"


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


def _service_block(payload: dict[str, Any] | None, error: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": payload if error is None else None,
        "error": error,
    }


def _list(payload: dict[str, Any] | None, key: str) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _section(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"summary": None, "items": []}
    value = payload.get(key)
    if isinstance(value, dict):
        return {
            "summary": value.get("summary"),
            "items": value.get("items") if isinstance(value.get("items"), list) else [],
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

    if isinstance(v2_payload, dict) and v2_payload.get("position_source_error"):
        errors.append({
            "source": "strategy_analytics_v2_position_source",
            "path": "/strategy-analytics/v2",
            "status_code": 200,
            "error": v2_payload.get("position_source_error"),
        })

    return {
        "ok": v2_error is None,
        "partial": len(errors) > 0,
        "strategy_analytics_page_v2_version": STRATEGY_ANALYTICS_PAGE_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": (v2_payload.get("trade_summary") or v2_payload.get("summary")) if isinstance(v2_payload, dict) else None,
        "score_buckets": _list(v2_payload, "score_buckets"),
        "symbols": _list(v2_payload, "symbols"),
        "holding_times": _section(v2_payload, "holding_times"),
        "exit_outcomes": _section(v2_payload, "exit_outcomes"),
        "fee_pressure": _section(v2_payload, "fee_pressure"),
        "v2": {
            "strategy_analytics": v2_payload,
            "trade_summary": v2_payload.get("trade_summary") if isinstance(v2_payload, dict) else None,
            "decision_summary": v2_payload.get("decision_summary") if isinstance(v2_payload, dict) else None,
            "regimes": v2_payload.get("regimes") if isinstance(v2_payload, dict) else [],
            "setups": v2_payload.get("setups") if isinstance(v2_payload, dict) else [],
            "score_components": v2_payload.get("score_components") if isinstance(v2_payload, dict) else None,
            "risk_rejections": v2_payload.get("risk_rejections") if isinstance(v2_payload, dict) else None,
            "positions": v2_payload.get("positions") if isinstance(v2_payload, dict) else None,
            "position_source_error": v2_payload.get("position_source_error") if isinstance(v2_payload, dict) else None,
            "pnl_convention": v2_payload.get("pnl_convention") if isinstance(v2_payload, dict) else None,
        },
        "services": {
            "strategy_analytics_v2": _service_block(v2_payload, v2_error),
        },
        "errors": errors,
    }
