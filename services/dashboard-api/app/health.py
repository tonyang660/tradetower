from datetime import datetime, timezone, timedelta
import time

import requests

from config import (
    SERVICE_NAME,
    EVALUATOR_BASE_URL,
    SCHEDULER_BASE_URL,
    TRADE_GUARDIAN_BASE_URL,
    CANDIDATE_FILTER_BASE_URL,
    STRATEGY_ENGINE_BASE_URL,
    RISK_ENGINE_BASE_URL,
    PAPER_EXECUTION_BASE_URL,
    API_GATEWAY_BASE_URL,
    DATA_HUB_BASE_URL,
)
from time_utils import iso_now


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
