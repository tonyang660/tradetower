from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from threading import Thread
import json
import os
import time
import traceback

import requests


SERVICE_NAME = "scheduler"
PORT = int(os.getenv("PORT", "8080"))

API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
CANDIDATE_FILTER_BASE_URL = os.getenv("CANDIDATE_FILTER_BASE_URL", "http://candidate-filter:8080")
STRATEGY_ENGINE_BASE_URL = os.getenv("STRATEGY_ENGINE_BASE_URL", "http://strategy-engine:8080")
RISK_ENGINE_BASE_URL = os.getenv("RISK_ENGINE_BASE_URL", "http://risk-engine:8080")
PAPER_EXECUTION_BASE_URL = os.getenv("PAPER_EXECUTION_BASE_URL", "http://paper-execution:8080")
EVALUATOR_BASE_URL = os.getenv("EVALUATOR_BASE_URL", "http://evaluator:8080")

PAPER_EXECUTION_ENTRY_PATH = os.getenv("PAPER_EXECUTION_ENTRY_PATH", "/entry/simulate")

AUTO_LOOP_DEFAULT = os.getenv("AUTO_LOOP_ENABLED", "false").lower() == "true"
AUTO_LOOP_ENABLED_STATE = AUTO_LOOP_DEFAULT

LOOP_INTERVAL_SECONDS = int(os.getenv("LOOP_INTERVAL_SECONDS", "300"))
ACCOUNT_ID = int(os.getenv("ACCOUNT_ID", "1"))
SYMBOL_UNIVERSE_PATH = os.getenv("SYMBOL_UNIVERSE_PATH", "/app/config/symbol_universe.json")

TIMEFRAMES = ["5m", "15m", "1h", "4h"]
REFRESH_LIMIT = 72

MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST = os.getenv("MARK_TO_MARKET_BEFORE_EVALUATOR_INGEST", "true").lower() == "true"

PENDING_ENTRY_LOOP_INTERVAL_SECONDS = int(os.getenv("PENDING_ENTRY_LOOP_INTERVAL_SECONDS", "60"))
ENTRY_RETRY_MAX_ATTEMPTS = int(os.getenv("ENTRY_RETRY_MAX_ATTEMPTS", "15"))
PENDING_ENTRY_ORDERS = {}
LAST_PENDING_ENTRY_LOOP_RESULT = {
    "timestamp": None,
    "processed": 0,
    "fills": 0,
    "pending": 0,
    "cancelled": 0,
    "blocked": 0,
    "errors": 0,
    "results": [],
}

MAINTENANCE_LOOP_INTERVAL_SECONDS = int(os.getenv("MAINTENANCE_LOOP_INTERVAL_SECONDS", "60"))

LAST_MAINTENANCE_LOOP_RESULT = {
    "timestamp": None,
    "checked": 0,
    "actions_triggered": 0,
    "no_action": 0,
    "blocked": 0,
    "errors": 0,
    "results": [],
}

EXIT_RETRY_MAX_ATTEMPTS = int(os.getenv("EXIT_RETRY_MAX_ATTEMPTS", "5"))
PENDING_EXIT_LOOP_INTERVAL_SECONDS = int(os.getenv("PENDING_EXIT_LOOP_INTERVAL_SECONDS", "60"))
PENDING_EXIT_ORDERS = {}

LAST_PENDING_EXIT_LOOP_RESULT = {
    "timestamp": None,
    "processed": 0,
    "filled": 0,
    "pending": 0,
    "forced_market": 0,
    "errors": 0,
    "results": [],
}

def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def run_mark_to_market_refresh(account_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/mark-to-market/refresh",
            json={"account_id": account_id},
            timeout=15
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_mark_to_market_failed: {str(e)}"

    return payload, None

def ingest_pending_loop_event_to_evaluator(payload: dict):
    try:
        r = requests.post(
            f"{EVALUATOR_BASE_URL}/ingest/pending-entry-event",
            json=payload,
            timeout=15,
        )
        return r.json(), None
    except Exception as e:
        return None, f"evaluator_pending_entry_ingest_failed: {str(e)}"

def fetch_latest_price(symbol: str):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}/providers/bitget/ticker",
            params={"symbol": symbol},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"api_gateway_latest_price_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "latest_price_fetch_failed")

    price = payload.get("mark_price")
    if price is None:
        price = payload.get("last_price")

    if price is None:
        return None, "latest_price_missing"

    return float(price), None

def fetch_trade_guardian_status(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/status",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_status_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_status_failed")

    return payload, None

def load_symbol_universe():
    with open(SYMBOL_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    symbols = []
    for item in payload.get("symbols", []):
        if item.get("enabled", False):
            symbols.append(item["symbol"].upper())

    return symbols


def fetch_candles_from_api_gateway(symbol: str, timeframe: str, limit: int = REFRESH_LIMIT):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}/providers/bitget/candles",
            params={"symbol": symbol, "timeframe": timeframe, "limit": limit},
            timeout=20
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"api_gateway_request_failed: {str(e)}"}


def ingest_candles_to_data_hub(payload: dict):
    try:
        r = requests.post(
            f"{DATA_HUB_BASE_URL}/candles/ingest",
            json=payload,
            timeout=20
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"data_hub_ingest_failed: {str(e)}"}


def refresh_symbol_candles(symbol: str):
    results = []

    for timeframe in TIMEFRAMES:
        api_payload = fetch_candles_from_api_gateway(symbol, timeframe, REFRESH_LIMIT)
        if not api_payload.get("ok"):
            results.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "ok": False,
                "stage": "api_gateway",
                "error": api_payload.get("error", "unknown_error")
            })
            continue

        ingest_result = ingest_candles_to_data_hub(api_payload)
        if not ingest_result.get("ok"):
            results.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "ok": False,
                "stage": "data_hub",
                "error": ingest_result.get("error", "unknown_error")
            })
            continue

        results.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "ok": True,
            "stored_rows": ingest_result.get("stored_rows")
        })

    return results


def fetch_open_positions(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/positions/open",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_positions_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_positions_failed")

    return payload.get("positions", []), None

def process_pending_exits_once():
    results = []
    filled = 0
    pending = 0
    forced_market = 0
    errors_count = 0

    for symbol in list(PENDING_EXIT_ORDERS.keys()):
        state = PENDING_EXIT_ORDERS.get(symbol)
        if not state:
            continue

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

        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
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
            PENDING_EXIT_ORDERS.pop(symbol, None)
            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "POSITION_ALREADY_CLOSED",
            })
            continue

        trigger_seen_count = int(state.get("trigger_seen_count", 1))

        if trigger_seen_count < 2:
            PENDING_EXIT_ORDERS[symbol]["trigger_seen_count"] = trigger_seen_count + 1
            PENDING_EXIT_ORDERS[symbol]["updated_at"] = iso_now()
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
            ACCOUNT_ID,
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
            ACCOUNT_ID,
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
            PENDING_EXIT_ORDERS[symbol]["attempt_number"] = attempt_number + 1
            PENDING_EXIT_ORDERS[symbol]["updated_at"] = iso_now()
            PENDING_EXIT_ORDERS[symbol]["requested_price"] = float(new_limit_price)
            pending += 1
        else:
            PENDING_EXIT_ORDERS.pop(symbol, None)

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
        "timestamp": iso_now(),
        "processed": len(results),
        "filled": filled,
        "pending": pending,
        "forced_market": forced_market,
        "errors": errors_count,
        "results": results,
    }

    global LAST_PENDING_EXIT_LOOP_RESULT
    LAST_PENDING_EXIT_LOOP_RESULT = result
    return result

def check_maintenance(account_id: int, symbol: str):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/guard/check-maintenance",
            json={"account_id": account_id, "symbol": symbol},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_maintenance_check_failed: {str(e)}"

    return payload, None


def run_maintenance(account_id: int, symbol: str, force_market_stop_loss: bool = False):
    try:
        r = requests.post(
            f"{PAPER_EXECUTION_BASE_URL}/maintenance/check",
            json={
                "account_id": account_id,
                "symbol": symbol,
                "force_market_stop_loss": force_market_stop_loss,
            },
            timeout=20
        )
        payload = r.json()
    except Exception as e:
        return None, f"paper_execution_maintenance_failed: {str(e)}"

    return payload, None


def check_entry_gate(account_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/guard/check-entry",
            json={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_entry_check_failed: {str(e)}"

    return payload, None


def check_entry_gate_for_symbol(account_id: int, symbol: str, ignore_pending_order: bool = False):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/guard/check-entry",
            json={
                "account_id": account_id,
                "symbol": symbol,
                "ignore_pending_order": ignore_pending_order,
            },
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_symbol_entry_check_failed: {str(e)}"

    return payload, None


def run_candidate_filter(account_id: int, symbols: list[str]):
    if not symbols:
        return {
            "ok": True,
            "account_id": account_id,
            "generated_at": iso_now(),
            "max_candidates": 0,
            "min_score": 0,
            "candidates": [],
            "rejected": []
        }, None

    try:
        r = requests.get(
            f"{CANDIDATE_FILTER_BASE_URL}/candidates",
            params={"account_id": account_id, "symbols": ",".join(symbols)},
            timeout=30
        )
        payload = r.json()
    except Exception as e:
        return None, f"candidate_filter_request_failed: {str(e)}"

    return payload, None


def run_strategy_engine(symbol: str):
    try:
        r = requests.post(
            f"{STRATEGY_ENGINE_BASE_URL}/analyze",
            json={"symbol": symbol},
            timeout=30
        )
        payload = r.json()
    except Exception as e:
        return None, f"strategy_engine_request_failed: {str(e)}"

    return payload, None

def reprice_protective_order(account_id: int, order_id: int, new_price: float):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/reprice-protective",
            json={
                "account_id": account_id,
                "order_id": order_id,
                "new_price": new_price,
            },
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_reprice_protective_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "protective_reprice_failed")

    return payload, None

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

    return payload

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
            blocked += 1

            event_payload = {
                "account_id": ACCOUNT_ID,
                "cycle_id": originating_cycle_id,
                "symbol": symbol,
                "event_type": "ENTRY_BLOCKED",
                "attempt_number": attempt_number,
                "source": "pending_entry_loop",
                "details": {
                    "reason_codes": retry_gate.get("reason_codes", []),
                },
            }
            ingest_pending_loop_event_to_evaluator(event_payload)

            results.append({
                "symbol": symbol,
                "ok": True,
                "action": "BLOCKED",
                "reason_codes": retry_gate.get("reason_codes", []),
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
                "attempt_number": new_attempt_number
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

    global LAST_PENDING_ENTRY_LOOP_RESULT
    LAST_PENDING_ENTRY_LOOP_RESULT = result

    return result

def process_open_position_maintenance_once():
    results = []
    checked = 0
    actions_triggered = 0
    no_action = 0
    blocked = 0
    errors_count = 0

    open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
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

        global LAST_MAINTENANCE_LOOP_RESULT
        LAST_MAINTENANCE_LOOP_RESULT = result
        return result

    for pos in open_positions:
        symbol = pos["symbol"]
        checked += 1

        guard_result, guard_error = check_maintenance(ACCOUNT_ID, symbol)
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

        maintenance_result, maintenance_error = run_maintenance(ACCOUNT_ID, symbol)
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
                existing_state = PENDING_EXIT_ORDERS.get(symbol)

                if existing_state is None:
                    PENDING_EXIT_ORDERS[symbol] = {
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
                    PENDING_EXIT_ORDERS[symbol] = {
                        **existing_state,
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
        "checked": checked,
        "actions_triggered": actions_triggered,
        "no_action": no_action,
        "blocked": blocked,
        "errors": errors_count,
        "results": results,
    }

    LAST_MAINTENANCE_LOOP_RESULT = result

    return result

def run_risk_engine(risk_payload: dict):
    try:
        r = requests.post(
            f"{RISK_ENGINE_BASE_URL}/plan",
            json=risk_payload,
            timeout=30
        )
        payload = r.json()
    except Exception as e:
        return None, f"risk_engine_request_failed: {str(e)}"

    return payload, None


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


def submit_entry_to_paper_execution(payload: dict):
    try:
        r = requests.post(
            f"{PAPER_EXECUTION_BASE_URL}{PAPER_EXECUTION_ENTRY_PATH}",
            json=payload,
            timeout=30
        )
        result = r.json()
    except Exception as e:
        return None, f"paper_execution_entry_submit_failed: {str(e)}"

    return result, None


def get_pending_entry_symbols():
    return set(PENDING_ENTRY_ORDERS.keys())


def store_pending_entry(symbol: str, paper_payload: dict, paper_result: dict):
    current_attempt_number = int(
        paper_result.get("attempt_number", paper_payload.get("attempt_number", 1))
    )

    PENDING_ENTRY_ORDERS[symbol] = {
        "paper_payload": dict(paper_payload),
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


def ingest_cycle_summary_to_evaluator(summary: dict):
    try:
        r = requests.post(
            f"{EVALUATOR_BASE_URL}/ingest/cycle-summary",
            json=summary,
            timeout=20
        )
        return r.json(), None
    except Exception as e:
        return None, f"evaluator_cycle_ingest_failed: {str(e)}"


def ingest_equity_snapshot_to_evaluator(status_payload: dict):
    payload = {
        "account_id": status_payload["account_id"],
        "recorded_at": iso_now(),
        "cash_balance": status_payload["cash_balance"],
        "equity": status_payload["equity"],
        "realized_pnl": status_payload["realized_pnl"],
        "unrealized_pnl": status_payload["unrealized_pnl"],
        "fees_paid_total": status_payload.get("fees_paid_total", 0.0),
        "trading_enabled": status_payload["trading_enabled"],
        "manual_halt": status_payload["manual_halt"],
        "daily_kill_switch": status_payload["daily_kill_switch"],
        "weekly_kill_switch": status_payload["weekly_kill_switch"],
    }

    try:
        r = requests.post(
            f"{EVALUATOR_BASE_URL}/ingest/equity-snapshot",
            json=payload,
            timeout=20
        )
        return r.json(), None
    except Exception as e:
        return None, f"evaluator_equity_ingest_failed: {str(e)}"


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
            "results": []
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
            "results": []
        },
        "risk_engine": {
            "checked": 0,
            "approved": 0,
            "results": []
        },
        "final_entry_gate": {
            "checked": 0,
            "blocked": 0,
            "results": []
        },
        "paper_execution": {
            "submitted": 0,
            "fills": 0,
            "pending_retries": 0,
            "results": []
        },

        "errors": []
    }

    try:
        # Phase 0: load enabled symbol universe
        enabled_symbols = load_symbol_universe()
        summary["enabled_symbols"] = enabled_symbols

        summary["pending_entries_before_cycle"] = len(PENDING_ENTRY_ORDERS)

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
                "reason_codes": ["ENTRY_GATE_UNAVAILABLE"]
            }
        else:
            summary["entry_gate"] = entry_gate

        # Phase 4: build entry-eligible universe from latest state
        pending_symbols = get_pending_entry_symbols()

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
                    "error": candidate_error
                }
            else:
                summary["candidate_filter"] = candidate_payload
        else:
            summary["candidate_filter"] = {
                "ok": True,
                "skipped": True,
                "reason": "ENTRY_GATE_BLOCKED"
            }
            candidate_symbols = []

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
                    "error": strategy_error
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
                    "error": risk_error
                })
                continue

            summary["risk_engine"]["results"].append({
                "symbol": symbol,
                **risk_result
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
                    "error": final_gate_error
                })
                continue

            summary["final_entry_gate"]["results"].append({
                "symbol": symbol,
                **final_gate
            })

            if not final_gate.get("trade_allowed", False):
                summary["final_entry_gate"]["blocked"] += 1
                continue

            # Phase 9: submit approved plan to paper-execution
            paper_payload = build_paper_execution_payload(ACCOUNT_ID, strategy_result, risk_result)
            paper_result, paper_error = submit_entry_to_paper_execution(paper_payload)
            if paper_error:
                summary["paper_execution"]["results"].append({
                    "symbol": symbol,
                    "decision": strategy_result.get("decision"),
                    "selected_strategy": strategy_result.get("selected_strategy"),
                    "ok": False,
                    "error": paper_error
                })
                continue

            summary["paper_execution"]["submitted"] += 1

            action = str(paper_result.get("action", "")).upper()

            if action == "ENTRY_PENDING":
                store_pending_entry(symbol, {
                    **paper_payload,
                    "attempt_number": 1,
                    "max_attempts": ENTRY_RETRY_MAX_ATTEMPTS,
                    "originating_cycle_id": cycle_id,
                }, paper_result)
            else:
                clear_pending_entry(symbol)

            if action == "ENTRY_FILLED":
                summary["paper_execution"]["fills"] += 1

            summary["paper_execution"]["results"].append({
                "symbol": symbol,
                "retry": False,
                **paper_result
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

    summary["pending_entries_after_cycle"] = len(PENDING_ENTRY_ORDERS)

    return summary

def pending_entry_loop():
    while True:
        try:
            if AUTO_LOOP_ENABLED_STATE and len(PENDING_ENTRY_ORDERS) > 0:
                result = process_pending_entries_once()
                print(json.dumps({
                    "event": "PENDING_ENTRY_LOOP_COMPLETED",
                    "processed": result["processed"],
                    "timestamp": result["timestamp"],
                }))
        except Exception as e:
            print(json.dumps({
                "event": "PENDING_ENTRY_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(PENDING_ENTRY_LOOP_INTERVAL_SECONDS)

def pending_exit_loop():
    while True:
        try:
            if AUTO_LOOP_ENABLED_STATE and len(PENDING_EXIT_ORDERS) > 0:
                result = process_pending_exits_once()
                print(json.dumps({
                    "event": "PENDING_EXIT_LOOP_COMPLETED",
                    "processed": result["processed"],
                    "filled": result["filled"],
                    "timestamp": result["timestamp"],
                }))
        except Exception as e:
            print(json.dumps({
                "event": "PENDING_EXIT_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(PENDING_EXIT_LOOP_INTERVAL_SECONDS)

def open_position_maintenance_loop():
    while True:
        try:
            if AUTO_LOOP_ENABLED_STATE:
                result = process_open_position_maintenance_once()
                print(json.dumps({
                    "event": "MAINTENANCE_LOOP_COMPLETED",
                    "checked": result.get("checked", 0),
                    "actions_triggered": result.get("actions_triggered", 0),
                    "timestamp": result.get("timestamp"),
                }))
        except Exception as e:
            print(json.dumps({
                "event": "MAINTENANCE_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(MAINTENANCE_LOOP_INTERVAL_SECONDS)

def scheduler_loop():
    while True:
        global AUTO_LOOP_ENABLED_STATE

        if AUTO_LOOP_ENABLED_STATE:
            try:
                result = run_one_cycle()
                print(json.dumps({
                    "event": "CYCLE_COMPLETED",
                    "cycle_id": result["cycle_id"],
                    "ok": result["ok"],
                    "completed_at": result["completed_at"]
                }))
            except Exception as e:
                print(json.dumps({
                    "event": "CYCLE_FAILED",
                    "error": str(e)
                }))
        time.sleep(LOOP_INTERVAL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            pending_status = build_pending_entry_status()

            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
                "auto_loop_enabled": AUTO_LOOP_ENABLED_STATE,
                "auto_loop_default": AUTO_LOOP_DEFAULT,
                "loop_interval_seconds": LOOP_INTERVAL_SECONDS,
                "paper_execution_entry_path": PAPER_EXECUTION_ENTRY_PATH,
                "pending_entry_loop_interval_seconds": pending_status["pending_entry_loop_interval_seconds"],
                "pending_entry_max_attempts": pending_status["pending_entry_max_attempts"],
                "pending_entries_count": pending_status["pending_entries_count"],
                "pending_entries": pending_status["pending_entries"],
                "last_pending_entry_loop_at": LAST_PENDING_ENTRY_LOOP_RESULT.get("timestamp"),
                "last_pending_entry_loop_processed": LAST_PENDING_ENTRY_LOOP_RESULT.get("processed", 0),
                "last_pending_entry_loop_fills": LAST_PENDING_ENTRY_LOOP_RESULT.get("fills", 0),
                "last_pending_entry_loop_pending": LAST_PENDING_ENTRY_LOOP_RESULT.get("pending", 0),
                "last_pending_entry_loop_cancelled": LAST_PENDING_ENTRY_LOOP_RESULT.get("cancelled", 0),
                "last_pending_entry_loop_blocked": LAST_PENDING_ENTRY_LOOP_RESULT.get("blocked", 0),
                "last_pending_entry_loop_errors": LAST_PENDING_ENTRY_LOOP_RESULT.get("errors", 0),
                "last_pending_entry_loop_results": LAST_PENDING_ENTRY_LOOP_RESULT.get("results", []),
                "maintenance_loop_interval_seconds": MAINTENANCE_LOOP_INTERVAL_SECONDS,
                "last_maintenance_loop_at": LAST_MAINTENANCE_LOOP_RESULT.get("timestamp"),
                "last_maintenance_loop_checked": LAST_MAINTENANCE_LOOP_RESULT.get("checked", 0),
                "last_maintenance_loop_actions_triggered": LAST_MAINTENANCE_LOOP_RESULT.get("actions_triggered", 0),
                "last_maintenance_loop_no_action": LAST_MAINTENANCE_LOOP_RESULT.get("no_action", 0),
                "last_maintenance_loop_blocked": LAST_MAINTENANCE_LOOP_RESULT.get("blocked", 0),
                "last_maintenance_loop_errors": LAST_MAINTENANCE_LOOP_RESULT.get("errors", 0),
                "last_maintenance_loop_results": LAST_MAINTENANCE_LOOP_RESULT.get("results", []),
                "pending_exit_loop_interval_seconds": PENDING_EXIT_LOOP_INTERVAL_SECONDS,
                "pending_exit_orders_count": len(PENDING_EXIT_ORDERS),
                "last_pending_exit_loop_at": LAST_PENDING_EXIT_LOOP_RESULT.get("timestamp"),
                "last_pending_exit_loop_processed": LAST_PENDING_EXIT_LOOP_RESULT.get("processed", 0),
                "last_pending_exit_loop_filled": LAST_PENDING_EXIT_LOOP_RESULT.get("filled", 0),
                "last_pending_exit_loop_pending": LAST_PENDING_EXIT_LOOP_RESULT.get("pending", 0),
                "last_pending_exit_loop_forced_market": LAST_PENDING_EXIT_LOOP_RESULT.get("forced_market", 0),
                "last_pending_exit_loop_errors": LAST_PENDING_EXIT_LOOP_RESULT.get("errors", 0),
                "last_pending_exit_loop_results": LAST_PENDING_EXIT_LOOP_RESULT.get("results", []),
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/controls/auto-loop":
            global AUTO_LOOP_ENABLED_STATE

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "invalid_json",
                    "details": str(e)
                }, status=400)
                return

            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                self._send_json({
                    "ok": False,
                    "error": "invalid_enabled_flag",
                    "required": {"enabled": "boolean"}
                }, status=400)
                return

            AUTO_LOOP_ENABLED_STATE = enabled

            self._send_json({
                "ok": True,
                "auto_loop_enabled": AUTO_LOOP_ENABLED_STATE,
                "timestamp": iso_now()
            })
            return

        if self.path == "/cycle/run-once":
            try:
                result = run_one_cycle()
                self._send_json(result, status=200 if result.get("ok") else 500)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    loop_thread = Thread(target=scheduler_loop, daemon=True)
    loop_thread.start()

    pending_thread = Thread(target=pending_entry_loop, daemon=True)
    pending_thread.start()

    pending_exit_thread = Thread(target=pending_exit_loop, daemon=True)
    pending_exit_thread.start()

    maintenance_thread = Thread(target=open_position_maintenance_loop, daemon=True)
    maintenance_thread.start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()