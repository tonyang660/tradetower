from config import EVALUATOR_BASE_URL
from http_client import get_json, get_json_proxy
from time_utils import iso_now


def get_execution_history(account_id: int, limit: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/orders/executed",
        params={"account_id": account_id, "limit": limit},
        timeout=20,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return payload, 200


def get_open_positions(account_id: int, refresh: bool):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/positions/open",
        params={
            "account_id": account_id,
            "refresh": "true" if refresh else "false",
        },
        timeout=20,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return payload, 200


def get_recent_positions(account_id: int, limit: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/positions/recent",
        params={
            "account_id": account_id,
            "limit": limit,
        },
        timeout=20,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return payload, 200


def get_open_orders(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/orders/open",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return payload, 200


def get_performance_summary_extended(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/summary-extended",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_pnl_series(account_id: int, limit: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/pnl-series",
        params={"account_id": account_id, "limit": limit},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_drawdown_series(account_id: int, limit: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/drawdown-series",
        params={"account_id": account_id, "limit": limit},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_directional_breakdown(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/directional-breakdown",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_hourly(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/hourly",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_weekday(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/weekday",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_session(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/session",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_calendar(account_id: int, limit_days: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/calendar",
        params={"account_id": account_id, "limit_days": limit_days},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_performance_monthly_summary(account_id: int):
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/monthly-summary",
        params={"account_id": account_id},
        timeout=20,
    )

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200


def get_bootstrap_performance(account_id: int):
    errors = []

    summary_payload, summary_status = get_performance_summary_extended(account_id)
    pnl_series_payload, pnl_series_status = get_performance_pnl_series(account_id, 8640)
    drawdown_payload, drawdown_status = get_performance_drawdown_series(account_id, 8640)
    directional_payload, directional_status = get_performance_directional_breakdown(account_id)
    hourly_payload, hourly_status = get_performance_hourly(account_id)
    weekday_payload, weekday_status = get_performance_weekday(account_id)
    session_payload, session_status = get_performance_session(account_id)
    calendar_payload, calendar_status = get_performance_calendar(account_id, 120)
    monthly_payload, monthly_status = get_performance_monthly_summary(account_id)

    if summary_status != 200:
        errors.append({"source": "summary_extended", "error": summary_payload})
    if pnl_series_status != 200:
        errors.append({"source": "pnl_series", "error": pnl_series_payload})
    if drawdown_status != 200:
        errors.append({"source": "drawdown_series", "error": drawdown_payload})
    if directional_status != 200:
        errors.append({"source": "directional_breakdown", "error": directional_payload})
    if hourly_status != 200:
        errors.append({"source": "hourly", "error": hourly_payload})
    if weekday_status != 200:
        errors.append({"source": "weekday", "error": weekday_payload})
    if session_status != 200:
        errors.append({"source": "session", "error": session_payload})
    if calendar_status != 200:
        errors.append({"source": "calendar", "error": calendar_payload})
    if monthly_status != 200:
        errors.append({"source": "monthly_summary", "error": monthly_payload})

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": summary_payload.get("summary") if isinstance(summary_payload, dict) else None,
        "equity_curve": pnl_series_payload.get("items", []) if isinstance(pnl_series_payload, dict) else [],
        "drawdown_curve": drawdown_payload.get("items", []) if isinstance(drawdown_payload, dict) else [],
        "directional_breakdown": directional_payload.get("directional_breakdown") if isinstance(directional_payload, dict) else None,
        "hourly_performance": hourly_payload.get("items", []) if isinstance(hourly_payload, dict) else [],
        "weekday_performance": weekday_payload.get("items", []) if isinstance(weekday_payload, dict) else [],
        "session_performance": session_payload.get("items", []) if isinstance(session_payload, dict) else [],
        "calendar_days": calendar_payload.get("items", []) if isinstance(calendar_payload, dict) else [],
        "monthly_summary": monthly_payload.get("monthly_summary") if isinstance(monthly_payload, dict) else None,
        "errors": errors,
    }

def get_strategy_analytics_summary(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/summary", {"account_id": account_id})

def get_strategy_analytics_score_buckets(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/score-buckets", {"account_id": account_id})

def get_strategy_analytics_symbols(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/symbols", {"account_id": account_id})

def get_strategy_analytics_holding_times(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/holding-times", {"account_id": account_id})

def get_strategy_analytics_exit_outcomes(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/exit-outcomes", {"account_id": account_id})

def get_strategy_analytics_fee_pressure(account_id: int):
    return get_json_proxy(f"{EVALUATOR_BASE_URL}/strategy-analytics/fee-pressure", {"account_id": account_id})

def get_bootstrap_strategy_analytics(account_id: int):
    errors = []

    summary_payload, summary_status = get_strategy_analytics_summary(account_id)
    score_payload, score_status = get_strategy_analytics_score_buckets(account_id)
    symbols_payload, symbols_status = get_strategy_analytics_symbols(account_id)
    holding_payload, holding_status = get_strategy_analytics_holding_times(account_id)
    exit_payload, exit_status = get_strategy_analytics_exit_outcomes(account_id)
    fee_payload, fee_status = get_strategy_analytics_fee_pressure(account_id)

    if summary_status != 200:
        errors.append({"source": "summary", "error": summary_payload})
    if score_status != 200:
        errors.append({"source": "score_buckets", "error": score_payload})
    if symbols_status != 200:
        errors.append({"source": "symbols", "error": symbols_payload})
    if holding_status != 200:
        errors.append({"source": "holding_times", "error": holding_payload})
    if exit_status != 200:
        errors.append({"source": "exit_outcomes", "error": exit_payload})
    if fee_status != 200:
        errors.append({"source": "fee_pressure", "error": fee_payload})

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "summary": summary_payload.get("summary") if isinstance(summary_payload, dict) else None,
        "score_buckets": score_payload.get("items", []) if isinstance(score_payload, dict) else [],
        "symbols": symbols_payload.get("items", []) if isinstance(symbols_payload, dict) else [],
        "holding_times": {
            "summary": holding_payload.get("summary") if isinstance(holding_payload, dict) else None,
            "items": holding_payload.get("items", []) if isinstance(holding_payload, dict) else [],
        },
        "exit_outcomes": {
            "summary": exit_payload.get("summary") if isinstance(exit_payload, dict) else None,
            "items": exit_payload.get("items", []) if isinstance(exit_payload, dict) else [],
        },
        "fee_pressure": {
            "summary": fee_payload.get("summary") if isinstance(fee_payload, dict) else None,
            "items": fee_payload.get("items", []) if isinstance(fee_payload, dict) else [],
        },
        "errors": errors,
    }