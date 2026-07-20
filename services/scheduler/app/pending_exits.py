from api_clients import (
    fetch_latest_price,
    fetch_open_positions,
    reprice_protective_order,
    run_maintenance,
)
from config import ACCOUNT_ID, EXIT_RETRY_MAX_ATTEMPTS
from state import LAST_PENDING_EXIT_LOOP_RESULT, PENDING_EXIT_ORDERS
from time_utils import iso_now

def _split_pending_exit_key(raw_key, state):
    text = str(raw_key)
    if ':' in text:
        prefix, symbol = text.split(':', 1)
        try:
            return int(prefix), symbol.upper()
        except Exception:
            pass
    return int(state.get('account_id', ACCOUNT_ID)), str(state.get('symbol', text)).upper()


def _pending_exit_key(account_id: int, symbol: str) -> str:
    return f"{int(account_id)}:{str(symbol).upper()}"

def process_pending_exits_once(account_id: int | None = None):
    account_id = int(account_id or ACCOUNT_ID)
    results = []
    filled = 0
    pending = 0
    forced_market = 0
    errors_count = 0

    for raw_key in list(PENDING_EXIT_ORDERS.keys()):
        state = PENDING_EXIT_ORDERS.get(raw_key)
        if not state:
            continue

        state_account_id, symbol = _split_pending_exit_key(raw_key, state)
        if int(state_account_id) != int(account_id):
            continue
        pending_key = _pending_exit_key(account_id, symbol)

        attempt_number = int(state.get("attempt_number", 1))
        order_id = int(state["order_id"])

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

        open_positions, positions_error = fetch_open_positions(account_id)
        if positions_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "positions_fetch",
                "error": positions_error,
            })
            continue

        matching_position = next((p for p in open_positions if p["symbol"] == symbol), None)
        if not matching_position:
            PENDING_EXIT_ORDERS.pop(raw_key, None)
            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "POSITION_ALREADY_CLOSED",
            })
            continue

        trigger_seen_count = int(state.get("trigger_seen_count", 1))

        if trigger_seen_count < 2:
            PENDING_EXIT_ORDERS[pending_key]["trigger_seen_count"] = trigger_seen_count + 1
            PENDING_EXIT_ORDERS[pending_key]["updated_at"] = iso_now()
            pending += 1
            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "STOP_LOSS_PENDING_GRACE",
                "attempt_number": attempt_number,
                "trigger_seen_count": trigger_seen_count,
            })
            continue

        previous_limit_price = float(state.get("requested_price", latest_price))
        original_stop_price = float(state.get("original_stop_price", latest_price))
        side = str(state.get("side", "")).lower()

        candidate_price = latest_price

        if side == "long":
            bounded_candidate = min(original_stop_price, candidate_price)
            new_limit_price = min(previous_limit_price, bounded_candidate)
        elif side == "short":
            bounded_candidate = max(original_stop_price, candidate_price)
            new_limit_price = max(previous_limit_price, bounded_candidate)
        else:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "pending_exit_state",
                "error": "unsupported_position_side",
            })
            continue

        reprice_result, reprice_error = reprice_protective_order(
            account_id,
            order_id,
            new_limit_price,
        )
        if reprice_error:
            errors_count += 1
            results.append({
                "symbol": symbol,
                "ok": False,
                "stage": "reprice_protective",
                "error": reprice_error,
            })
            continue

        use_force_market = attempt_number >= EXIT_RETRY_MAX_ATTEMPTS
        if use_force_market:
            forced_market += 1

        maintenance_result, maintenance_error = run_maintenance(
            account_id,
            symbol,
            force_market_stop_loss=use_force_market,
        )
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
                "error": maintenance_result.get("error", "maintenance_failed"),
                "details": maintenance_result,
            })
            continue

        action = str(maintenance_result.get("action", "")).upper()

        if action == "STOP_LOSS_PENDING":
            PENDING_EXIT_ORDERS[pending_key]["attempt_number"] = attempt_number + 1
            PENDING_EXIT_ORDERS[pending_key]["updated_at"] = iso_now()
            PENDING_EXIT_ORDERS[pending_key]["requested_price"] = float(new_limit_price)
            pending += 1
        else:
            PENDING_EXIT_ORDERS.pop(raw_key, None)

        if action in ("STOP_LOSS_TRIGGERED", "STOP_LOSS_APPLIED_POSITION_CLOSED"):
            filled += 1

        results.append({
            "symbol": symbol,
            "ok": True,
            "action": action,
            "attempt_number": attempt_number,
            "forced_market": use_force_market,
            "maintenance_result": maintenance_result,
            "reprice_result": reprice_result,
        })

    result = {
        "ok": True,
        "account_id": account_id,
        "timestamp": iso_now(),
        "processed": len(results),
        "filled": filled,
        "pending": pending,
        "forced_market": forced_market,
        "errors": errors_count,
        "results": results,
    }

    LAST_PENDING_EXIT_LOOP_RESULT.update(result)
    return result
