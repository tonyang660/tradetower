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
    build_paper_execution_payload,
    build_risk_payload_from_strategy,
    extract_candidate_symbols,
)
from execution_router import execute_entry
from market_data import refresh_symbol_candles
from symbol_universe import load_symbol_universe
from time_utils import iso_now


def run_one_cycle():
    started_at = iso_now()
    cycle_id = started_at

    summary = {
        "ok": True,
        "cycle_id": cycle_id,
        "started_at": started_at,
        "completed_at": None,
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
        "strategy_engine": {
            "analyzed": 0,
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
        },
        "errors": [],
    }

    try:
        # Resolve account execution mode once for this cycle.
        guardian_status, guardian_status_error = fetch_trade_guardian_status(ACCOUNT_ID)
        if guardian_status_error:
            summary["ok"] = False
            summary["errors"].append(guardian_status_error)
            summary["completed_at"] = iso_now()
            return summary

        execution_mode = guardian_status["execution_mode"]
        summary["execution_mode"] = execution_mode

        # Phase 0: load enabled symbol universe
        enabled_symbols = load_symbol_universe()
        summary["enabled_symbols"] = enabled_symbols

        pending_entries, pending_entries_error = fetch_pending_entry_orders(
            ACCOUNT_ID
        )
        if pending_entries_error:
            summary["ok"] = False
            summary["errors"].append(pending_entries_error)
            summary["completed_at"] = iso_now()
            return summary

        summary["pending_entries_before_cycle"] = len(pending_entries)

        # Phase 1: refresh market data for full enabled universe
        for symbol in enabled_symbols:
            refresh_results = refresh_symbol_candles(symbol)
            summary["refresh_results"].extend(refresh_results)

        refreshed_ok_symbols = set()
        for item in summary["refresh_results"]:
            if item.get("ok"):
                refreshed_ok_symbols.add(item["symbol"])
        summary["refreshed_symbols_count"] = len(refreshed_ok_symbols)

        # Phase 2: fetch current open positions snapshot only
        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            summary["errors"].append(positions_error)
            open_positions = []

        summary["open_positions_before_maintenance_count"] = len(open_positions)
        summary["open_positions_count"] = len(open_positions)

        current_open_symbols = [p["symbol"] for p in open_positions]
        maintenance_touched_symbols = set()

        # Phase 3: account-level entry gate
        entry_gate, entry_error = check_entry_gate(ACCOUNT_ID)
        if entry_error:
            summary["errors"].append(entry_error)
            summary["entry_gate"] = {
                "trade_allowed": False,
                "reason_codes": ["ENTRY_GATE_UNAVAILABLE"],
            }
        else:
            summary["entry_gate"] = entry_gate

        # Phase 4: build entry-eligible universe from persistent order state
        pending_symbols = {
            str(order["symbol"]).upper()
            for order in pending_entries
        }

        entry_eligible_symbols = [
            s for s in enabled_symbols
            if s not in current_open_symbols
            and s not in maintenance_touched_symbols
            and s not in pending_symbols
        ]
        summary["entry_eligible_symbols"] = entry_eligible_symbols

        # Phase 5: candidate filter only if account-level entry allowed
        if summary["entry_gate"] and summary["entry_gate"].get("trade_allowed", False):
            candidate_payload, candidate_error = run_candidate_filter(ACCOUNT_ID, entry_eligible_symbols)
            if candidate_error:
                summary["errors"].append(candidate_error)
                summary["candidate_filter"] = {
                    "ok": False,
                    "error": candidate_error,
                }
            else:
                summary["candidate_filter"] = candidate_payload
        else:
            summary["candidate_filter"] = {
                "ok": True,
                "skipped": True,
                "reason": "ENTRY_GATE_BLOCKED",
            }

        # Phase 6: deterministic downstream path
        if not summary["candidate_filter"] or not summary["candidate_filter"].get("ok", False):
            summary["errors"].append("candidate_filter_unavailable")
            candidate_symbols = []
        elif summary["candidate_filter"].get("skipped", False):
            candidate_symbols = []
        else:
            candidate_symbols = extract_candidate_symbols(summary["candidate_filter"])

        for symbol in candidate_symbols:
            summary["strategy_engine"]["analyzed"] += 1

            strategy_result, strategy_error = run_strategy_engine(symbol)
            if strategy_error:
                summary["strategy_engine"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": strategy_error,
                })
                continue

            summary["strategy_engine"]["results"].append(strategy_result)

            if not strategy_result.get("ok", False):
                continue

            decision = str(strategy_result.get("decision", "no_trade")).lower()

            if decision == "no_trade":
                summary["strategy_engine"]["no_trade"] += 1
                continue

            if decision == "observe":
                summary["strategy_engine"]["observe_candidates"] += 1
                continue

            if decision not in ("long", "short"):
                summary["errors"].append(
                    f"unexpected_strategy_decision_for_{symbol}: {decision}"
                )
                continue

            summary["strategy_engine"]["trade_candidates"] += 1
            summary["strategy_engine"]["accepted"] += 1

            # Phase 7: risk-engine
            risk_payload = build_risk_payload_from_strategy(ACCOUNT_ID, strategy_result)

            summary["risk_engine"]["checked"] += 1
            risk_result, risk_error = run_risk_engine(risk_payload)
            if risk_error:
                summary["risk_engine"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": risk_error,
                })
                continue

            summary["risk_engine"]["results"].append({
                "symbol": symbol,
                **risk_result,
            })

            if not risk_result.get("approved", False):
                continue

            summary["risk_engine"]["approved"] += 1

            # Phase 8: final symbol-level entry gate
            summary["final_entry_gate"]["checked"] += 1
            final_gate, final_gate_error = check_entry_gate_for_symbol(ACCOUNT_ID, symbol)
            if final_gate_error:
                summary["final_entry_gate"]["blocked"] += 1
                summary["final_entry_gate"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": final_gate_error,
                })
                continue

            summary["final_entry_gate"]["results"].append({
                "symbol": symbol,
                **final_gate,
            })

            if not final_gate.get("trade_allowed", False):
                summary["final_entry_gate"]["blocked"] += 1
                continue

            # Phase 9: route approved plan by the account execution mode.
            execution_payload = build_paper_execution_payload(
                ACCOUNT_ID,
                strategy_result,
                risk_result,
            )

            if execution_mode == "paper":
                execution_payload["attempt_number"] = 1
                execution_payload["max_attempts"] = (
                    ENTRY_RETRY_MAX_ATTEMPTS
                )
                execution_payload["originating_cycle_id"] = cycle_id

            execution_result, execution_error = execute_entry(
                execution_mode,
                execution_payload,
            )
            if execution_error:
                summary["paper_execution"]["results"].append({
                    "symbol": symbol,
                    "decision": strategy_result.get("decision"),
                    "selected_strategy": strategy_result.get("selected_strategy"),
                    "execution_mode": execution_mode,
                    "ok": False,
                    "error": execution_error,
                })
                continue

            summary["paper_execution"]["submitted"] += 1

            action = str(execution_result.get("action", "")).upper()

            if action == "ENTRY_FILLED":
                summary["paper_execution"]["fills"] += 1

            summary["paper_execution"]["results"].append({
                "symbol": symbol,
                "retry": False,
                "execution_mode": execution_mode,
                **execution_result,
            })

    except Exception as e:
        summary["ok"] = False
        summary["errors"].append(f"unhandled_cycle_exception: {str(e)}")
        summary["errors"].append(traceback.format_exc())

    summary["completed_at"] = iso_now()

    evaluator_result, evaluator_error = ingest_cycle_summary_to_evaluator(summary)
    if evaluator_error:
        summary["errors"].append(evaluator_error)
    else:
        summary["evaluator_ingest"] = evaluator_result

    # fetch live Trade Guardian account status and ingest equity snapshot
    tg_status = None

    if MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST:
        mtm_result, mtm_error = run_mark_to_market_refresh(ACCOUNT_ID)
        if mtm_error:
            summary["errors"].append(mtm_error)
        else:
            tg_status = mtm_result.get("account_status")
            summary["mark_to_market_refresh"] = {
                "ok": True,
                "positions_checked": mtm_result.get("positions_checked", 0),
                "positions_priced": mtm_result.get("positions_priced", 0),
                "pricing_errors": mtm_result.get("pricing_errors", []),
                "total_unrealized_pnl": mtm_result.get("total_unrealized_pnl", 0.0),
            }

    if tg_status is None:
        tg_status, tg_status_error = fetch_trade_guardian_status(ACCOUNT_ID)
        if tg_status_error:
            summary["errors"].append(tg_status_error)

    if tg_status is not None:
        equity_ingest_result, equity_ingest_error = ingest_equity_snapshot_to_evaluator(tg_status)
        if equity_ingest_error:
            summary["errors"].append(equity_ingest_error)
        else:
            summary["evaluator_equity_ingest"] = equity_ingest_result

    pending_entries_after, pending_entries_after_error = (
        fetch_pending_entry_orders(ACCOUNT_ID)
    )
    if pending_entries_after_error:
        summary["errors"].append(pending_entries_after_error)
    else:
        summary["pending_entries_after_cycle"] = len(
            pending_entries_after
        )

    return summary
