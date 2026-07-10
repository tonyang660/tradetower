from config import ENTRY_RETRY_MAX_ATTEMPTS, PENDING_ENTRY_LOOP_INTERVAL_SECONDS
from state import PENDING_ENTRY_ORDERS
from time_utils import iso_now


def build_pending_entry_status():
    items = []

    for symbol, pending in PENDING_ENTRY_ORDERS.items():
        items.append({
            "symbol": symbol,
            "attempt_number": int(pending.get("attempt_number", 1)),
            "updated_at": pending.get("updated_at"),
            "order_type": pending.get("paper_payload", {}).get("order_type"),
            "position_side": pending.get("paper_payload", {}).get("position_side"),
            "entry_price": pending.get("paper_payload", {}).get("entry_price"),
        })

    items.sort(key=lambda x: x["symbol"])

    return {
        "pending_entries_count": len(items),
        "pending_entry_loop_interval_seconds": PENDING_ENTRY_LOOP_INTERVAL_SECONDS,
        "pending_entry_max_attempts": ENTRY_RETRY_MAX_ATTEMPTS,
        "pending_entries": items,
    }


def build_risk_payload_from_strategy(account_id: int, strategy_result: dict):
    return {
        "account_id": account_id,
        "symbol": strategy_result["symbol"],
        "position_side": strategy_result["decision"],
        "entry_order_type": strategy_result["entry_order_type"],
        "entry_price": strategy_result["entry_price"],
        "stop_loss": strategy_result["stop_loss"],
    }


def build_repriced_risk_payload(account_id: int, pending_payload: dict, new_entry_price: float):
    return {
        "account_id": account_id,
        "symbol": pending_payload["symbol"],
        "position_side": pending_payload["position_side"],
        "entry_order_type": "limit",
        "entry_price": new_entry_price,
        "stop_loss": float(pending_payload["stop_loss"]),
    }


def build_repriced_paper_payload(account_id: int, pending_payload: dict, risk_result: dict, new_entry_price: float):
    payload = {
        "account_id": account_id,
        "symbol": pending_payload["symbol"],
        "selected_strategy": pending_payload.get("selected_strategy"),
        "regime": pending_payload.get("regime"),
        "strategy_confidence": pending_payload.get("strategy_confidence"),
        "strategy_reason_tags": pending_payload.get("strategy_reason_tags", []),
        "position_side": pending_payload["position_side"],
        "order_type": "limit",
        "entry_price": new_entry_price,
        "stop_loss": float(pending_payload["stop_loss"]),
    }

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    payload["attempt_number"] = int(pending_payload.get("attempt_number", 1))
    payload["max_attempts"] = ENTRY_RETRY_MAX_ATTEMPTS

    if pending_payload.get("order_id") is not None:
        payload["order_id"] = int(pending_payload["order_id"])

    return payload


def build_paper_execution_payload(account_id: int, strategy_result: dict, risk_result: dict):
    payload = {
        "account_id": account_id,
        "symbol": strategy_result["symbol"],
        "selected_strategy": strategy_result.get("selected_strategy"),
        "regime": strategy_result.get("regime"),
        "strategy_confidence": strategy_result.get("confidence"),
        "strategy_reason_tags": strategy_result.get("reason_tags", []),
        "position_side": strategy_result["decision"],
        "order_type": strategy_result["entry_order_type"],
        "entry_price": strategy_result["entry_price"],
        "stop_loss": strategy_result["stop_loss"],
    }

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    if "entry_order_type" in payload and "order_type" not in payload:
        payload["order_type"] = payload["entry_order_type"]

    return payload


def get_pending_entry_symbols():
    return set(PENDING_ENTRY_ORDERS.keys())


def store_pending_entry(symbol: str, paper_payload: dict, paper_result: dict):
    current_attempt_number = int(
        paper_result.get("attempt_number", paper_payload.get("attempt_number", 1))
    )

    stored_payload = dict(paper_payload)
    if paper_result.get("order_id") is not None:
        stored_payload["order_id"] = int(paper_result["order_id"])

    PENDING_ENTRY_ORDERS[symbol] = {
        "paper_payload": stored_payload,
        "attempt_number": current_attempt_number,
        "updated_at": iso_now(),
    }


def clear_pending_entry(symbol: str):
    PENDING_ENTRY_ORDERS.pop(symbol, None)


def build_retry_payload(symbol: str):
    pending = PENDING_ENTRY_ORDERS.get(symbol)
    if not pending:
        return None

    payload = dict(pending["paper_payload"])
    payload["attempt_number"] = int(pending.get("attempt_number", 1))
    payload["max_attempts"] = ENTRY_RETRY_MAX_ATTEMPTS
    return payload


def extract_candidate_symbols(candidate_payload: dict):
    symbols = []
    for item in candidate_payload.get("candidates", []):
        symbol = item.get("symbol")
        if symbol:
            symbols.append(symbol.upper())
    return symbols
