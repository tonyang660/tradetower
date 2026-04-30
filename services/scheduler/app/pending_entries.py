from api_clients import (
    check_entry_gate_for_symbol,
    fetch_latest_price,
    fetch_open_positions,
    ingest_pending_loop_event_to_evaluator,
    run_risk_engine,
    submit_entry_to_paper_execution,
)
from config import ACCOUNT_ID, ENTRY_RETRY_MAX_ATTEMPTS
from cycle_utils import (
    build_repriced_paper_payload,
    build_repriced_risk_payload,
    clear_pending_entry,
    get_pending_entry_symbols,
    store_pending_entry,
)
from state import LAST_PENDING_ENTRY_LOOP_RESULT, PENDING_ENTRY_ORDERS
from time_utils import iso_now


def process_pending_entries_once():
    results = []
    fills = 0
    pending_count = 0
    cancelled = 0
    blocked = 0
    errors_count = 0

    for symbol in list(get_pending_entry_symbols()):
        pending = PENDING_ENTRY_ORDERS.get(symbol)
        if not pending:
            continue

        pending_payload = dict(pending["paper_payload"])
        attempt_number = int(pending.get("attempt_number", 1))
        originating_cycle_id = pending_payload.get("originating_cycle_id")

        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "positions_check",
                "error": positions_error,
            })
            continue

        current_open_symbols = {p["symbol"] for p in open_positions}
        if symbol in current_open_symbols:
            clear_pending_entry(symbol)

            event_payload = {
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_FILLED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "action": "CLEARED_ALREADY_OPEN",
                },
            }
            ingest_pending_loop_event_to_evaluator(event_payload)

            fills += 1
            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "CLEARED_ALREADY_OPEN",
                "attempt_number": attempt_number,
            })
            continue

        retry_gate, retry_gate_error = check_entry_gate_for_symbol(
            ACCOUNT_ID,
            symbol,
            ignore_pending_order=True,
        )
        if retry_gate_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "entry_gate",
                "error": retry_gate_error,
            })
            continue

        if not retry_gate.get("trade_allowed", False):
            reason_codes = retry_gate.get("reason_codes", [])

            # If capacity is full, stop retrying this pending entry.
            # A fresh candidate can be generated later once capacity opens again.
            if "MAX_CONCURRENT_POSITIONS_REACHED" in reason_codes:
                clear_pending_entry(symbol)
                cancelled += 1

                event_payload = {
                    "account_id": ACCOUNT_ID,
                    "cycle_id": originating_cycle_id,
                    "symbol": symbol,
                    "event_type": "ENTRY_CANCELLED",
                    "attempt_number": attempt_number,
                    "source": "pending_entry_loop",
                    "details": {
                        "reason": "MAX_CONCURRENT_POSITIONS_REACHED",
                        "reason_codes": reason_codes,
                    },
                }
                ingest_pending_loop_event_to_evaluator(event_payload)

                results.append({
                    "symbol": symbol,
                    "ok": True,
                    "action": "CANCELLED_CAPACITY_BLOCKED",
                    "reason_codes": reason_codes,
                })
                continue

            blocked += 1

            event_payload = {
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_BLOCKED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "reason_codes": reason_codes,
                },
            }
            ingest_pending_loop_event_to_evaluator(event_payload)

            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "BLOCKED",
                "reason_codes": reason_codes,
            })
            continue

        latest_price, latest_price_error = fetch_latest_price(symbol)
        if latest_price_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "latest_price",
                "error": latest_price_error,
            })
            continue

        repriced_risk_payload = build_repriced_risk_payload(
            ACCOUNT_ID,
            pending_payload,
            latest_price,
        )

        risk_result, risk_error = run_risk_engine(repriced_risk_payload)
        if risk_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "risk_engine",
                "error": risk_error,
            })
            continue

        if not risk_result.get("approved", False):
            clear_pending_entry(symbol)
            cancelled += 1

            event_payload = {
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_CANCELLED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "reason": "RISK_REJECTED",
                    "risk_result": risk_result,
                },
            }
            ingest_pending_loop_event_to_evaluator(event_payload)

            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "CANCELLED_RISK_REJECTED",
                "risk_result": risk_result,
            })
            continue

        new_attempt_number = attempt_number + 1

        paper_payload = build_repriced_paper_payload(
            ACCOUNT_ID,
            pending_payload,
            risk_result,
            latest_price,
        )
        paper_payload["attempt_number"] = new_attempt_number
        paper_payload["max_attempts"] = ENTRY_RETRY_MAX_ATTEMPTS
        paper_payload["originating_cycle_id"] = originating_cycle_id

        paper_result, paper_error = submit_entry_to_paper_execution(paper_payload)
        if paper_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "paper_execution",
                "error": paper_error,
            })
            continue

        action = str(paper_result.get("action", "")).upper()

        if action == "ENTRY_PENDING":
            store_pending_entry(symbol, paper_payload, {
                "attempt_number": new_attempt_number,
            })
            pending_count += 1
        else:
            clear_pending_entry(symbol)

        if action == "ENTRY_FILLED":
            fills += 1
        elif action.startswith("ENTRY_CANCELLED") or action.startswith("CANCELLED"):
            cancelled += 1

        event_payload = {
            "account_id": ACCOUNT_ID,
            "cycle_id": originating_cycle_id,
            "symbol": symbol,
            "event_type": action,
            "attempt_number": new_attempt_number,
            "source": "pending_entry_loop",
            "details": {
                "paper_result": paper_result,
            },
        }
        ingest_pending_loop_event_to_evaluator(event_payload)

        results.append({
            "symbol": symbol,
            "ok": True,
            "action": action,
            "attempt_number": new_attempt_number,
            "paper_result": paper_result,
        })

    result = {
        "ok": True,
        "processed": len(results),
        "fills": fills,
        "pending": pending_count,
        "cancelled": cancelled,
        "blocked": blocked,
        "errors": errors_count,
        "results": results,
        "timestamp": iso_now(),
    }

    LAST_PENDING_ENTRY_LOOP_RESULT.update(result)

    return result
