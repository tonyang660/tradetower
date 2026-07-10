from api_clients import (
    cancel_pending_entry_order,
    check_entry_gate_for_symbol,
    fetch_latest_price,
    fetch_open_positions,
    fetch_pending_entry_orders,
    fetch_trade_guardian_status,
    ingest_pending_loop_event_to_evaluator,
    run_risk_engine,
)
from config import ACCOUNT_ID, ENTRY_RETRY_MAX_ATTEMPTS
from cycle_utils import (
    build_repriced_paper_payload,
    build_repriced_risk_payload,
)
from execution_router import execute_entry
from state import LAST_PENDING_ENTRY_LOOP_RESULT
from time_utils import iso_now


def _loop_failure(error: str):
    result = {
        "ok": False,
        "processed": 0,
        "fills": 0,
        "pending": 0,
        "cancelled": 0,
        "blocked": 0,
        "errors": 1,
        "results": [{"error": error}],
        "timestamp": iso_now(),
    }
    LAST_PENDING_ENTRY_LOOP_RESULT.update(result)
    return result


def _cancel_entry(order_id: int):
    return cancel_pending_entry_order(
        account_id=ACCOUNT_ID,
        order_id=order_id,
    )


def process_pending_entries_once():
    guardian_status, guardian_status_error = fetch_trade_guardian_status(
        ACCOUNT_ID
    )
    if guardian_status_error:
        return _loop_failure(guardian_status_error)

    execution_mode = guardian_status["execution_mode"]

    if execution_mode != "paper":
        result = {
            "ok": True,
            "processed": 0,
            "fills": 0,
            "pending": 0,
            "cancelled": 0,
            "blocked": 0,
            "errors": 0,
            "execution_mode": execution_mode,
            "results": [],
            "timestamp": iso_now(),
        }
        LAST_PENDING_ENTRY_LOOP_RESULT.update(result)
        return result

    pending_orders, pending_orders_error = fetch_pending_entry_orders(
        ACCOUNT_ID
    )
    if pending_orders_error:
        return _loop_failure(pending_orders_error)

    open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
    if positions_error:
        return _loop_failure(positions_error)

    current_open_symbols = {p["symbol"] for p in open_positions}

    results = []
    fills = 0
    pending_count = 0
    cancelled = 0
    blocked = 0
    errors_count = 0

    for order in pending_orders:
        order_id = int(order["order_id"])
        symbol = str(order["symbol"]).upper()
        pending_payload = dict(order.get("execution_context") or {})
        attempt_number = int(order.get("retry_attempt", 0))
        max_attempts = int(
            order.get("max_retry_attempts")
            or pending_payload.get("max_attempts")
            or ENTRY_RETRY_MAX_ATTEMPTS
        )
        originating_cycle_id = (
            order.get("originating_cycle_id")
            or pending_payload.get("originating_cycle_id")
        )

        required_context = {
            "symbol",
            "position_side",
            "stop_loss",
        }
        missing_context = sorted(
            key
            for key in required_context
            if pending_payload.get(key) is None
        )
        if missing_context:
            errors_count += 1
            results.append({
                "order_id": order_id,
                "symbol": symbol,
                "ok": False,
                "stage": "pending_context",
                "error": "pending_entry_context_incomplete",
                "missing_fields": missing_context,
            })
            continue

        pending_payload["order_id"] = order_id
        pending_payload["attempt_number"] = attempt_number
        pending_payload["max_attempts"] = max_attempts
        pending_payload["originating_cycle_id"] = originating_cycle_id

        if symbol in current_open_symbols:
            cancel_result, cancel_error = _cancel_entry(order_id)
            if cancel_error:
                errors_count += 1
                results.append({
                    "order_id": order_id,
                    "symbol": symbol,
                    "ok": False,
                    "stage": "cancel_already_open",
                    "error": cancel_error,
                })
                continue

            ingest_pending_loop_event_to_evaluator({
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_FILLED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "order_id": order_id,
                    "action": "CANCELLED_STALE_ENTRY_ALREADY_OPEN",
                },
            })

            fills += 1
            results.append({
                "order_id": order_id,
                "symbol": symbol,
                "ok": True,
                "action": "CANCELLED_STALE_ENTRY_ALREADY_OPEN",
                "attempt_number": attempt_number,
                "cancel_result": cancel_result,
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
                "order_id": order_id,
                "symbol": symbol,
                "ok": False,
                "stage": "entry_gate",
                "error": retry_gate_error,
            })
            continue

        if not retry_gate.get("trade_allowed", False):
            reason_codes = retry_gate.get("reason_codes", [])

            if "MAX_CONCURRENT_POSITIONS_REACHED" in reason_codes:
                cancel_result, cancel_error = _cancel_entry(order_id)
                if cancel_error:
                    errors_count += 1
                    results.append({
                        "order_id": order_id,
                        "symbol": symbol,
                        "ok": False,
                        "stage": "cancel_capacity_blocked",
                        "error": cancel_error,
                    })
                    continue

                cancelled += 1
                ingest_pending_loop_event_to_evaluator({
                    "account_id": ACCOUNT_ID,
                    "cycle_id": originating_cycle_id,
                    "symbol": symbol,
                    "event_type": "ENTRY_CANCELLED",
                    "attempt_number": attempt_number,
                    "source": "pending_entry_loop",
                    "details": {
                        "order_id": order_id,
                        "reason": "MAX_CONCURRENT_POSITIONS_REACHED",
                        "reason_codes": reason_codes,
                    },
                })

                results.append({
                    "order_id": order_id,
                    "symbol": symbol,
                    "ok": True,
                    "action": "CANCELLED_CAPACITY_BLOCKED",
                    "reason_codes": reason_codes,
                    "cancel_result": cancel_result,
                })
                continue

            blocked += 1
            ingest_pending_loop_event_to_evaluator({
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_BLOCKED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "order_id": order_id,
                    "reason_codes": reason_codes,
                },
            })

            results.append({
                "order_id": order_id,
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
                "order_id": order_id,
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
                "order_id": order_id,
                "symbol": symbol,
                "ok": False,
                "stage": "risk_engine",
                "error": risk_error,
            })
            continue

        if not risk_result.get("approved", False):
            cancel_result, cancel_error = _cancel_entry(order_id)
            if cancel_error:
                errors_count += 1
                results.append({
                    "order_id": order_id,
                    "symbol": symbol,
                    "ok": False,
                    "stage": "cancel_risk_rejected",
                    "error": cancel_error,
                })
                continue

            cancelled += 1
            ingest_pending_loop_event_to_evaluator({
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_CANCELLED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "order_id": order_id,
                    "reason": "RISK_REJECTED",
                    "risk_result": risk_result,
                },
            })

            results.append({
                "order_id": order_id,
                "symbol": symbol,
                "ok": True,
                "action": "CANCELLED_RISK_REJECTED",
                "risk_result": risk_result,
                "cancel_result": cancel_result,
            })
            continue

        new_attempt_number = attempt_number + 1

        paper_payload = build_repriced_paper_payload(
            ACCOUNT_ID,
            pending_payload,
            risk_result,
            latest_price,
        )
        paper_payload["order_id"] = order_id
        paper_payload["attempt_number"] = new_attempt_number
        paper_payload["max_attempts"] = max_attempts
        paper_payload["originating_cycle_id"] = originating_cycle_id

        paper_result, paper_error = execute_entry(
            execution_mode,
            paper_payload,
        )
        if paper_error:
            errors_count += 1
            results.append({
                "order_id": order_id,
                "symbol": symbol,
                "ok": False,
                "stage": "paper_execution",
                "error": paper_error,
            })
            continue

        action = str(paper_result.get("action", "")).upper()

        if action == "ENTRY_PENDING":
            pending_count += 1
        elif action == "ENTRY_FILLED":
            fills += 1
        elif (
            action.startswith("ENTRY_CANCELLED")
            or action.startswith("CANCELLED")
        ):
            cancelled += 1

        ingest_pending_loop_event_to_evaluator({
            "account_id": ACCOUNT_ID,
            "cycle_id": originating_cycle_id,
            "symbol": symbol,
            "event_type": action,
            "attempt_number": new_attempt_number,
            "source": "pending_entry_loop",
            "details": {
                "order_id": order_id,
                "paper_result": paper_result,
            },
        })

        results.append({
            "order_id": order_id,
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
        "execution_mode": execution_mode,
        "timestamp": iso_now(),
    }

    LAST_PENDING_ENTRY_LOOP_RESULT.update(result)
    return result
