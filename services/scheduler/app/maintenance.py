from api_clients import check_maintenance, fetch_open_positions, run_maintenance
from config import ACCOUNT_ID
from state import LAST_MAINTENANCE_LOOP_RESULT, PENDING_EXIT_ORDERS
from time_utils import iso_now


def _pending_exit_key(account_id: int, symbol: str) -> str:
    return f"{int(account_id)}:{str(symbol).upper()}"


def process_open_position_maintenance_once(account_id: int | None = None):
    account_id = int(account_id or ACCOUNT_ID)
    results = []
    checked = 0
    actions_triggered = 0
    no_action = 0
    blocked = 0
    errors_count = 0

    open_positions, positions_error = fetch_open_positions(account_id)
    if positions_error:
        result = {
            "ok": False,
            "timestamp": iso_now(),
            "checked": 0,
            "actions_triggered": 0,
            "no_action": 0,
            "blocked": 0,
            "errors": 1,
            "results": [{
                "ok": False,
                "stage": "positions_fetch",
                "error": positions_error,
            }],
        }

        LAST_MAINTENANCE_LOOP_RESULT.update(result)
        return result

    for pos in open_positions:
        symbol = pos["symbol"]
        checked += 1

        guard_result, guard_error = check_maintenance(account_id, symbol)
        if guard_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "trade_guardian",
                "error": guard_error,
            })
            continue

        if not guard_result.get("maintenance_allowed", False):
            blocked += 1
            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "MAINTENANCE_BLOCKED",
                "reason_codes": guard_result.get("reason_codes", []),
            })
            continue

        maintenance_result, maintenance_error = run_maintenance(account_id, symbol)
        if maintenance_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "paper_execution",
                "error": maintenance_error,
            })
            continue

        if not maintenance_result.get("ok", False):
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "paper_execution",
                "error": maintenance_result.get("error", "maintenance_check_failed"),
                "details": maintenance_result,
            })
            continue

        action = str(maintenance_result.get("action", "NO_ACTION")).upper()

        if action == "STOP_LOSS_PENDING":
            order_id = maintenance_result.get("order_id")
            if order_id is not None:
                pending_key = _pending_exit_key(account_id, symbol)
                existing_state = PENDING_EXIT_ORDERS.get(pending_key)

                if existing_state is None:
                    PENDING_EXIT_ORDERS[pending_key] = {
                        "account_id": account_id,
                        "symbol": symbol,
                        "order_id": int(order_id),
                        "attempt_number": 1,
                        "updated_at": iso_now(),
                        "requested_price": float(
                            maintenance_result.get("limit_price")
                            or maintenance_result.get("trigger_price")
                            or 0.0
                        ),
                        "original_stop_price": float(
                            maintenance_result.get("trigger_price") or 0.0
                        ),
                        "side": str(pos["side"]).lower(),
                        "trigger_seen_count": 1,
                    }
                else:
                    PENDING_EXIT_ORDERS[pending_key] = {
                        **existing_state,
                        "account_id": account_id,
                        "symbol": symbol,
                        "order_id": int(order_id),
                        "updated_at": iso_now(),
                        "requested_price": float(
                            maintenance_result.get("limit_price")
                            or existing_state.get("requested_price")
                            or maintenance_result.get("trigger_price")
                            or 0.0
                        ),
                        "original_stop_price": float(
                            existing_state.get("original_stop_price")
                            or maintenance_result.get("trigger_price")
                            or 0.0
                        ),
                        "side": str(existing_state.get("side") or pos["side"]).lower(),
                    }

        results.append({
            "symbol": symbol,
            "ok": True,
            "action": action,
            "execution_event": maintenance_result.get("execution_event"),
            "guardian_result": maintenance_result.get("guardian_result"),
        })

        if action != "NO_ACTION":
            actions_triggered += 1
        else:
            no_action += 1

    result = {
        "ok": True,
        "timestamp": iso_now(),
        "account_id": account_id,
        "checked": checked,
        "actions_triggered": actions_triggered,
        "no_action": no_action,
        "blocked": blocked,
        "errors": errors_count,
        "results": results,
    }

    LAST_MAINTENANCE_LOOP_RESULT.update(result)

    return result
