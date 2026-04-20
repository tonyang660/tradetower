from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
import json
import os
import time

import requests


SERVICE_NAME = "dashboard-api"
PORT = int(os.getenv("PORT", "8080"))

EVALUATOR_BASE_URL = os.getenv("EVALUATOR_BASE_URL", "http://evaluator:8080")
SCHEDULER_BASE_URL = os.getenv("SCHEDULER_BASE_URL", "http://scheduler:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
CANDIDATE_FILTER_BASE_URL = os.getenv("CANDIDATE_FILTER_BASE_URL", "http://candidate-filter:8080")
STRATEGY_ENGINE_BASE_URL = os.getenv("STRATEGY_ENGINE_BASE_URL", "http://strategy-engine:8080")
RISK_ENGINE_BASE_URL = os.getenv("RISK_ENGINE_BASE_URL", "http://risk-engine:8080")
PAPER_EXECUTION_BASE_URL = os.getenv("PAPER_EXECUTION_BASE_URL", "http://paper-execution:8080")
API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_json(url: str, params: dict | None = None, timeout: int = 15):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        payload = r.json()
        return payload, r.status_code, None
    except Exception as e:
        return None, None, str(e)
    

def post_json(url: str, payload: dict, timeout: int = 15):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        data = r.json()
        return data, r.status_code, None
    except Exception as e:
        return None, None, str(e)
    

def set_manual_halt(account_id: int, enabled: bool):
    reason_code = "MANUAL_HALT" if enabled else "MANUAL_HALT_CLEARED"

    payload, status_code, error = post_json(
        f"{TRADE_GUARDIAN_BASE_URL}/guard/manual-halt",
        {
            "account_id": account_id,
            "enabled": enabled,
            "reason_code": reason_code,
        },
        timeout=15,
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

    return {
        "ok": True,
        "account_id": account_id,
        "manual_halt": enabled,
        "trade_guardian_response": payload,
    }, 200

def local_service_health(name: str):
    return {
        "service_key": name,
        "service_name": name.replace("-", " ").title(),
        "ok": True,
        "reachable": True,
        "status": "healthy",
        "status_code": 200,
        "latency_ms": 0.0,
        "last_checked_at": iso_now(),
        "last_ok_at": iso_now(),
        "message": None,
        "payload": {
            "ok": True,
            "service": SERVICE_NAME,
            "timestamp": iso_now(),
        },
    }

def service_health_check(name: str, base_url: str):
    started = time.perf_counter()

    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        payload = r.json()
    except Exception as e:
        return {
            "service_key": name,
            "service_name": name.replace("-", " ").title(),
            "ok": False,
            "reachable": False,
            "status": "offline",
            "status_code": None,
            "latency_ms": None,
            "last_checked_at": iso_now(),
            "last_ok_at": None,
            "message": str(e),
        }

    ok = bool(payload.get("ok", False)) and r.status_code == 200

    return {
        "service_key": name,
        "service_name": name.replace("-", " ").title(),
        "ok": ok,
        "reachable": True,
        "status": "healthy" if ok else "degraded",
        "status_code": r.status_code,
        "latency_ms": latency_ms,
        "last_checked_at": iso_now(),
        "last_ok_at": iso_now() if ok else None,
        "message": None if ok else "Health endpoint returned non-ok response",
        "payload": payload,
    }


def get_market_session_banner():
    now_utc = datetime.now(timezone.utc)

    sessions = [
        {"name": "Sydney", "open_hour_utc": 21, "close_hour_utc": 6},
        {"name": "Tokyo", "open_hour_utc": 0, "close_hour_utc": 9},
        {"name": "London", "open_hour_utc": 8, "close_hour_utc": 16},
        {"name": "New York", "open_hour_utc": 13, "close_hour_utc": 21},
    ]

    # Python weekday(): Monday=0 ... Sunday=6
    is_weekend = now_utc.weekday() >= 5

    session_rows = []
    active_sessions = []
    next_session = None
    min_delta = None

    for session in sessions:
        open_dt = now_utc.replace(
            hour=session["open_hour_utc"], minute=0, second=0, microsecond=0
        )
        close_dt = now_utc.replace(
            hour=session["close_hour_utc"], minute=0, second=0, microsecond=0
        )

        if close_dt <= open_dt:
            close_dt += timedelta(days=1)

        if now_utc.hour < session["open_hour_utc"] and session["close_hour_utc"] < session["open_hour_utc"]:
            open_dt -= timedelta(days=1)
            close_dt -= timedelta(days=1)

        # Weekend override: all sessions forced closed
        is_active = False if is_weekend else (open_dt <= now_utc < close_dt)

        # Find next valid open, skipping weekends
        future_open = now_utc.replace(
            hour=session["open_hour_utc"], minute=0, second=0, microsecond=0
        )

        if future_open <= now_utc:
            future_open += timedelta(days=1)

        while future_open.weekday() >= 5:
            future_open += timedelta(days=1)

        delta = future_open - now_utc
        if min_delta is None or delta < min_delta:
            min_delta = delta
            next_session = {
                "name": session["name"],
                "opens_at_utc": future_open.isoformat().replace("+00:00", "Z"),
                "seconds_until_open": int(delta.total_seconds()),
            }

        if is_active:
            active_sessions.append(session["name"])

        session_rows.append({
            "name": session["name"],
            "open_hour_utc": session["open_hour_utc"],
            "close_hour_utc": session["close_hour_utc"],
            "is_active": is_active,
        })

    return {
        "ok": True,
        "generated_at": iso_now(),
        "current_utc_time": now_utc.isoformat().replace("+00:00", "Z"),
        "active_session": active_sessions[0] if active_sessions else None,
        "active_sessions": active_sessions,
        "overlap_count": len(active_sessions),
        "next_session": next_session,
        "session_rows": session_rows,
        "is_weekend": is_weekend,
    }


def get_bootstrap_overview(account_id: int):
    overview, overview_status, overview_error = get_json(
        f"{EVALUATOR_BASE_URL}/overview",
        params={"account_id": account_id},
        timeout=20,
    )
    performance, performance_status, performance_error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/summary",
        params={"account_id": account_id},
        timeout=20,
    )
    cycle_latest, cycle_status, cycle_error = get_json(
        f"{EVALUATOR_BASE_URL}/cycles/latest",
        params={"account_id": account_id},
        timeout=20,
    )
    decision_funnel, funnel_status, funnel_error = get_json(
        f"{EVALUATOR_BASE_URL}/analytics/decision-funnel",
        params={"account_id": account_id},
        timeout=20,
    )
    scheduler_health, scheduler_status, scheduler_error = get_json(
        f"{SCHEDULER_BASE_URL}/health",
        timeout=10,
    )
    market_banner = get_market_session_banner()

    errors = []
    if overview_error or overview_status != 200:
        errors.append({
            "source": "overview",
            "error": overview_error or overview,
        })
    if performance_error or performance_status != 200:
        errors.append({
            "source": "performance_summary",
            "error": performance_error or performance,
        })
    if cycle_error or cycle_status != 200:
        errors.append({
            "source": "cycles_latest",
            "error": cycle_error or cycle_latest,
        })
    if funnel_error or funnel_status != 200:
        errors.append({
            "source": "decision_funnel",
            "error": funnel_error or decision_funnel,
        })
    if scheduler_error or scheduler_status != 200:
        errors.append({
            "source": "scheduler_health",
            "error": scheduler_error or scheduler_health,
        })

    account_status = overview.get("account_status", {}) if isinstance(overview, dict) else {}
    trading_enabled = account_status.get("trading_enabled", True)
    manual_halt = account_status.get("manual_halt", False)
    daily_kill_switch = account_status.get("daily_kill_switch", False)
    weekly_kill_switch = account_status.get("weekly_kill_switch", False)

    disable_reasons = []
    if not trading_enabled:
        disable_reasons.append("TRADING_DISABLED")
    if manual_halt:
        disable_reasons.append("MANUAL_HALT")
    if daily_kill_switch:
        disable_reasons.append("DAILY_KILL_SWITCH")
    if weekly_kill_switch:
        disable_reasons.append("WEEKLY_KILL_SWITCH")

    trading_banner = {
        "trading_disabled": len(disable_reasons) > 0,
        "reason_codes": disable_reasons,
        "message": "Trading Suspended" if disable_reasons else "Trading Enabled",
        "maintenance_remains_active": True,
    }

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "market_banner": market_banner,
        "trading_banner": trading_banner,
        "overview": overview if isinstance(overview, dict) else None,
        "performance_summary": performance if isinstance(performance, dict) else None,
        "latest_cycle": cycle_latest if isinstance(cycle_latest, dict) else None,
        "decision_funnel": decision_funnel if isinstance(decision_funnel, dict) else None,
        "scheduler_health": scheduler_health if isinstance(scheduler_health, dict) else None,
        "errors": errors,
    }


def compute_cycle_duration_seconds(cycle: dict | None):
    if not cycle:
        return None

    started_at = cycle.get("started_at")
    completed_at = cycle.get("completed_at")
    if not started_at or not completed_at:
        return None

    try:
        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return round((end_dt - start_dt).total_seconds(), 2)
    except Exception:
        return None


def build_cycle_summary_strip(cycle: dict | None):
    if not cycle:
        return None

    summary = cycle.get("summary", {}) or {}

    candidate_filter = summary.get("candidate_filter", {}) or {}
    strategy_engine = summary.get("strategy_engine", {}) or {}
    maintenance = summary.get("maintenance", {}) or {}
    risk_engine = summary.get("risk_engine", {}) or {}
    paper_execution = summary.get("paper_execution", {}) or {}
    errors = summary.get("errors", []) or []

    candidates_found = len(candidate_filter.get("candidates", []) or [])

    return {
        "cycle_id": cycle.get("cycle_id"),
        "duration_seconds": compute_cycle_duration_seconds(cycle),
        "refreshed_symbols_count": int(summary.get("refreshed_symbols_count", 0) or 0),
        "maintenance_checked": int(maintenance.get("checked", 0) or 0),
        "maintenance_actions_triggered": int(maintenance.get("actions_triggered", 0) or 0),
        "candidates_found": candidates_found,
        "strategy_analyzed": int(strategy_engine.get("analyzed", 0) or 0),
        "strategy_accepted": int(strategy_engine.get("accepted", 0) or 0),
        "risk_approved": int(risk_engine.get("approved", 0) or 0),
        "paper_submitted": int(paper_execution.get("submitted", 0) or 0),
        "paper_fills": int(paper_execution.get("fills", 0) or 0),
        "error_count": len(errors),
    }


def build_pipeline_stages(cycle: dict | None):
    if not cycle:
        return []

    summary = cycle.get("summary", {}) or {}

    maintenance = summary.get("maintenance", {}) or {}
    entry_gate = summary.get("entry_gate", {}) or {}
    candidate_filter = summary.get("candidate_filter", {}) or {}
    strategy_engine = summary.get("strategy_engine", {}) or {}
    risk_engine = summary.get("risk_engine", {}) or {}
    final_entry_gate = summary.get("final_entry_gate", {}) or {}
    paper_execution = summary.get("paper_execution", {}) or {}
    errors = summary.get("errors", []) or []

    candidates_found = len(candidate_filter.get("candidates", []) or [])

    stages = [
        {
            "key": "refresh",
            "label": "Refresh",
            "status": "ok" if int(summary.get("refreshed_symbols_count", 0) or 0) > 0 else "idle",
            "primary_value": int(summary.get("refreshed_symbols_count", 0) or 0),
            "secondary_text": "symbols refreshed",
        },
        {
            "key": "maintenance",
            "label": "Maintenance",
            "status": "ok" if int(maintenance.get("checked", 0) or 0) >= 0 else "idle",
            "primary_value": int(maintenance.get("actions_triggered", 0) or 0),
            "secondary_text": f"{int(maintenance.get('checked', 0) or 0)} checked",
        },
        {
            "key": "entry_gate",
            "label": "Entry Gate",
            "status": "ok" if bool(entry_gate.get("trade_allowed", False)) else "blocked",
            "primary_value": 1 if bool(entry_gate.get("trade_allowed", False)) else 0,
            "secondary_text": "allowed" if bool(entry_gate.get("trade_allowed", False)) else "blocked",
        },
        {
            "key": "candidate_filter",
            "label": "Candidate Filter",
            "status": "ok" if candidates_found > 0 else "idle",
            "primary_value": candidates_found,
            "secondary_text": "candidates found",
        },
        {
            "key": "strategy_engine",
            "label": "Strategy Engine",
            "status": "ok" if int(strategy_engine.get("analyzed", 0) or 0) > 0 else "idle",
            "primary_value": int(strategy_engine.get("accepted", 0) or 0),
            "secondary_text": f"{int(strategy_engine.get('analyzed', 0) or 0)} analyzed",
        },
        {
            "key": "risk_engine",
            "label": "Risk Engine",
            "status": "ok" if int(risk_engine.get("checked", 0) or 0) > 0 else "idle",
            "primary_value": int(risk_engine.get("approved", 0) or 0),
            "secondary_text": f"{int(risk_engine.get('checked', 0) or 0)} checked",
        },
        {
            "key": "final_gate",
            "label": "Final Gate",
            "status": "ok" if int(final_entry_gate.get("checked", 0) or 0) > 0 else "idle",
            "primary_value": int(final_entry_gate.get("blocked", 0) or 0),
            "secondary_text": f"{int(final_entry_gate.get('checked', 0) or 0)} checked",
        },
        {
            "key": "paper_execution",
            "label": "Paper Execution",
            "status": "ok" if int(paper_execution.get("submitted", 0) or 0) > 0 else "idle",
            "primary_value": int(paper_execution.get("fills", 0) or 0),
            "secondary_text": f"{int(paper_execution.get('submitted', 0) or 0)} submitted",
        },
    ]

    if errors:
        stages.append({
            "key": "errors",
            "label": "Errors",
            "status": "error",
            "primary_value": len(errors),
            "secondary_text": "cycle errors",
        })

    return stages


def build_recent_cycle_card(cycle: dict):
    summary = cycle.get("summary", {}) or {}
    candidate_filter = summary.get("candidate_filter", {}) or {}
    strategy_engine = summary.get("strategy_engine", {}) or {}
    paper_execution = summary.get("paper_execution", {}) or {}
    errors = summary.get("errors", []) or []

    return {
        "cycle_id": cycle.get("cycle_id"),
        "started_at": cycle.get("started_at"),
        "completed_at": cycle.get("completed_at"),
        "duration_seconds": compute_cycle_duration_seconds(cycle),
        "refreshed_symbols_count": int(summary.get("refreshed_symbols_count", 0) or 0),
        "candidates_found": len(candidate_filter.get("candidates", []) or []),
        "strategy_analyzed": int(strategy_engine.get("analyzed", 0) or 0),
        "strategy_accepted": int(strategy_engine.get("accepted", 0) or 0),
        "paper_fills": int(paper_execution.get("fills", 0) or 0),
        "error_count": len(errors),
        "summary": summary,
    }


def build_cycle_trends(cycles: list[dict]):
    trend_cycles = list(reversed(cycles))

    candidates_per_cycle = []
    accepted_per_cycle = []
    fills_per_cycle = []
    errors_per_cycle = []

    for cycle in trend_cycles:
        summary = cycle.get("summary", {}) or {}
        candidate_filter = summary.get("candidate_filter", {}) or {}
        strategy_engine = summary.get("strategy_engine", {}) or {}
        paper_execution = summary.get("paper_execution", {}) or {}
        errors = summary.get("errors", []) or []

        label = (cycle.get("cycle_id") or "")[11:19] if cycle.get("cycle_id") else "cycle"

        candidates_per_cycle.append({
            "label": label,
            "value": len(candidate_filter.get("candidates", []) or []),
        })
        accepted_per_cycle.append({
            "label": label,
            "value": int(strategy_engine.get("accepted", 0) or 0),
        })
        fills_per_cycle.append({
            "label": label,
            "value": int(paper_execution.get("fills", 0) or 0),
        })
        errors_per_cycle.append({
            "label": label,
            "value": len(errors),
        })

    return {
        "candidates_per_cycle": candidates_per_cycle,
        "accepted_per_cycle": accepted_per_cycle,
        "fills_per_cycle": fills_per_cycle,
        "errors_per_cycle": errors_per_cycle,
    }


def get_bootstrap_live_cycle_monitor(account_id: int, limit: int):
    latest_cycle, latest_status, latest_error = get_json(
        f"{EVALUATOR_BASE_URL}/cycles/latest",
        params={"account_id": account_id},
        timeout=20,
    )

    cycle_history, history_status, history_error = get_json(
        f"{EVALUATOR_BASE_URL}/cycles/history",
        params={"account_id": account_id, "limit": limit},
        timeout=20,
    )

    errors = []

    if latest_error or latest_status != 200:
        errors.append({
            "source": "cycles_latest",
            "error": latest_error or latest_cycle,
        })

    if history_error or history_status != 200:
        errors.append({
            "source": "cycles_history",
            "error": history_error or cycle_history,
        })

    latest_cycle_obj = None
    if isinstance(latest_cycle, dict):
        latest_cycle_obj = latest_cycle.get("cycle")

    recent_cycles = []
    if isinstance(cycle_history, dict):
        recent_cycles = cycle_history.get("items", []) or []

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "latest_cycle": latest_cycle_obj,
        "summary_strip": build_cycle_summary_strip(latest_cycle_obj),
        "pipeline_stages": build_pipeline_stages(latest_cycle_obj),
        "recent_cycles": [build_recent_cycle_card(cycle) for cycle in recent_cycles],
        "trends": build_cycle_trends(recent_cycles),
        "errors": errors,
    }


def get_system_health():
    services = [
        ("evaluator", EVALUATOR_BASE_URL),
        ("scheduler", SCHEDULER_BASE_URL),
        ("trade-guardian", TRADE_GUARDIAN_BASE_URL),
        ("candidate-filter", CANDIDATE_FILTER_BASE_URL),
        ("strategy-engine", STRATEGY_ENGINE_BASE_URL),
        ("risk-engine", RISK_ENGINE_BASE_URL),
        ("paper-execution", PAPER_EXECUTION_BASE_URL),
        ("api-gateway", API_GATEWAY_BASE_URL),
        ("data-hub", DATA_HUB_BASE_URL),
    ]

    results = [service_health_check(name, base_url) for name, base_url in services]

    total = len(results)
    healthy = sum(1 for x in results if x.get("ok"))
    unhealthy = total - healthy

    return {
        "ok": unhealthy == 0,
        "generated_at": iso_now(),
        "summary": {
            "total_services": total,
            "healthy_services": healthy,
            "unhealthy_services": unhealthy,
        },
        "services": results,
    }


def set_scheduler_auto_loop(enabled: bool):
    payload, status_code, error = post_json(
        f"{SCHEDULER_BASE_URL}/controls/auto-loop",
        {"enabled": enabled},
        timeout=15,
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

    return {
        "ok": True,
        "scheduler": payload,
    }, 200


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
    pnl_series_payload, pnl_series_status = get_performance_pnl_series(account_id, 500)
    drawdown_payload, drawdown_status = get_performance_drawdown_series(account_id, 500)
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


def parse_iso_ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def build_system_health_overall(services: list[dict], last_cycle_at: str | None):
    total_services = len(services)
    healthy_services = sum(1 for s in services if s.get("status") == "healthy")
    degraded_services = sum(1 for s in services if s.get("status") == "degraded")
    offline_services = sum(1 for s in services if s.get("status") == "offline")

    latencies = [s.get("latency_ms") for s in services if s.get("latency_ms") is not None]
    average_latency_ms = round(sum(latencies) / len(latencies), 2) if latencies else None

    if offline_services > 0:
        overall_status = "partial_outage"
        message = "One or more core services are offline."
    elif degraded_services > 0:
        overall_status = "degraded"
        message = "Some services are degraded."
    else:
        overall_status = "operational"
        message = "All core services operational."

    return {
        "status": overall_status,
        "message": message,
        "healthy_services": healthy_services,
        "total_services": total_services,
        "average_latency_ms": average_latency_ms,
        "incidents_open": offline_services + degraded_services,
        "last_successful_cycle_at": last_cycle_at,
    }


def build_system_health_timeline(services: list[dict]):
    # v1 placeholder timeline: current status repeated across 24 slots
    labels = [f"{i:02d}" for i in range(24)]
    items = []

    for service in services:
        items.append({
            "service_key": service["service_key"],
            "service_name": service["service_name"],
            "points": [
                {
                    "label": label,
                    "status": service["status"],
                }
                for label in labels
            ],
        })

    return items


def build_system_health_dependency_flow(services: list[dict]):
    order = [
        "dashboard-api",
        "scheduler",
        "evaluator",
        "trade-guardian",
        "candidate-filter",
        "strategy-engine",
        "risk-engine",
        "paper-execution",
        "api-gateway",
        "data-hub",
    ]

    by_key = {s["service_key"]: s for s in services}

    flow = []
    flow.append({
        "service_key": "dashboard-web",
        "service_name": "Dashboard Web",
        "status": "healthy",
    })

    for key in order:
        if key in by_key:
            flow.append({
                "service_key": key,
                "service_name": by_key[key]["service_name"],
                "status": by_key[key]["status"],
            })

    return flow


def build_system_health_issues(services: list[dict], scheduler_health: dict | None, last_cycle_age_seconds: float | None):
    issues = []

    for service in services:
        status = service.get("status")
        if status == "offline":
            issues.append({
                "level": "critical",
                "code": "SERVICE_OFFLINE",
                "title": f"{service['service_name']} offline",
                "detail": service.get("message") or "Service is unreachable.",
                "detected_at": iso_now(),
            })
        elif status == "degraded":
            issues.append({
                "level": "warning",
                "code": "SERVICE_DEGRADED",
                "title": f"{service['service_name']} degraded",
                "detail": service.get("message") or "Health endpoint returned a degraded state.",
                "detected_at": iso_now(),
            })

    if scheduler_health and not scheduler_health.get("auto_loop_enabled", False):
        issues.append({
            "level": "warning",
            "code": "SCHEDULER_DISABLED",
            "title": "Scheduler auto loop disabled",
            "detail": "The scheduler is healthy, but automatic cycle execution is currently off.",
            "detected_at": iso_now(),
        })

    if last_cycle_age_seconds is not None and scheduler_health:
        loop_interval = int(scheduler_health.get("loop_interval_seconds", 300) or 300)
        stale_threshold = loop_interval * 2

        if last_cycle_age_seconds > stale_threshold:
            issues.append({
                "level": "warning",
                "code": "CYCLE_STALE",
                "title": "Cycle history appears stale",
                "detail": f"Last successful cycle age is {int(last_cycle_age_seconds)}s, above threshold {stale_threshold}s.",
                "detected_at": iso_now(),
            })

    return issues


def get_bootstrap_system_health(account_id: int):
    services = [
        ("dashboard-api", f"http://127.0.0.1:{PORT}"),
        ("evaluator", EVALUATOR_BASE_URL),
        ("scheduler", SCHEDULER_BASE_URL),
        ("trade-guardian", TRADE_GUARDIAN_BASE_URL),
        ("candidate-filter", CANDIDATE_FILTER_BASE_URL),
        ("strategy-engine", STRATEGY_ENGINE_BASE_URL),
        ("risk-engine", RISK_ENGINE_BASE_URL),
        ("paper-execution", PAPER_EXECUTION_BASE_URL),
        ("api-gateway", API_GATEWAY_BASE_URL),
        ("data-hub", DATA_HUB_BASE_URL),
    ]

    service_results = []

    for name, base_url in services:
        if name == "dashboard-api":
            service_results.append(local_service_health(name))
        else:
            service_results.append(service_health_check(name, base_url))

    scheduler_health, scheduler_status, scheduler_error = get_json(
        f"{SCHEDULER_BASE_URL}/health",
        timeout=10,
    )

    latest_cycle, latest_cycle_status, latest_cycle_error = get_json(
        f"{EVALUATOR_BASE_URL}/cycles/latest",
        params={"account_id": account_id},
        timeout=15,
    )

    overview_bootstrap, overview_status, overview_error = get_json(
        f"{EVALUATOR_BASE_URL}/overview",
        params={"account_id": account_id},
        timeout=15,
    )

    performance_bootstrap, performance_status, performance_error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/pnl-series",
        params={"account_id": account_id, "limit": 1},
        timeout=15,
    )

    errors = []

    if scheduler_error or scheduler_status != 200:
        errors.append({"source": "scheduler_health", "error": scheduler_error or scheduler_health})
        scheduler_health = None

    if latest_cycle_error or latest_cycle_status != 200:
        errors.append({"source": "latest_cycle", "error": latest_cycle_error or latest_cycle})
        latest_cycle = None

    if overview_error or overview_status != 200:
        errors.append({"source": "overview", "error": overview_error or overview_bootstrap})
        overview_bootstrap = None

    if performance_error or performance_status != 200:
        errors.append({"source": "performance_pnl_series", "error": performance_error or performance_bootstrap})
        performance_bootstrap = None

    latest_cycle_obj = latest_cycle.get("cycle") if isinstance(latest_cycle, dict) else None
    last_cycle_at = latest_cycle_obj.get("completed_at") if latest_cycle_obj else None

    last_cycle_dt = parse_iso_ts(last_cycle_at)
    now_dt = datetime.now(timezone.utc)
    last_cycle_age_seconds = round((now_dt - last_cycle_dt).total_seconds(), 2) if last_cycle_dt else None

    overall = build_system_health_overall(service_results, last_cycle_at)
    issues = build_system_health_issues(service_results, scheduler_health, last_cycle_age_seconds)

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "overall": overall,
        "summary_strip": {
            "overall_status": overall["status"],
            "healthy_services": overall["healthy_services"],
            "average_latency_ms": overall["average_latency_ms"],
            "scheduler_state": "enabled" if scheduler_health and scheduler_health.get("auto_loop_enabled", False) else "disabled",
            "last_cycle_age_seconds": last_cycle_age_seconds,
            "issues_open": len(issues),
        },
        "services": service_results,
        "dependency_flow": build_system_health_dependency_flow(service_results),
        "availability_timeline": build_system_health_timeline(service_results),
        "freshness": {
            "overview_generated_at": overview_bootstrap.get("overview_generated_at") if isinstance(overview_bootstrap, dict) else None,
            "performance_generated_at": performance_bootstrap.get("items", [{}])[-1].get("recorded_at") if isinstance(performance_bootstrap, dict) and performance_bootstrap.get("items") else None,
            "last_scheduler_cycle_at": last_cycle_at,
            "last_cycle_age_seconds": last_cycle_age_seconds,
            "scheduler_auto_loop_enabled": scheduler_health.get("auto_loop_enabled") if isinstance(scheduler_health, dict) else None,
            "scheduler_loop_interval_seconds": scheduler_health.get("loop_interval_seconds") if isinstance(scheduler_health, dict) else None,
        },
        "issues": issues,
        "errors": errors,
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_json({
                "ok": False,
                "error": "invalid_json",
                "details": str(e),
            }, status=400)
            return

        if parsed.path == "/controls/trading/suspend":
            account_id = int(payload.get("account_id", 1))
            result, status = set_manual_halt(account_id, True)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/trading/resume":
            account_id = int(payload.get("account_id", 1))
            result, status = set_manual_halt(account_id, False)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/scheduler/enable":
            result, status = set_scheduler_auto_loop(True)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/scheduler/disable":
            result, status = set_scheduler_auto_loop(False)
            self._send_json(result, status=status)
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
            })
            return

        if parsed.path == "/market/banner":
            self._send_json(get_market_session_banner())
            return

        if parsed.path == "/system/health":
            self._send_json(get_system_health())
            return

        if parsed.path == "/bootstrap/overview":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_overview(account_id))
            return
        
        if parsed.path == "/bootstrap/live-cycle-monitor":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["15"])[0])
            self._send_json(get_bootstrap_live_cycle_monitor(account_id, limit))
            return
        
        if parsed.path == "/positions/open":
            account_id = int(query.get("account_id", ["1"])[0])
            refresh = query.get("refresh", ["true"])[0].lower() == "true"
            payload, status = get_open_positions(account_id, refresh)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/positions/recent":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["20"])[0])
            payload, status = get_recent_positions(account_id, limit)
            self._send_json(payload, status=status)
            return
        
        if parsed.path == "/orders/open":
            account_id = int(query.get("account_id", ["1"])[0])
            payload, status = get_open_orders(account_id)
            self._send_json(payload, status=status)
            return
        
        if parsed.path == "/bootstrap/performance":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_performance(account_id))
            return
        
        if parsed.path == "/bootstrap/system-health":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_system_health(account_id))
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()