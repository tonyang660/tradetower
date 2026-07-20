from config import EVALUATOR_BASE_URL, SCHEDULER_BASE_URL, TRADE_GUARDIAN_BASE_URL
from health import get_market_session_banner
from http_client import get_json, post_json
from time_utils import iso_now


def _extract_latest_cycle_entry_gate(cycle_latest):
    if not isinstance(cycle_latest, dict):
        return None
    cycle = cycle_latest.get("cycle")
    if not isinstance(cycle, dict):
        return None
    summary = cycle.get("summary") or {}
    entry_gate = summary.get("entry_gate")
    return entry_gate if isinstance(entry_gate, dict) else None


def _fetch_current_entry_gate(account_id: int, cycle_latest):
    payload, status_code, error = post_json(
        f"{TRADE_GUARDIAN_BASE_URL}/guard/check-entry",
        {"account_id": account_id},
        timeout=10,
    )

    if error or status_code != 200 or not isinstance(payload, dict):
        fallback = _extract_latest_cycle_entry_gate(cycle_latest)
        if fallback is not None:
            return fallback, {
                "source": "trade_guardian_entry_gate",
                "error": error or payload,
                "fallback": "latest_cycle.entry_gate",
            }
        return None, {
            "source": "trade_guardian_entry_gate",
            "error": error or payload,
        }

    return payload, None


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
    entry_gate, entry_gate_error = _fetch_current_entry_gate(account_id, cycle_latest)

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
    if entry_gate_error:
        errors.append(entry_gate_error)

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

    entry_gate = entry_gate if isinstance(entry_gate, dict) else {
        "trade_allowed": len(disable_reasons) == 0,
        "reason_codes": disable_reasons,
        "source": "account_status_fallback",
    }

    entry_allowed = bool(entry_gate.get("trade_allowed", False))
    entry_reason_codes = entry_gate.get("reason_codes", []) or []

    weekly_pnl = float(account_status.get("weekly_pnl", 0.0) or 0.0)
    weekly_pnl_pct = float(account_status.get("weekly_pnl_pct", 0.0) or 0.0)
    weekly_pnl_loss_threshold_pct = 5.0
    weekly_pnl_score_penalty = 10
    weekly_pnl_base_threshold = 75
    weekly_pnl_penalty_active = weekly_pnl_pct <= -weekly_pnl_loss_threshold_pct
    weekly_pnl_penalty = {
        "active": weekly_pnl_penalty_active,
        "weekly_pnl": round(weekly_pnl, 8),
        "weekly_pnl_pct": round(weekly_pnl_pct, 6),
        "weekly_pnl_loss_pct": round(abs(weekly_pnl_pct) if weekly_pnl_pct < 0 else 0.0, 6),
        "threshold_pct": weekly_pnl_loss_threshold_pct,
        "score_penalty": weekly_pnl_score_penalty if weekly_pnl_penalty_active else 0,
        "base_trade_score_threshold": weekly_pnl_base_threshold,
        "required_trade_score_threshold": weekly_pnl_base_threshold + weekly_pnl_score_penalty if weekly_pnl_penalty_active else weekly_pnl_base_threshold,
        "reason_code": "WEEKLY_PNL_THRESHOLD_PENALTY_ACTIVE" if weekly_pnl_penalty_active else None,
        "label": (
            f"Penalty applied: +{weekly_pnl_score_penalty} weekly_pnl loss exceeds {weekly_pnl_loss_threshold_pct}%"
            if weekly_pnl_penalty_active
            else "No weekly_pnl threshold penalty"
        ),
    }

    consecutive_loss_cooldown_until = account_status.get("consecutive_loss_cooldown_until")

    trading_banner = {
        "trading_disabled": len(disable_reasons) > 0,
        "entry_blocked": not entry_allowed,
        "entry_allowed": entry_allowed,
        "reason_codes": disable_reasons,
        "entry_reason_codes": entry_reason_codes,
        "entry_gate": entry_gate,
        "weekly_pnl_penalty": weekly_pnl_penalty,
        "consecutive_loss_cooldown_until": consecutive_loss_cooldown_until,
        "message": (
            "Trading Suspended"
            if disable_reasons
            else "Entry Blocked"
            if not entry_allowed
            else "Trading Enabled"
        ),
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
