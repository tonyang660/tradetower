from datetime import datetime

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now


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
        "strategy_trade_candidates": int(strategy_engine.get("trade_candidates", strategy_engine.get("accepted", 0)) or 0),
        "strategy_observe_candidates": int(strategy_engine.get("observe_candidates", 0) or 0),
        "strategy_no_trade": int(strategy_engine.get("no_trade", 0) or 0),
        "strategy_accepted": int(strategy_engine.get("accepted", 0) or 0),
        "risk_approved": int(risk_engine.get("approved", 0) or 0),
        "paper_submitted": int(paper_execution.get("submitted", 0) or 0),
        "paper_pending_retries": int(paper_execution.get("pending_retries", 0) or 0),
        "paper_fills": int(paper_execution.get("fills", 0) or 0),
        "pending_entries_before_cycle": int(summary.get("pending_entries_before_cycle", 0) or 0),
        "pending_entries_after_cycle": int(summary.get("pending_entries_after_cycle", 0) or 0),
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
    strategy_analyzed = int(strategy_engine.get("analyzed", 0) or 0)
    strategy_trade_candidates = int(strategy_engine.get("trade_candidates", strategy_engine.get("accepted", 0)) or 0)
    strategy_observe_candidates = int(strategy_engine.get("observe_candidates", 0) or 0)
    strategy_no_trade = int(strategy_engine.get("no_trade", 0) or 0)

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
            "status": "ok" if strategy_analyzed > 0 else "idle",
            "primary_value": strategy_trade_candidates,
            "secondary_text": f"{strategy_observe_candidates} observe · {strategy_analyzed} analyzed · {strategy_no_trade} no-trade",
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
            "secondary_text": (
                f"{int(paper_execution.get('submitted', 0) or 0)} submitted · "
                f"{int(paper_execution.get('pending_retries', 0) or 0)} retries · "
                f"{int(summary.get('pending_entries_after_cycle', 0) or 0)} pending"
            ),
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
        "strategy_trade_candidates": int(strategy_engine.get("trade_candidates", strategy_engine.get("accepted", 0)) or 0),
        "strategy_observe_candidates": int(strategy_engine.get("observe_candidates", 0) or 0),
        "strategy_no_trade": int(strategy_engine.get("no_trade", 0) or 0),
        "strategy_accepted": int(strategy_engine.get("accepted", 0) or 0),
        "paper_pending_retries": int(paper_execution.get("pending_retries", 0) or 0),
        "paper_fills": int(paper_execution.get("fills", 0) or 0),
        "pending_entries_before_cycle": int(summary.get("pending_entries_before_cycle", 0) or 0),
        "pending_entries_after_cycle": int(summary.get("pending_entries_after_cycle", 0) or 0),
        "error_count": len(errors),
        "summary": summary,
    }


def build_cycle_trends(cycles: list[dict]):
    trend_cycles = list(reversed(cycles))

    candidates_per_cycle = []
    trade_candidates_per_cycle = []
    observe_per_cycle = []
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
        trade_candidates_per_cycle.append({
            "label": label,
            "value": int(strategy_engine.get("trade_candidates", strategy_engine.get("accepted", 0)) or 0),
        })
        observe_per_cycle.append({
            "label": label,
            "value": int(strategy_engine.get("observe_candidates", 0) or 0),
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
        "trade_candidates_per_cycle": trade_candidates_per_cycle,
        "observe_per_cycle": observe_per_cycle,
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
