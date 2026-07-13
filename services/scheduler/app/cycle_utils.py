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


def normalize_position_side(payload: dict) -> str | None:
    """
    Phase 4 Step 12 compatibility helper.

    Strategy Signal v2 emits:
        decision      = legacy decision for current Scheduler: trade/observe/no_trade
        v2_decision   = trade_candidate/observe/no_trade
        decision_side = long/short/neutral
        position_side = long/short for trade candidates

    Scheduler/Risk/Paper must use position_side, not decision.
    """
    for key in ("position_side", "decision_side", "side"):
        value = payload.get(key)
        if value is None:
            continue
        value = str(value).lower()
        if value in ("long", "short"):
            return value
    return None


def extract_take_profits(strategy_result: dict) -> dict:
    if isinstance(strategy_result.get("take_profits"), dict):
        return strategy_result["take_profits"]

    proposed_trade = strategy_result.get("proposed_trade") or {}
    if isinstance(proposed_trade.get("take_profits"), dict):
        return proposed_trade["take_profits"]

    return {}


def extract_entry_order_type(strategy_result: dict) -> str | None:
    value = strategy_result.get("entry_order_type")
    if value:
        return str(value).lower()

    proposed_trade = strategy_result.get("proposed_trade") or {}
    value = proposed_trade.get("entry_order_type")
    if value:
        return str(value).lower()

    return None


def extract_entry_price(strategy_result: dict):
    if strategy_result.get("entry_price") is not None:
        return strategy_result.get("entry_price")

    proposed_trade = strategy_result.get("proposed_trade") or {}
    return proposed_trade.get("entry_price")


def extract_stop_loss(strategy_result: dict):
    if strategy_result.get("stop_loss") is not None:
        return strategy_result.get("stop_loss")

    proposed_trade = strategy_result.get("proposed_trade") or {}
    return proposed_trade.get("stop_loss")


def build_risk_payload_from_strategy(account_id: int, strategy_result: dict):
    position_side = normalize_position_side(strategy_result)
    return {
        "account_id": account_id,
        "symbol": strategy_result["symbol"],
        "position_side": position_side,
        "entry_order_type": extract_entry_order_type(strategy_result),
        "entry_price": extract_entry_price(strategy_result),
        "stop_loss": extract_stop_loss(strategy_result),
        "take_profits": extract_take_profits(strategy_result),
        "strategy_signal": {
            "schema_version": strategy_result.get("schema_version"),
            "v2_decision": strategy_result.get("v2_decision"),
            "legacy_decision": strategy_result.get("legacy_decision"),
            "selected_strategy": strategy_result.get("selected_strategy"),
            "score": strategy_result.get("score") or strategy_result.get("confidence"),
            "reason_tags": strategy_result.get("reason_tags", []),
        },
    }


def build_repriced_risk_payload(account_id: int, pending_payload: dict, new_entry_price: float):
    return {
        "account_id": account_id,
        "symbol": pending_payload["symbol"],
        "position_side": pending_payload["position_side"],
        "entry_order_type": "limit",
        "entry_price": new_entry_price,
        "stop_loss": float(pending_payload["stop_loss"]),
        "take_profits": pending_payload.get("take_profits", {}),
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
        "take_profits": pending_payload.get("take_profits", {}),
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
    position_side = normalize_position_side(strategy_result)
    payload = {
        "account_id": account_id,
        "symbol": strategy_result["symbol"],
        "selected_strategy": strategy_result.get("selected_strategy"),
        "regime": strategy_result.get("regime"),
        "strategy_confidence": strategy_result.get("confidence") or strategy_result.get("score"),
        "strategy_reason_tags": strategy_result.get("reason_tags", []),
        "position_side": position_side,
        "order_type": extract_entry_order_type(strategy_result),
        "entry_price": extract_entry_price(strategy_result),
        "stop_loss": extract_stop_loss(strategy_result),
        "take_profits": extract_take_profits(strategy_result),
        "attempt_number": int(attempt_number),
        "max_attempts": int(max_attempts),
        "v2_decision": strategy_result.get("v2_decision"),
        "legacy_decision": strategy_result.get("legacy_decision"),
    }

    if cycle_id is not None:
        payload["cycle_id"] = cycle_id
        payload["originating_cycle_id"] = cycle_id

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    if "entry_order_type" in payload and "order_type" not in payload:
        payload["order_type"] = payload["entry_order_type"]

    if "order_type" not in payload and payload.get("entry_order_type"):
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
