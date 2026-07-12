from config import ENTRY_RETRY_MAX_ATTEMPTS, PENDING_ENTRY_LOOP_INTERVAL_SECONDS


def build_pending_entry_status(
    pending_entries: list[dict] | None = None,
):
    pending_entries = pending_entries or []

    items = []
    for order in pending_entries:
        context = order.get("execution_context") or {}

        items.append({
            "order_id": order.get("order_id"),
            "symbol": order.get("symbol"),
            "attempt_number": int(order.get("retry_attempt", 0)),
            "updated_at": order.get("updated_at"),
            "order_type": order.get("order_type"),
            "position_side": order.get("position_side"),
            "entry_price": order.get("requested_price"),
            "originating_cycle_id": order.get("originating_cycle_id"),
            "selected_strategy": context.get("selected_strategy"),
        })

    items.sort(key=lambda x: x["symbol"] or "")

    return {
        "pending_entries_count": len(items),
        "pending_entry_loop_interval_seconds": (
            PENDING_ENTRY_LOOP_INTERVAL_SECONDS
        ),
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


def build_paper_execution_payload(
    account_id: int,
    strategy_result: dict,
    risk_result: dict,
    cycle_id: str | None = None,
    attempt_number: int = 1,
    max_attempts: int = ENTRY_RETRY_MAX_ATTEMPTS,
):
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
        "attempt_number": int(attempt_number),
        "max_attempts": int(max_attempts),
    }

    if cycle_id is not None:
        payload["cycle_id"] = cycle_id
        payload["originating_cycle_id"] = cycle_id

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    if "entry_order_type" in payload and "order_type" not in payload:
        payload["order_type"] = payload["entry_order_type"]

    return payload


def _candidate_status(item: dict) -> str:
    return str(item.get("candidate_status") or "").lower()


def _candidate_symbol(item: dict) -> str | None:
    symbol = item.get("symbol")
    if not symbol:
        return None
    return str(symbol).upper()


def extract_candidate_symbols(candidate_payload: dict):
    """
    Return only symbols explicitly emitted in Candidate Filter's `candidates`
    bucket.

    This is the scheduler-side safety boundary for Phase 3.5:
    - candidates -> Strategy Engine
    - rejected -> skip
    - unavailable -> skip

    Backward compatibility:
    Older candidate-filter responses may not include candidate_status, so items
    inside the candidates list are treated as passable unless they explicitly say
    rejected/unavailable.
    """
    symbols = []
    seen = set()

    for item in candidate_payload.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue

        status = _candidate_status(item)
        tier = str(item.get("candidate_tier") or "").lower()

        if status in ("rejected", "unavailable"):
            continue
        if tier in ("rejected", "unavailable"):
            continue

        symbol = _candidate_symbol(item)
        if not symbol or symbol in seen:
            continue

        seen.add(symbol)
        symbols.append(symbol)

    return symbols


def build_candidate_filter_cycle_summary(candidate_payload: dict) -> dict:
    """
    Build a compact scheduler summary that makes Candidate Filter routing clear.
    The full candidate filter payload is still stored separately.
    """
    candidates = candidate_payload.get("candidates", []) or []
    rejected = candidate_payload.get("rejected", []) or []
    unavailable = candidate_payload.get("unavailable", []) or []

    candidate_symbols = extract_candidate_symbols(candidate_payload)
    rejected_symbols = sorted([
        symbol for symbol in (_candidate_symbol(item) for item in rejected)
        if symbol
    ])
    unavailable_symbols = sorted([
        symbol for symbol in (_candidate_symbol(item) for item in unavailable)
        if symbol
    ])

    return {
        "ok": bool(candidate_payload.get("ok", False)),
        "schema_version": candidate_payload.get("schema_version"),
        "runtime_version": candidate_payload.get("runtime_version"),
        "candidate_filter_mode": candidate_payload.get("candidate_filter_mode"),
        "input_symbols_count": candidate_payload.get("input_symbols_count"),
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "unavailable_count": len(unavailable),
        "candidate_symbols_for_strategy_engine": candidate_symbols,
        "rejected_symbols_skipped": rejected_symbols,
        "unavailable_symbols_skipped": unavailable_symbols,
        "routing_policy": (
            "Only Candidate Filter `candidates` are sent to Strategy Engine. "
            "`rejected` and `unavailable` are logged and skipped."
        ),
    }
