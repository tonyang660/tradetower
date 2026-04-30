from datetime import datetime, timezone

from config import (
    PORT,
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
from health import local_service_health, service_health_check
from http_client import get_json
from time_utils import iso_now, parse_iso_ts


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
        "order_cycle": {
            "pending_entry_loop_interval_seconds": scheduler_health.get("pending_entry_loop_interval_seconds") if isinstance(scheduler_health, dict) else None,
            "pending_entry_max_attempts": scheduler_health.get("pending_entry_max_attempts") if isinstance(scheduler_health, dict) else None,
            "pending_entries_count": scheduler_health.get("pending_entries_count") if isinstance(scheduler_health, dict) else None,
            "pending_entries": scheduler_health.get("pending_entries", []) if isinstance(scheduler_health, dict) else [],
            "last_pending_entry_loop_at": scheduler_health.get("last_pending_entry_loop_at") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_processed": scheduler_health.get("last_pending_entry_loop_processed") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_fills": scheduler_health.get("last_pending_entry_loop_fills") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_pending": scheduler_health.get("last_pending_entry_loop_pending") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_cancelled": scheduler_health.get("last_pending_entry_loop_cancelled") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_blocked": scheduler_health.get("last_pending_entry_loop_blocked") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_errors": scheduler_health.get("last_pending_entry_loop_errors") if isinstance(scheduler_health, dict) else None,
            "last_pending_entry_loop_results": scheduler_health.get("last_pending_entry_loop_results", []) if isinstance(scheduler_health, dict) else [],
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
            "pending_entry_loop_interval_seconds": scheduler_health.get("pending_entry_loop_interval_seconds") if isinstance(scheduler_health, dict) else None,
            "pending_entry_max_attempts": scheduler_health.get("pending_entry_max_attempts") if isinstance(scheduler_health, dict) else None,
            "pending_entries_count": scheduler_health.get("pending_entries_count") if isinstance(scheduler_health, dict) else None,
        },
        "issues": issues,
        "errors": errors,
    }
