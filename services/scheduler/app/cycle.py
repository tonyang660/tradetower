import json
import traceback

from api_clients import (
    check_entry_gate,
    check_entry_gate_for_symbol,
    fetch_open_positions,
    fetch_pending_entry_orders,
    fetch_trade_guardian_status,
    ingest_cycle_summary_to_evaluator,
    ingest_equity_snapshot_to_evaluator,
    run_candidate_filter,
    run_mark_to_market_refresh,
    run_risk_engine,
    run_strategy_engine,
)
from config import (
    ACCOUNT_ID,
    ENTRY_RETRY_MAX_ATTEMPTS,
    MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST,
)
from cycle_utils import (
    build_candidate_filter_cycle_summary,
    build_paper_execution_payload,
    build_risk_payload_from_strategy,
    extract_candidate_symbols,
    is_risk_approved,
    required_risk_payload_fields_missing,
    summarize_risk_result_for_cycle,
)
from execution_router import execute_entry
from market_data import refresh_symbol_candles
from symbol_universe import load_symbol_universe_report
from time_utils import iso_now


def run_one_cycle():
    started_at = iso_now()
    cycle_id = started_at

    summary = {
        "ok": True,
        "cycle_id": cycle_id,
        "started_at": started_at,
        "completed_at": None,
        "symbol_universe": None,
        "enabled_symbols": [],
        "refreshed_symbols_count": 0,
        "refresh_results": [],
        "pending_entries_before_cycle": 0,
        "pending_entries_after_cycle": 0,
        "open_positions_before_maintenance_count": 0,
        "open_positions_count": 0,
        "maintenance": {
            "checked": 0,
            "actions_triggered": 0,
            "no_action": 0,
            "errors": 0,
            "results": [],
        },
        "entry_gate": None,
        "entry_eligible_symbols": [],
        "candidate_filter": None,
        "candidate_filter_summary": None,
        "strategy_engine": {
            "analyzed": 0,
            "candidate_symbols": [],
            "trade_candidates": 0,
            "observe_candidates": 0,
            "no_trade": 0,
            "accepted": 0,
            "results": [],
        },
        "risk_engine": {
            "checked": 0,
            "approved": 0,
            "results": [],
            "compatibility_version": "phase5_step11_scheduler_paper_compatibility",
        },
        "final_entry_gate": {
            "checked": 0,
            "blocked": 0,
            "results": [],
        },
        "paper_execution": {
            "submitted": 0,
            "fills": 0,
            "pending_retries": 0,
            "results": [],
            "compatibility_version": "phase5_step11_scheduler_paper_compatibility",
        },
        "errors": [],
    }

    try:
        guardian_status, guardian_status_error = fetch_trade_guardian_status(ACCOUNT_ID)
        if guardian_status_error:
            summary["ok"] = False
            summary["errors"].append(guardian_status_error)
            summary["completed_at"] = iso_now()
            return summary

        execution_mode = guardian_status["execution_mode"]
        summary["execution_mode"] = execution_mode

        universe_report = load_symbol_universe_report()
        enabled_symbols = universe_report["enabled_symbols"]
        summary["symbol_universe"] = universe_report
        summary["enabled_symbols"] = enabled_symbols

        if not enabled_symbols:
            summary["ok"] = False
            summary["errors"].append("no_enabled_symbols_after_validation")
            summary["completed_at"] = iso_now()
            return summary

        pending_entries, pending_entries_error = fetch_pending_entry_orders(
            ACCOUNT_ID
        )
        if pending_entries_error:
            summary["ok"] = False
            summary["errors"].append(pending_entries_error)
            summary["completed_at"] = iso_now()
            return summary

        summary["pending_entries_before_cycle"] = len(pending_entries)

        for symbol in enabled_symbols:
            refresh_results = refresh_symbol_candles(symbol)
            summary["refresh_results"].extend(refresh_results)

        refreshed_ok_symbols = set()
        for item in summary["refresh_results"]:
            if item.get("ok"):
                refreshed_ok_symbols.add(item["symbol"])
        summary["refreshed_symbols_count"] = len(refreshed_ok_symbols)

        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            summary["errors"].append(positions_error)
            open_positions = []

        summary["open_positions_before_maintenance_count"] = len(open_positions)
        summary["open_positions_count"] = len(open_positions)

        current_open_symbols = [p["symbol"] for p in open_positions]

        entry_gate, entry_error = check_entry_gate(ACCOUNT_ID)
        if entry_error:
            summary["errors"].append(entry_error)
            summary["entry_gate"] = {
                "trade_allowed": False,
                "reason_codes": [entry_error],
            }
        else:
            summary["entry_gate"] = entry_gate

        entry_allowed = bool(summary["entry_gate"].get("trade_allowed", False))

        entry_eligible_symbols = []
        if entry_allowed:
            pending_symbols = {
                str(order.get("symbol", "")).upper()
                for order in pending_entries
                if order.get("symbol")
            }

            for symbol in refreshed_ok_symbols:
                if symbol in current_open_symbols:
                    continue
                if symbol in pending_symbols:
                    continue
                entry_eligible_symbols.append(symbol)

        summary["entry_eligible_symbols"] = sorted(entry_eligible_symbols)

        candidate_filter_payload, candidate_error = run_candidate_filter(
            ACCOUNT_ID,
            summary["entry_eligible_symbols"],
        )
        if candidate_error:
            summary["errors"].append(candidate_error)
            candidate_filter_payload = {
                "ok": False,
                "error": candidate_error,
                "schema_version": "candidate_filter_v2",
                "candidate_filter_mode": "lenient_screener",
                "input_symbols_count": len(summary["entry_eligible_symbols"]),
                "candidates": [],
                "rejected": [],
                "unavailable": [],
            }

        summary["candidate_filter"] = candidate_filter_payload
        summary["candidate_filter_summary"] = build_candidate_filter_cycle_summary(
            candidate_filter_payload
        )

        candidate_symbols = extract_candidate_symbols(candidate_filter_payload)
        summary["strategy_engine"]["candidate_symbols"] = candidate_symbols

        for symbol in candidate_symbols:
            strategy_payload, strategy_error = run_strategy_engine(symbol)
            if strategy_error:
                summary["errors"].append(strategy_error)
                summary["strategy_engine"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": strategy_error,
                })
                continue

            summary["strategy_engine"]["analyzed"] += 1
            summary["strategy_engine"]["results"].append(strategy_payload)

            decision = strategy_payload.get("decision")
            if decision == "trade":
                summary["strategy_engine"]["trade_candidates"] += 1
            elif decision == "observe":
                summary["strategy_engine"]["observe_candidates"] += 1
            else:
                summary["strategy_engine"]["no_trade"] += 1

        trade_candidates = [
            item for item in summary["strategy_engine"]["results"]
            if item.get("ok") and item.get("decision") == "trade"
        ]

        for strategy_payload in trade_candidates:
            risk_payload = build_risk_payload_from_strategy(
                ACCOUNT_ID,
                strategy_payload,
            )
            risk_result, risk_error = run_risk_engine(risk_payload)
            if risk_error:
                summary["errors"].append(risk_error)
                summary["risk_engine"]["results"].append({
                    "symbol": strategy_payload.get("symbol"),
                    "ok": False,
                    "approved": False,
                    "risk_decision": "rejected",
                    "reason_codes": [risk_error],
                })
                continue

            summary["risk_engine"]["checked"] += 1

            if isinstance(risk_result, dict):
                risk_result["scheduler_risk_summary"] = summarize_risk_result_for_cycle(
                    risk_result
                )
            summary["risk_engine"]["results"].append(risk_result)

            if is_risk_approved(risk_result):
                missing_fields = required_risk_payload_fields_missing(risk_result)
                if missing_fields:
                    risk_result["approved"] = False
                    risk_result["risk_decision"] = "rejected"
                    risk_result.setdefault("reason_codes", []).append(
                        "RISK_APPROVAL_PAYLOAD_MISSING_FIELDS"
                    )
                    risk_result["missing_fields"] = missing_fields
                    summary["errors"].append(
                        f"risk_approval_payload_missing_fields_{risk_result.get('symbol')}:"
                        f"{','.join(missing_fields)}"
                    )
                    continue

                summary["risk_engine"]["approved"] += 1

        approved_risk_results = [
            item for item in summary["risk_engine"]["results"]
            if is_risk_approved(item)
        ]

        for risk_result in approved_risk_results:
            symbol = risk_result["symbol"]

            final_gate, final_gate_error = check_entry_gate_for_symbol(
                ACCOUNT_ID,
                symbol,
            )
            if final_gate_error:
                summary["errors"].append(final_gate_error)
                final_gate = {
                    "trade_allowed": False,
                    "reason_codes": [final_gate_error],
                    "symbol": symbol,
                }

            final_gate["symbol"] = symbol
            summary["final_entry_gate"]["checked"] += 1
            summary["final_entry_gate"]["results"].append(final_gate)

            if not final_gate.get("trade_allowed"):
                summary["final_entry_gate"]["blocked"] += 1
                continue

            strategy_payload = next(
                (
                    item for item in trade_candidates
                    if item.get("symbol") == symbol
                ),
                None,
            )

            if strategy_payload is None:
                summary["errors"].append(f"missing_strategy_payload_for_{symbol}")
                continue

            execution_payload = build_paper_execution_payload(
                account_id=ACCOUNT_ID,
                cycle_id=cycle_id,
                strategy_result=strategy_payload,
                risk_result=risk_result,
                attempt_number=1,
                max_attempts=ENTRY_RETRY_MAX_ATTEMPTS,
            )

            execution_result, execution_error = execute_entry(
                execution_mode,
                execution_payload,
            )
            if execution_error:
                summary["errors"].append(execution_error)
                summary["paper_execution"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": execution_error,
                })
                continue

            summary["paper_execution"]["submitted"] += 1
            summary["paper_execution"]["results"].append(execution_result)

            action = execution_result.get("action")
            if action == "ENTRY_FILLED":
                summary["paper_execution"]["fills"] += 1
            elif action == "ENTRY_PENDING":
                summary["paper_execution"]["pending_retries"] += 1

        pending_entries_after, pending_entries_after_error = (
            fetch_pending_entry_orders(ACCOUNT_ID)
        )
        if pending_entries_after_error:
            summary["errors"].append(pending_entries_after_error)
        else:
            summary["pending_entries_after_cycle"] = len(
                pending_entries_after
            )

        if MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST:
            _, mtm_error = run_mark_to_market_refresh(ACCOUNT_ID)
            if mtm_error:
                summary["errors"].append(mtm_error)

        latest_status, latest_status_error = fetch_trade_guardian_status(ACCOUNT_ID)
        if latest_status_error:
            summary["errors"].append(latest_status_error)
        else:
            _, evaluator_equity_error = ingest_equity_snapshot_to_evaluator(
                latest_status
            )
            if evaluator_equity_error:
                summary["errors"].append(evaluator_equity_error)

        summary["completed_at"] = iso_now()

        evaluator_payload, evaluator_error = ingest_cycle_summary_to_evaluator(
            summary
        )
        if evaluator_error:
            summary["errors"].append(evaluator_error)
        else:
            summary["evaluator_ingest"] = evaluator_payload

        return summary

    except Exception as exc:
        summary["ok"] = False
        summary["completed_at"] = iso_now()
        summary["errors"].append(str(exc))
        summary["traceback"] = traceback.format_exc()
        return summary
