from config import EVALUATOR_BASE_URL, SCHEDULER_BASE_URL
from health import get_market_session_banner
from http_client import get_json
from time_utils import iso_now


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
