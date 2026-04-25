from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone
import json
import os

import requests


SERVICE_NAME = "paper-execution"
PORT = int(os.getenv("PORT", "8080"))

DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
API_GATEWAY_LATEST_PRICE_PATH = os.getenv("API_GATEWAY_LATEST_PRICE_PATH", "/providers/bitget/ticker")

LIMIT_FEE_PCT = float(os.getenv("LIMIT_FEE_PCT", "0.02"))
MARKET_FEE_PCT = float(os.getenv("MARKET_FEE_PCT", "0.06"))
MARKET_SLIPPAGE_PCT = float(os.getenv("MARKET_SLIPPAGE_PCT", "0.06"))


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

    # exits
    if position_side == "long":
        return price * (1 - slip)
    if position_side == "short":
        return price * (1 + slip)

    return price

def apply_exit_fill_price(trigger_price: float, position_side: str, execution_type: str) -> float:
    if execution_type.startswith("TP"):
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

def fetch_latest_price(symbol: str):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}{API_GATEWAY_LATEST_PRICE_PATH}",
            params={"symbol": symbol},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"latest_price_request_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "latest_price_fetch_failed")

    price = payload.get("mark_price")
    if price is None:
        price = payload.get("last_price")

    if price is None:
        return None, "latest_price_missing_in_response"

    return float(price), None

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
        and o.get("role") in ("stop_loss", "tp1", "tp2", "tp3")
    ]

    return filtered, None

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

def evaluate_live_price_trigger(side: str, current_price: float, orders_by_role: dict, remaining_size: float):
    sl_order = orders_by_role.get("stop_loss")
    tp1_order = orders_by_role.get("tp1")
    tp2_order = orders_by_role.get("tp2")
    tp3_order = orders_by_role.get("tp3")

    if side == "long":
        if sl_order is not None and sl_order.get("entry_price") is not None:
            if current_price <= float(sl_order["entry_price"]):
                return "STOP_LOSS", float(sl_order["entry_price"]), float(remaining_size), sl_order

        if tp1_order is not None and tp1_order.get("entry_price") is not None:
            if current_price >= float(tp1_order["entry_price"]):
                return "TP1", float(tp1_order["entry_price"]), float(tp1_order["requested_size"] or 0.0), tp1_order

        if tp2_order is not None and tp2_order.get("entry_price") is not None:
            if current_price >= float(tp2_order["entry_price"]):
                return "TP2", float(tp2_order["entry_price"]), float(tp2_order["requested_size"] or 0.0), tp2_order

        if tp3_order is not None and tp3_order.get("entry_price") is not None:
            if current_price >= float(tp3_order["entry_price"]):
                return "TP3", float(tp3_order["entry_price"]), float(remaining_size), tp3_order

    elif side == "short":
        if sl_order is not None and sl_order.get("entry_price") is not None:
            if current_price >= float(sl_order["entry_price"]):
                return "STOP_LOSS", float(sl_order["entry_price"]), float(remaining_size), sl_order

        if tp1_order is not None and tp1_order.get("entry_price") is not None:
            if current_price <= float(tp1_order["entry_price"]):
                return "TP1", float(tp1_order["entry_price"]), float(tp1_order["requested_size"] or 0.0), tp1_order

        if tp2_order is not None and tp2_order.get("entry_price") is not None:
            if current_price <= float(tp2_order["entry_price"]):
                return "TP2", float(tp2_order["entry_price"]), float(tp2_order["requested_size"] or 0.0), tp2_order

        if tp3_order is not None and tp3_order.get("entry_price") is not None:
            if current_price <= float(tp3_order["entry_price"]):
                return "TP3", float(tp3_order["entry_price"]), float(remaining_size), tp3_order

    return None

def execute_market_entry(
    account_id: int,
    symbol: str,
    position_side: str,
    entry_price: float,
    size: float,
    payload: dict,
    notes: str = "paper market entry fill",
):
    slipped_price = apply_market_slippage(entry_price, position_side, "ENTRY")
    notional = slipped_price * size
    fee_paid = calc_fee(notional, MARKET_FEE_PCT)

    execution_event = {
        "account_id": account_id,
        "symbol": symbol,
        "position_side": position_side,
        "execution_type": "ENTRY",
        "order_type": "market",
        "fill_price": slipped_price,
        "filled_size": size,
        "fee_paid": fee_paid,
        "slippage_bps": MARKET_SLIPPAGE_PCT * 100,
        "stop_loss": float(payload["stop_loss"]),
        "tp1_price": float(payload["tp1_price"]),
        "tp2_price": float(payload["tp2_price"]),
        "tp3_price": float(payload["tp3_price"]),
        "risk_amount": float(payload["risk_amount"]),
        "leverage": float(payload.get("leverage", 1.0)),
        "notes": notes,
    }

    guardian_result, g_error = send_execution_to_guardian(execution_event)
    if g_error:
        return {"ok": False, "error": g_error}

    return {
        "ok": True,
        "action": "ENTRY_FILLED",
        "fill_method": "market",
        "execution_event": execution_event,
        "guardian_result": guardian_result,
    }


def simulate_entry(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    position_side = payload["position_side"].lower()
    
    order_type = str(payload.get("order_type") or payload.get("entry_order_type") or "").lower()
    if order_type not in ("limit", "market"):
        return {"ok": False, "error": "unsupported_order_type"}

    entry_price = float(payload["entry_price"])
    size = float(payload["size"])
    attempt_number = int(payload.get("attempt_number", 1))
    max_attempts = int(payload.get("max_attempts", 15))

    candles, error = fetch_recent_candles(symbol, "5m", limit=3)
    if error:
        return {"ok": False, "error": error}

    if order_type == "limit":
        if recent_candles_touch_limit(candles, entry_price):
            notional = entry_price * size
            fee_paid = calc_fee(notional, LIMIT_FEE_PCT)

            execution_event = {
                "account_id": account_id,
                "symbol": symbol,
                "position_side": position_side,
                "execution_type": "ENTRY",
                "order_type": "limit",
                "fill_price": entry_price,
                "filled_size": size,
                "fee_paid": fee_paid,
                "slippage_bps": 0.0,
                "stop_loss": float(payload["stop_loss"]),
                "tp1_price": float(payload["tp1_price"]),
                "tp2_price": float(payload["tp2_price"]),
                "tp3_price": float(payload["tp3_price"]),
                "risk_amount": float(payload["risk_amount"]),
                "leverage": float(payload.get("leverage", 1.0)),
                "notes": payload.get("notes", "paper limit entry fill")
            }

            guardian_result, g_error = send_execution_to_guardian(execution_event)
            if g_error:
                return {"ok": False, "error": g_error}

            return {
                "ok": True,
                "action": "ENTRY_FILLED",
                "fill_method": "limit",
                "execution_event": execution_event,
                "guardian_result": guardian_result
            }

        if attempt_number < max_attempts:
            return {
                "ok": True,
                "action": "ENTRY_PENDING",
                "attempt_number": attempt_number,
                "next_attempt_number": attempt_number + 1,
                "reason_codes": ["LIMIT_NOT_TOUCHED"],
            }

        return execute_market_entry(
            account_id=account_id,
            symbol=symbol,
            position_side=position_side,
            entry_price=entry_price,
            size=size,
            payload=payload,
            notes="paper market fallback after limit max attempts",
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
        )

    return {"ok": False, "error": "unsupported_order_type"}


def simulate_maintenance(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()

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
            tp1_order = orders_by_role.get("tp1")
            tp2_order = orders_by_role.get("tp2")
            tp3_order = orders_by_role.get("tp3")

            if side == "long":
                sl_hit = sl_order is not None and sl_order.get("entry_price") is not None and low <= float(sl_order["entry_price"])
                tp1_hit = tp1_order is not None and tp1_order.get("entry_price") is not None and high >= float(tp1_order["entry_price"])
                tp2_hit = tp2_order is not None and tp2_order.get("entry_price") is not None and high >= float(tp2_order["entry_price"])
                tp3_hit = tp3_order is not None and tp3_order.get("entry_price") is not None and high >= float(tp3_order["entry_price"])

                # Conservative rule: SL first if touched in same candle.
                if sl_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = float(sl_order["entry_price"])
                    close_size = float(position["remaining_size"])
                    trigger_order = sl_order
                    break
                elif tp1_hit:
                    execution_type = "TP1"
                    trigger_price = float(tp1_order["entry_price"])
                    close_size = float(tp1_order["requested_size"] or 0.0)
                    trigger_order = tp1_order
                    break
                elif tp2_hit:
                    execution_type = "TP2"
                    trigger_price = float(tp2_order["entry_price"])
                    close_size = float(tp2_order["requested_size"] or 0.0)
                    trigger_order = tp2_order
                    break
                elif tp3_hit:
                    execution_type = "TP3"
                    trigger_price = float(tp3_order["entry_price"])
                    close_size = float(position["remaining_size"])
                    trigger_order = tp3_order
                    break

            elif side == "short":
                sl_hit = sl_order is not None and sl_order.get("entry_price") is not None and high >= float(sl_order["entry_price"])
                tp1_hit = tp1_order is not None and tp1_order.get("entry_price") is not None and low <= float(tp1_order["entry_price"])
                tp2_hit = tp2_order is not None and tp2_order.get("entry_price") is not None and low <= float(tp2_order["entry_price"])
                tp3_hit = tp3_order is not None and tp3_order.get("entry_price") is not None and low <= float(tp3_order["entry_price"])

                if sl_hit:
                    execution_type = "STOP_LOSS"
                    trigger_price = float(sl_order["entry_price"])
                    close_size = float(position["remaining_size"])
                    trigger_order = sl_order
                    break
                elif tp1_hit:
                    execution_type = "TP1"
                    trigger_price = float(tp1_order["entry_price"])
                    close_size = float(tp1_order["requested_size"] or 0.0)
                    trigger_order = tp1_order
                    break
                elif tp2_hit:
                    execution_type = "TP2"
                    trigger_price = float(tp2_order["entry_price"])
                    close_size = float(tp2_order["requested_size"] or 0.0)
                    trigger_order = tp2_order
                    break
                elif tp3_hit:
                    execution_type = "TP3"
                    trigger_price = float(tp3_order["entry_price"])
                    close_size = float(position["remaining_size"])
                    trigger_order = tp3_order
                    break
            else:
                return {"ok": False, "error": "unsupported_position_side"}   

    if execution_type is None:
        return {
            "ok": True,
            "action": "NO_ACTION"
        }

    close_size = min(float(close_size), float(position["remaining_size"]))
    actual_fill_price = apply_exit_fill_price(trigger_price, side, execution_type)
    notional = actual_fill_price * close_size
    fee_pct = LIMIT_FEE_PCT if execution_type.startswith("TP") else MARKET_FEE_PCT
    fee_paid = calc_fee(notional, fee_pct)

    execution_event = {
        "account_id": account_id,
        "symbol": symbol,
        "position_side": side,
        "execution_type": execution_type,
        "order_type": "limit" if execution_type.startswith("TP") else "market",
        "order_id": int(trigger_order["order_id"]) if trigger_order and trigger_order.get("order_id") is not None else None,
        "fill_price": actual_fill_price,
        "filled_size": close_size,
        "fee_paid": fee_paid,
        "slippage_bps": 0.0 if execution_type.startswith("TP") else MARKET_SLIPPAGE_PCT * 100,
        "notes": f"paper maintenance {execution_type.lower()} trigger"
    }
    guardian_result, g_error = send_execution_to_guardian(execution_event)
    if g_error:
        return {"ok": False, "error": g_error}

    return {
        "ok": True,
        "action": f"{execution_type}_TRIGGERED",
        "execution_event": execution_event,
        "guardian_result": guardian_result
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
                "timestamp": iso_now()
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