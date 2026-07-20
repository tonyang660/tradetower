from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone
import json
import os

import requests

from entry_fill_model import evaluate_entry_fill
from execution_pricing import (
    EXECUTION_PRICING_VERSION,
    build_entry_pricing_context,
    extract_reference_prices,
    pricing_contract,
)
from paper_execution_contract import (
    PAPER_EXECUTION_REPORT_VERSION,
    PAPER_EXECUTION_VERSION,
    build_entry_execution_report_v2,
    build_entry_filled_result,
    build_entry_pending_result,
)
from protective_order_policy import (
    PROTECTIVE_ORDER_POLICY_VERSION,
    build_protective_order_policy_contract,
    validate_protective_order_set,
)
from pending_entry_policy import (
    PENDING_ENTRY_POLICY_VERSION,
    build_pending_entry_policy_contract,
    evaluate_pending_limit_lifecycle,
)


SERVICE_NAME = "paper-execution"
PORT = int(os.getenv("PORT", "8080"))

DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
API_GATEWAY_LATEST_PRICE_PATH = os.getenv("API_GATEWAY_LATEST_PRICE_PATH", "/market/ticker")

LIMIT_FEE_PCT = float(os.getenv("LIMIT_FEE_PCT", "0.02"))
MARKET_FEE_PCT = float(os.getenv("MARKET_FEE_PCT", "0.06"))
MARKET_SLIPPAGE_PCT = float(os.getenv("MARKET_SLIPPAGE_PCT", "0.06"))

RUNTIME_VERSION = "phase6_step5_protective_order_lifecycle"


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def calc_fee(notional: float, fee_pct: float) -> float:
    return notional * (fee_pct / 100.0)


def apply_market_slippage(price: float, position_side: str, execution_type: str) -> float:
    slip = MARKET_SLIPPAGE_PCT / 100.0

    if execution_type == "ENTRY":
        if position_side == "long":
            return price * (1 + slip)
        if position_side == "short":
            return price * (1 - slip)

    if position_side == "long":
        return price * (1 - slip)
    if position_side == "short":
        return price * (1 + slip)

    return price


def can_fill_stop_limit_now(candles: list[dict], stop_price: float) -> bool:
    return recent_candles_touch_limit(candles, stop_price)


def apply_exit_fill_price(trigger_price: float, position_side: str, execution_type: str) -> float:
    if execution_type.startswith("TP") or execution_type == "STOP_LOSS":
        return trigger_price
    return apply_market_slippage(trigger_price, position_side, execution_type)


def fetch_recent_candles(symbol: str, timeframe: str = "5m", limit: int = 3):
    try:
        r = requests.get(
            f"{DATA_HUB_BASE_URL}/candles",
            params={"symbol": symbol, "timeframe": timeframe, "limit": limit},
            timeout=10
        )
        payload = r.json()
    except Exception:
        return None, "data_hub_request_failed"

    if not payload.get("ok"):
        return None, payload.get("error", "data_hub_error")

    candles = payload.get("candles", [])
    if not candles:
        return None, "no_recent_candles"

    return candles, None


def fetch_latest_ticker(symbol: str):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}{API_GATEWAY_LATEST_PRICE_PATH}",
            params={"symbol": symbol},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"latest_ticker_request_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "latest_ticker_fetch_failed")

    return payload, None


def fetch_latest_price(symbol: str):
    ticker, error = fetch_latest_ticker(symbol)
    if error:
        return None, error

    price = ticker.get("mark_price")
    if price is None:
        price = ticker.get("last_price")

    if price is None:
        return None, "latest_price_missing_in_response"

    return float(price), None


def get_order_trigger_price(order: dict):
    if order is None:
        return None

    value = order.get("entry_price")
    if value is None:
        value = order.get("requested_price")

    if value is None:
        return None

    return float(value)


def get_order_requested_price(order: dict):
    if order is None:
        return None

    value = order.get("requested_price")
    if value is None:
        value = order.get("entry_price")

    if value is None:
        return None

    return float(value)


def get_stop_trigger_price(order: dict):
    if order is None:
        return None

    value = order.get("stop_loss")
    if value is None:
        value = order.get("requested_price")
    if value is None:
        value = order.get("entry_price")

    if value is None:
        return None

    return float(value)


def get_tp_close_percent(payload: dict, key: str, default: float) -> float:
    direct_key = f"{key}_close_percent"

    try:
        if payload.get(direct_key) is not None:
            return float(payload[direct_key])

        take_profits = payload.get("take_profits") or {}
        item = take_profits.get(key) or {}
        if isinstance(item, dict) and item.get("close_percent") is not None:
            return float(item["close_percent"])
    except Exception:
        pass

    return float(default)


def fetch_open_position(account_id: int, symbol: str):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/position/open",
            params={"account_id": account_id, "symbol": symbol},
            timeout=10
        )
        payload = r.json()
    except Exception:
        return None, "trade_guardian_request_failed"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_error")

    return payload["position"], None


def fetch_open_orders(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/open",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception:
        return None, "trade_guardian_open_orders_failed"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_open_orders_failed")

    return payload.get("items", []), None


def get_symbol_protective_orders(account_id: int, symbol: str, linked_position_id: int):
    orders, error = fetch_open_orders(account_id)
    if error:
        return None, error

    filtered = [
        o for o in orders
        if o.get("symbol") == symbol
        and o.get("linked_position_id") == linked_position_id
        and o.get("role") in ("stop_loss", "sl2", "tp1", "tp2", "tp3")
    ]

    return filtered, None


def ensure_entry_order(payload: dict, order_type: str):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/entry/ensure",
            json={
                "account_id": int(payload["account_id"]),
                "symbol": str(payload["symbol"]).upper(),
                "position_side": str(payload["position_side"]).lower(),
                "order_type": order_type,
                "requested_price": float(payload["entry_price"]),
                "requested_size": float(payload["size"]),
                "order_id": payload.get("order_id"),
                "execution_context": payload,
                "retry_attempt": int(payload.get("attempt_number", 0)),
                "max_retry_attempts": int(payload.get("max_attempts", 15)),
                "originating_cycle_id": payload.get("originating_cycle_id"),
            },
            timeout=15,
        )
        result = r.json()
    except Exception as e:
        return None, f"entry_order_ensure_failed: {str(e)}"

    if r.status_code != 200 or not result.get("ok", False):
        return None, result.get("error", "entry_order_ensure_failed")

    return int(result["order_id"]), None


def mark_entry_order_open(order_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/mark-open",
            json={"order_id": order_id},
            timeout=10,
        )
        result = r.json()
    except Exception as e:
        return False, f"order_mark_open_failed: {str(e)}"

    if r.status_code != 200 or not result.get("ok", False):
        return False, result.get("error", "order_mark_open_failed")

    return True, None


def send_execution_to_guardian(execution_event: dict):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/execution/apply",
            json=execution_event,
            timeout=15
        )
    except Exception as e:
        return None, f"trade_guardian_execution_apply_failed: {str(e)}"

    try:
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_invalid_json_response: {str(e)}"

    if r.status_code != 200:
        return None, f"trade_guardian_http_{r.status_code}: {payload}"

    if not payload.get("ok", False):
        return None, f"trade_guardian_apply_rejected: {payload}"

    return payload, None


def candle_touches_limit(candle: dict, price: float) -> bool:
    return float(candle["low"]) <= price <= float(candle["high"])


def recent_candles_touch_limit(candles: list[dict], price: float) -> bool:
    for candle in candles:
        if candle_touches_limit(candle, price):
            return True
    return False


def _stop_trigger_candidate(side: str, current_price: float, order: dict | None, remaining_size: float):
    if order is None:
        return None
    price = get_stop_trigger_price(order)
    if price is None:
        return None
    if side == "long":
        hit = current_price <= price
    elif side == "short":
        hit = current_price >= price
    else:
        hit = False
    if not hit:
        return None
    order_remaining = float(order.get("remaining_size") or order.get("requested_size") or remaining_size or 0.0)
    return "STOP_LOSS", price, min(order_remaining, float(remaining_size)), order


def evaluate_live_price_trigger(side: str, current_price: float, orders_by_role: dict, remaining_size: float):
    sl_order = orders_by_role.get("stop_loss")
    sl2_order = orders_by_role.get("sl2")
    tp1_order = orders_by_role.get("tp1")
    tp2_order = orders_by_role.get("tp2")
    tp3_order = orders_by_role.get("tp3")

    for stop_order in (sl_order, sl2_order):
        candidate = _stop_trigger_candidate(side, current_price, stop_order, remaining_size)
        if candidate is not None:
            return candidate

    tp1_price = get_order_trigger_price(tp1_order)
    tp2_price = get_order_trigger_price(tp2_order)
    tp3_price = get_order_trigger_price(tp3_order)

    if side == "long":
        if tp1_price is not None and current_price >= tp1_price:
            return "TP1", tp1_price, float(tp1_order["requested_size"] or 0.0), tp1_order
        if tp2_price is not None and current_price >= tp2_price:
            return "TP2", tp2_price, float(tp2_order["requested_size"] or 0.0), tp2_order
        if tp3_price is not None and current_price >= tp3_price:
            return "TP3", tp3_price, float(remaining_size), tp3_order

    elif side == "short":
        if tp1_price is not None and current_price <= tp1_price:
            return "TP1", tp1_price, float(tp1_order["requested_size"] or 0.0), tp1_order
        if tp2_price is not None and current_price <= tp2_price:
            return "TP2", tp2_price, float(tp2_order["requested_size"] or 0.0), tp2_order
        if tp3_price is not None and current_price <= tp3_price:
            return "TP3", tp3_price, float(remaining_size), tp3_order

    return None

def build_entry_execution_from_fill(
    *,
    payload: dict,
    order_id: int,
    order_type: str,
    fill_result: dict,
    fee_pct: float,
    notes: str,
    reference_prices: dict | None = None,
):
    pricing = build_entry_pricing_context(
        payload=payload,
        order_type=order_type,
        fill_price=float(fill_result["fill_price"]),
        size=float(payload["size"]),
        fee_pct=fee_pct,
        slippage_bps=float(fill_result.get("slippage_bps", 0.0)),
        fill_source=fill_result.get("fill_source", "unknown"),
        fill_reason=fill_result.get("fill_reason", "ENTRY_FILLED"),
        reference_prices=reference_prices,
    )

    execution_event = build_entry_execution_report_v2(
        payload=payload,
        order_id=order_id,
        order_type=order_type,
        fill_price=pricing["fill_price"],
        filled_size=pricing["filled_size"],
        fee_paid=pricing["fee_paid"],
        slippage_bps=pricing["slippage_bps"],
        fill_source=pricing["fill_source"],
        fill_reason=pricing["fill_reason"],
        notes=notes,
    )
    execution_event["notional"] = pricing["notional"]
    execution_event["fee_pct"] = pricing["fee_pct"]
    execution_event["pricing_context"] = pricing

    return execution_event


def execute_market_entry(
    account_id: int,
    symbol: str,
    position_side: str,
    entry_price: float,
    size: float,
    payload: dict,
    notes: str = "paper market entry fill",
    candles: list[dict] | None = None,
    latest_price: float | None = None,
    latest_ticker: dict | None = None,
):
    order_id, order_error = ensure_entry_order(payload, "market")
    if order_error:
        return {"ok": False, "error": order_error}

    payload["order_id"] = order_id

    reference_prices = extract_reference_prices(
        ticker_payload=latest_ticker,
        fallback_price=entry_price,
    )
    fill_result = evaluate_entry_fill(
        payload={**payload, "order_type": "market"},
        candles=candles or [],
        latest_price=reference_prices["reference_price"],
        market_slippage_pct=MARKET_SLIPPAGE_PCT,
    )
    if not fill_result.get("ok") or not fill_result.get("filled"):
        return {
            "ok": False,
            "error": "market_entry_fill_failed",
            "fill_result": fill_result,
        }

    execution_event = build_entry_execution_from_fill(
        payload=payload,
        order_id=order_id,
        order_type="market",
        fill_result=fill_result,
        fee_pct=MARKET_FEE_PCT,
        notes=notes,
        reference_prices=reference_prices,
    )

    guardian_result, g_error = send_execution_to_guardian(execution_event)
    if g_error:
        return {"ok": False, "error": g_error}

    return build_entry_filled_result(
        fill_method="market",
        execution_event=execution_event,
        guardian_result=guardian_result,
        order_id=order_id,
        fill_model_context=fill_result.get("context", {}),
    )


def simulate_entry(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    position_side = payload["position_side"].lower()

    order_type = str(payload.get("order_type") or payload.get("entry_order_type") or "").lower()
    if order_type not in ("limit", "market"):
        return {"ok": False, "error": "unsupported_order_type"}

    entry_price = float(payload["entry_price"])
    size = float(payload["size"])

    order_id, order_error = ensure_entry_order(payload, order_type)
    if order_error:
        return {"ok": False, "error": order_error}

    payload["order_id"] = order_id

    attempt_number = int(payload.get("attempt_number", 1))
    max_attempts = int(payload.get("max_attempts", 15))

    candles, error = fetch_recent_candles(symbol, "5m", limit=3)
    if error:
        return {"ok": False, "error": error}

    latest_ticker, latest_ticker_error = fetch_latest_ticker(symbol)
    if latest_ticker_error is not None:
        latest_ticker = None

    reference_prices = extract_reference_prices(
        ticker_payload=latest_ticker,
        fallback_price=entry_price,
    )

    fill_result = evaluate_entry_fill(
        payload=payload,
        candles=candles,
        latest_price=reference_prices["reference_price"],
        market_slippage_pct=MARKET_SLIPPAGE_PCT,
    )

    if not fill_result.get("ok"):
        return {
            "ok": False,
            "error": "entry_fill_model_rejected",
            "fill_result": fill_result,
        }

    if order_type == "limit":
        lifecycle = evaluate_pending_limit_lifecycle(
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            fill_result=fill_result,
        )

        if lifecycle["decision"] == "fill_now":
            execution_event = build_entry_execution_from_fill(
                payload=payload,
                order_id=order_id,
                order_type="limit",
                fill_result=fill_result,
                fee_pct=LIMIT_FEE_PCT,
                notes=payload.get("notes", "paper limit entry fill"),
                reference_prices=reference_prices,
            )

            guardian_result, g_error = send_execution_to_guardian(execution_event)
            if g_error:
                return {"ok": False, "error": g_error}

            return build_entry_filled_result(
                fill_method="limit",
                execution_event=execution_event,
                guardian_result=guardian_result,
                order_id=order_id,
                fill_model_context={
                    **fill_result.get("context", {}),
                    "pending_lifecycle": lifecycle,
                    "reference_prices": reference_prices,
                },
            )

        if lifecycle["decision"] == "keep_pending":
            marked_open, mark_open_error = mark_entry_order_open(order_id)
            if not marked_open:
                return {"ok": False, "error": mark_open_error}

            return build_entry_pending_result(
                order_id=order_id,
                attempt_number=attempt_number,
                next_attempt_number=lifecycle["next_attempt_number"],
                reason_codes=lifecycle["reason_codes"],
                fill_model_context={
                    **fill_result.get("context", {}),
                    "pending_lifecycle": lifecycle,
                    "reference_prices": reference_prices,
                },
            )

        if lifecycle["decision"] == "market_fallback":
            fallback_payload = {
                **payload,
                "order_type": "market",
                "entry_order_type": "market",
                "fallback_from_order_id": order_id,
                "fallback_reason_codes": lifecycle["reason_codes"],
            }
            return execute_market_entry(
                account_id=account_id,
                symbol=symbol,
                position_side=position_side,
                entry_price=entry_price,
                size=size,
                payload=fallback_payload,
                notes="paper market fallback after limit max attempts",
                candles=candles,
                latest_ticker=latest_ticker,
            )

    if order_type == "market":
        return execute_market_entry(
            account_id=account_id,
            symbol=symbol,
            position_side=position_side,
            entry_price=entry_price,
            size=size,
            payload=payload,
            notes=payload.get("notes", "paper market entry fill"),
            candles=candles,
            latest_ticker=latest_ticker,
        )

    return {"ok": False, "error": "unsupported_order_type"}


def simulate_maintenance(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    force_market_stop_loss = bool(payload.get("force_market_stop_loss", False))

    position, error = fetch_open_position(account_id, symbol)
    if error:
        return {"ok": False, "error": error}

    candles, c_error = fetch_recent_candles(symbol, "5m", limit=3)
    if c_error:
        return {"ok": False, "error": c_error}

    protective_orders, o_error = get_symbol_protective_orders(
        account_id,
        symbol,
        position["position_id"],
    )
    if o_error:
        return {"ok": False, "error": o_error}

    side = position["side"]
    execution_type = None
    trigger_price = None
    close_size = None
    trigger_order = None

    orders_by_role = {o["role"]: o for o in protective_orders}
    protective_validation = validate_protective_order_set(
        position=position,
        protective_orders=protective_orders,
    )
    if not protective_validation.get("ok"):
        return {
            "ok": False,
            "error": "protective_order_set_invalid",
            "reason_codes": protective_validation.get("reason_codes", []),
            "protective_order_validation": protective_validation,
        }

    latest_price, latest_price_error = fetch_latest_price(symbol)
    if latest_price_error is None:
        live_trigger = evaluate_live_price_trigger(
            side=side,
            current_price=latest_price,
            orders_by_role=orders_by_role,
            remaining_size=float(position["remaining_size"]),
        )
        if live_trigger is not None:
            execution_type, trigger_price, close_size, trigger_order = live_trigger

    if execution_type is None:
        for candle in candles:
            high = float(candle["high"])
            low = float(candle["low"])

            sl_order = orders_by_role.get("stop_loss")
            sl2_order = orders_by_role.get("sl2")
            tp1_order = orders_by_role.get("tp1")
            tp2_order = orders_by_role.get("tp2")
            tp3_order = orders_by_role.get("tp3")

            sl_price = get_stop_trigger_price(sl_order)
            sl2_price = get_stop_trigger_price(sl2_order)
            tp1_price = get_order_trigger_price(tp1_order)
            tp2_price = get_order_trigger_price(tp2_order)
            tp3_price = get_order_trigger_price(tp3_order)

            if side == "long":
                sl_hit = sl_price is not None and low <= sl_price
                sl2_hit = sl2_price is not None and low <= sl2_price
                tp1_hit = tp1_price is not None and high >= tp1_price
                tp2_hit = tp2_price is not None and high >= tp2_price
                tp3_hit = tp3_price is not None and high >= tp3_price

                if sl_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = sl_price
                    close_size = min(float(sl_order.get("remaining_size") or sl_order.get("requested_size") or position["remaining_size"]), float(position["remaining_size"]))
                    trigger_order = sl_order
                    break
                elif sl2_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = sl2_price
                    close_size = min(float(sl2_order.get("remaining_size") or sl2_order.get("requested_size") or position["remaining_size"]), float(position["remaining_size"]))
                    trigger_order = sl2_order
                    break
                elif tp1_hit:
                    execution_type = "TP1"
                    trigger_price = tp1_price
                    close_size = float(tp1_order["requested_size"] or 0.0)
                    trigger_order = tp1_order
                    break
                elif tp2_hit:
                    execution_type = "TP2"
                    trigger_price = tp2_price
                    close_size = float(tp2_order["requested_size"] or 0.0)
                    trigger_order = tp2_order
                    break
                elif tp3_hit:
                    execution_type = "TP3"
                    trigger_price = tp3_price
                    close_size = float(position["remaining_size"])
                    trigger_order = tp3_order
                    break

            elif side == "short":
                sl_hit = sl_price is not None and high >= sl_price
                sl2_hit = sl2_price is not None and high >= sl2_price
                tp1_hit = tp1_price is not None and low <= tp1_price
                tp2_hit = tp2_price is not None and low <= tp2_price
                tp3_hit = tp3_price is not None and low <= tp3_price

                if sl_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = sl_price
                    close_size = min(float(sl_order.get("remaining_size") or sl_order.get("requested_size") or position["remaining_size"]), float(position["remaining_size"]))
                    trigger_order = sl_order
                    break
                elif sl2_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = sl2_price
                    close_size = min(float(sl2_order.get("remaining_size") or sl2_order.get("requested_size") or position["remaining_size"]), float(position["remaining_size"]))
                    trigger_order = sl2_order
                    break
                elif tp1_hit:
                    execution_type = "TP1"
                    trigger_price = tp1_price
                    close_size = float(tp1_order["requested_size"] or 0.0)
                    trigger_order = tp1_order
                    break
                elif tp2_hit:
                    execution_type = "TP2"
                    trigger_price = tp2_price
                    close_size = float(tp2_order["requested_size"] or 0.0)
                    trigger_order = tp2_order
                    break
                elif tp3_hit:
                    execution_type = "TP3"
                    trigger_price = tp3_price
                    close_size = float(position["remaining_size"])
                    trigger_order = tp3_order
                    break
            else:
                return {"ok": False, "error": "unsupported_position_side"}

    if execution_type is None:
        return {
            "ok": True,
            "action": "NO_ACTION",
            "protective_order_validation": protective_validation,
        }

    if execution_type == "STOP_LOSS":
        stop_order_type = str(trigger_order.get("order_type", "")).lower()
        stop_limit_price = get_order_requested_price(trigger_order)

        if stop_order_type == "limit" and not force_market_stop_loss:
            if stop_limit_price is None or not can_fill_stop_limit_now(candles, float(stop_limit_price)):
                return {
                    "ok": True,
                    "action": "STOP_LOSS_PENDING",
                    "order_id": int(trigger_order["order_id"]) if trigger_order and trigger_order.get("order_id") is not None else None,
                    "trigger_price": float(trigger_price),
                    "limit_price": float(stop_limit_price) if stop_limit_price is not None else None,
                    "reason_codes": ["STOP_LIMIT_NOT_FILLED"],
                }

    close_size = min(float(close_size), float(position["remaining_size"]))

    effective_order_type = "limit"
    effective_slippage_bps = 0.0

    if execution_type == "STOP_LOSS" and force_market_stop_loss:
        effective_order_type = "market"
        effective_slippage_bps = MARKET_SLIPPAGE_PCT * 100

    stop_limit_price = get_order_requested_price(trigger_order) if execution_type == "STOP_LOSS" else None

    actual_fill_price = (
        apply_market_slippage(trigger_price, side, execution_type)
        if effective_order_type == "market"
        else float(stop_limit_price if execution_type == "STOP_LOSS" and stop_limit_price is not None else trigger_price)
    )

    notional = actual_fill_price * close_size
    fee_pct = LIMIT_FEE_PCT if effective_order_type == "limit" else MARKET_FEE_PCT
    fee_paid = calc_fee(notional, fee_pct)

    execution_event = {
        "account_id": account_id,
        "symbol": symbol,
        "position_side": side,
        "execution_type": execution_type,
        "order_type": effective_order_type,
        "order_id": int(trigger_order["order_id"]) if trigger_order and trigger_order.get("order_id") is not None else None,
        "fill_price": actual_fill_price,
        "filled_size": close_size,
        "fee_paid": fee_paid,
        "slippage_bps": effective_slippage_bps,
        "notes": f"paper maintenance {execution_type.lower()} trigger",
        "order_role": str(trigger_order.get("role") or "").lower() if trigger_order else None,
    }
    guardian_result, g_error = send_execution_to_guardian(execution_event)
    if g_error:
        return {"ok": False, "error": g_error}

    return {
        "ok": True,
        "action": f"{execution_type}_TRIGGERED",
        "execution_event": execution_event,
        "guardian_result": guardian_result,
        "protective_order_validation": protective_validation,
    }


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
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
                "runtime_version": RUNTIME_VERSION,
                "paper_execution_version": PAPER_EXECUTION_VERSION,
                "paper_execution_report_version": PAPER_EXECUTION_REPORT_VERSION,
                "pending_entry_policy_version": PENDING_ENTRY_POLICY_VERSION,
                "execution_pricing_version": EXECUTION_PRICING_VERSION,
                "protective_order_policy_version": PROTECTIVE_ORDER_POLICY_VERSION,
                "pending_entry_policy": build_pending_entry_policy_contract(),
                "execution_pricing": pricing_contract(),
                "protective_order_policy": build_protective_order_policy_contract(),
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/entry/simulate":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
                result = simulate_entry(payload)
                self._send_json(result, status=200 if result.get("ok") else 400)
                return
            except Exception as e:
                self._send_json({"ok": False, "error": "internal_error", "details": str(e)}, status=500)
                return

        if self.path == "/maintenance/check":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
                result = simulate_maintenance(payload)
                self._send_json(result, status=200 if result.get("ok") else 400)
                return
            except Exception as e:
                self._send_json({"ok": False, "error": "internal_error", "details": str(e)}, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
