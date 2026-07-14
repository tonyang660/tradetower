from config import ENTRY_RETRY_MAX_ATTEMPTS, PENDING_ENTRY_LOOP_INTERVAL_SECONDS


RISK_APPROVAL_PAYLOAD_VERSION_V2 = "phase5_step10_risk_approval_payload_v2"
SCHEDULER_RISK_COMPATIBILITY_VERSION = "phase5_step11_scheduler_paper_compatibility"


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
            "risk_approval_payload_version": context.get("risk_approval_payload_version"),
            "risk_decision": context.get("risk_decision"),
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


def extract_btc_macro_context(strategy_result: dict) -> dict:
    for key in ("btc_macro_policy", "btc_macro_context"):
        value = strategy_result.get(key)
        if isinstance(value, dict):
            return value

    market_context = strategy_result.get("market_context") or {}
    if isinstance(market_context, dict):
        value = market_context.get("btc_macro_policy") or market_context.get("btc_macro_context")
        if isinstance(value, dict):
            return value

    mtf_context = strategy_result.get("mtf_context") or {}
    if isinstance(mtf_context, dict):
        value = mtf_context.get("btc_macro_policy") or mtf_context.get("btc_macro_context")
        if isinstance(value, dict):
            return value

    proposed_trade = strategy_result.get("proposed_trade") or {}
    if isinstance(proposed_trade, dict):
        for key in ("btc_macro_policy", "btc_macro_context"):
            value = proposed_trade.get(key)
            if isinstance(value, dict):
                return value

    flat = {}
    for key in ("position_size_mult", "btc_position_mult", "score_threshold_adj", "max_signals_adj"):
        if strategy_result.get(key) is not None:
            flat[key] = strategy_result[key]
    return flat


def build_risk_payload_from_strategy(account_id: int, strategy_result: dict):
    position_side = normalize_position_side(strategy_result)
    btc_macro_context = extract_btc_macro_context(strategy_result)

    payload = {
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
            "regime": strategy_result.get("regime"),
            "score": strategy_result.get("score") or strategy_result.get("confidence"),
            "confidence": strategy_result.get("confidence") or strategy_result.get("score"),
            "reason_tags": strategy_result.get("reason_tags", []),
        },
    }

    if btc_macro_context:
        payload["btc_macro_context"] = btc_macro_context
        payload["strategy_signal"]["btc_macro_context"] = btc_macro_context

    return payload


def is_risk_approved(risk_result: dict) -> bool:
    if not isinstance(risk_result, dict):
        return False
    if not risk_result.get("ok"):
        return False
    if risk_result.get("approved") is True:
        return True
    return str(risk_result.get("risk_decision") or "").lower() == "approved"


def normalize_risk_order_type(risk_result: dict, fallback: str | None = None) -> str | None:
    value = risk_result.get("entry_order_type") or risk_result.get("order_type") or fallback
    if value:
        return str(value).lower()
    return None


def required_risk_payload_fields_missing(risk_result: dict) -> list[str]:
    required = [
        "symbol",
        "position_side",
        "entry_price",
        "stop_loss",
        "risk_amount",
        "size",
        "notional",
        "leverage",
        "margin_required",
        "take_profits",
    ]
    return [
        field
        for field in required
        if risk_result.get(field) is None
    ]


def summarize_risk_result_for_cycle(risk_result: dict) -> dict:
    return {
        "symbol": risk_result.get("symbol"),
        "ok": bool(risk_result.get("ok")),
        "approved": bool(risk_result.get("approved")),
        "risk_decision": risk_result.get("risk_decision"),
        "risk_approval_payload_version": risk_result.get("risk_approval_payload_version"),
        "runtime_version": risk_result.get("runtime_version"),
        "reason_codes": risk_result.get("reason_codes", []),
        "risk_amount": risk_result.get("risk_amount"),
        "base_risk_amount": risk_result.get("base_risk_amount"),
        "risk_amount_multiplier": risk_result.get("risk_amount_multiplier"),
        "size": risk_result.get("size"),
        "notional": risk_result.get("notional"),
        "leverage": risk_result.get("leverage"),
    }


def build_repriced_risk_payload(account_id: int, pending_payload: dict, new_entry_price: float):
    payload = {
        "account_id": account_id,
        "symbol": pending_payload["symbol"],
        "position_side": pending_payload["position_side"],
        "entry_order_type": "limit",
        "entry_price": new_entry_price,
        "stop_loss": float(pending_payload["stop_loss"]),
        "take_profits": pending_payload.get("take_profits", {}),
    }

    btc_macro_context = pending_payload.get("btc_macro_context")
    if isinstance(btc_macro_context, dict):
        payload["btc_macro_context"] = btc_macro_context

    strategy_signal = pending_payload.get("strategy_signal")
    if isinstance(strategy_signal, dict):
        payload["strategy_signal"] = strategy_signal

    return payload


def build_repriced_paper_payload(account_id: int, pending_payload: dict, risk_result: dict, new_entry_price: float):
    payload = {
        "account_id": account_id,
        "symbol": risk_result.get("symbol") or pending_payload["symbol"],
        "selected_strategy": pending_payload.get("selected_strategy"),
        "regime": pending_payload.get("regime"),
        "strategy_confidence": pending_payload.get("strategy_confidence"),
        "strategy_reason_tags": pending_payload.get("strategy_reason_tags", []),
        "position_side": risk_result.get("position_side") or pending_payload["position_side"],
        "order_type": normalize_risk_order_type(risk_result, "limit"),
        "entry_price": new_entry_price,
        "stop_loss": risk_result.get("stop_loss", float(pending_payload["stop_loss"])),
        "take_profits": risk_result.get("take_profits") or pending_payload.get("take_profits", {}),
        "scheduler_risk_compatibility_version": SCHEDULER_RISK_COMPATIBILITY_VERSION,
    }

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    payload["order_type"] = normalize_risk_order_type(payload, "limit")
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
    """
    Build the entry payload from the finalized Risk Approval v2 result.

    Strategy fields are retained as context, but execution-critical fields come
    from Risk Engine after sizing, leverage, portfolio, correlation, drawdown,
    and BTC macro checks.
    """
    position_side = risk_result.get("position_side") or normalize_position_side(strategy_result)
    order_type = normalize_risk_order_type(
        risk_result,
        extract_entry_order_type(strategy_result),
    )

    payload = {
        "account_id": account_id,
        "symbol": risk_result.get("symbol") or strategy_result["symbol"],
        "selected_strategy": strategy_result.get("selected_strategy"),
        "regime": strategy_result.get("regime"),
        "strategy_confidence": strategy_result.get("confidence") or strategy_result.get("score"),
        "strategy_reason_tags": strategy_result.get("reason_tags", []),
        "position_side": position_side,
        "order_type": order_type,
        "entry_price": risk_result.get("entry_price", extract_entry_price(strategy_result)),
        "stop_loss": risk_result.get("stop_loss", extract_stop_loss(strategy_result)),
        "take_profits": risk_result.get("take_profits") or extract_take_profits(strategy_result),
        "attempt_number": int(attempt_number),
        "max_attempts": int(max_attempts),
        "v2_decision": strategy_result.get("v2_decision"),
        "legacy_decision": strategy_result.get("legacy_decision"),
        "scheduler_risk_compatibility_version": SCHEDULER_RISK_COMPATIBILITY_VERSION,
    }

    if cycle_id is not None:
        payload["cycle_id"] = cycle_id
        payload["originating_cycle_id"] = cycle_id

    if isinstance(risk_result, dict):
        payload.update(risk_result)

    payload["order_type"] = normalize_risk_order_type(payload, order_type)
    payload["position_side"] = payload.get("position_side") or position_side
    payload["entry_price"] = payload.get("entry_price")
    payload["stop_loss"] = payload.get("stop_loss")
    payload["take_profits"] = payload.get("take_profits") or {}

    return payload


def _candidate_status(item: dict) -> str:
    return str(item.get("candidate_status") or "").lower()


def _candidate_symbol(item: dict) -> str | None:
    symbol = item.get("symbol")
    if not symbol:
        return None
    return str(symbol).upper()


def extract_candidate_symbols(candidate_payload: dict):
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
    candidates = candidate_payload.get("candidates", []) or []
    rejected = candidate_payload.get("rejected", []) or []
    unavailable = candidate_payload.get("unavailable", []) or []

    return {
        "schema_version": candidate_payload.get("schema_version"),
        "candidate_filter_mode": candidate_payload.get("candidate_filter_mode"),
        "input_symbols_count": candidate_payload.get("input_symbols_count"),
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "unavailable_count": len(unavailable),
        "candidate_symbols": extract_candidate_symbols(candidate_payload),
    }
