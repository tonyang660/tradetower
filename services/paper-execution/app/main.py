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


def fetch_latest_candle(symbol: str, timeframe: str = "5m"):
    try:
        r = requests.get(
            f"{DATA_HUB_BASE_URL}/candles",
            params={"symbol": symbol, "timeframe": timeframe, "limit": 1},
            timeout=10
        )
        payload = r.json()
    except Exception:
        return None, "data_hub_request_failed"

    if not payload.get("ok"):
        return None, payload.get("error", "data_hub_error")

    candles = payload.get("candles", [])
    if len(candles) != 1:
        return None, "no_recent_candle"

    return candles[0], None


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


def send_execution_to_guardian(execution_event: dict):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/execution/apply",
            json=execution_event,
            timeout=15
        )
        payload = r.json()
    except Exception:
        return None, "trade_guardian_request_failed"

    return payload, None


def candle_touches_limit(candle: dict, price: float) -> bool:
    return float(candle["low"]) <= price <= float(candle["high"])


def simulate_entry(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    position_side = payload["position_side"].lower()
    order_type = payload["order_type"].lower()
    entry_price = float(payload["entry_price"])
    size = float(payload["size"])
    attempt_number = int(payload.get("attempt_number", 1))
    max_attempts = int(payload.get("max_attempts", 2))

    candle, error = fetch_latest_candle(symbol, "5m")
    if error:
        return {"ok": False, "error": error}

    if order_type == "limit":
        if candle_touches_limit(candle, entry_price):
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
                "next_attempt_number": attempt_number + 1
            }

        return {
            "ok": True,
            "action": "ENTRY_REQUIRES_REVALIDATION",
            "reason_codes": ["LIMIT_NOT_FILLED_AFTER_MAX_ATTEMPTS"]
        }

    if order_type == "market":
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
            "notes": payload.get("notes", "paper market entry fill")
        }

        guardian_result, g_error = send_execution_to_guardian(execution_event)
        if g_error:
            return {"ok": False, "error": g_error}

        return {
            "ok": True,
            "action": "ENTRY_FILLED",
            "fill_method": "market",
            "execution_event": execution_event,
            "guardian_result": guardian_result
        }

    return {"ok": False, "error": "unsupported_order_type"}


def simulate_maintenance(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()

    position, error = fetch_open_position(account_id, symbol)
    if error:
        return {"ok": False, "error": error}

    candle, c_error = fetch_latest_candle(symbol, "5m")
    if c_error:
        return {"ok": False, "error": c_error}

    high = float(candle["high"])
    low = float(candle["low"])

    side = position["side"]
    execution_type = None
    trigger_price = None
    close_size = None

    # Conservative rule: if both touched in same candle, assume SL first.
    if side == "long":
        sl_hit = position["stop_loss"] is not None and low <= float(position["stop_loss"])
        tp1_hit = (not position["tp1_hit"]) and position["tp1_price"] is not None and high >= float(position["tp1_price"])
        tp2_hit = position["tp1_hit"] and (not position["tp2_hit"]) and position["tp2_price"] is not None and high >= float(position["tp2_price"])
        tp3_hit = (not position["tp3_hit"]) and position["tp3_price"] is not None and high >= float(position["tp3_price"])

        if sl_hit:
            execution_type = "STOP_LOSS"
            trigger_price = float(position["stop_loss"])
            close_size = float(position["remaining_size"])
        elif tp1_hit:
            execution_type = "TP1"
            trigger_price = float(position["tp1_price"])
            close_size = round(float(position["original_size"]) * 0.40, 8)
        elif tp2_hit:
            execution_type = "TP2"
            trigger_price = float(position["tp2_price"])
            close_size = round(float(position["original_size"]) * 0.40, 8)
        elif tp3_hit:
            execution_type = "TP3"
            trigger_price = float(position["tp3_price"])
            close_size = float(position["remaining_size"])

    elif side == "short":
        sl_hit = position["stop_loss"] is not None and high >= float(position["stop_loss"])
        tp1_hit = (not position["tp1_hit"]) and position["tp1_price"] is not None and low <= float(position["tp1_price"])
        tp2_hit = position["tp1_hit"] and (not position["tp2_hit"]) and position["tp2_price"] is not None and low <= float(position["tp2_price"])
        tp3_hit = (not position["tp3_hit"]) and position["tp3_price"] is not None and low <= float(position["tp3_price"])

        if sl_hit:
            execution_type = "STOP_LOSS"
            trigger_price = float(position["stop_loss"])
            close_size = float(position["remaining_size"])
        elif tp1_hit:
            execution_type = "TP1"
            trigger_price = float(position["tp1_price"])
            close_size = round(float(position["original_size"]) * 0.40, 8)
        elif tp2_hit:
            execution_type = "TP2"
            trigger_price = float(position["tp2_price"])
            close_size = round(float(position["original_size"]) * 0.40, 8)
        elif tp3_hit:
            execution_type = "TP3"
            trigger_price = float(position["tp3_price"])
            close_size = float(position["remaining_size"])
    else:
        return {"ok": False, "error": "unsupported_position_side"}

    if execution_type is None:
        return {
            "ok": True,
            "action": "NO_ACTION"
        }

    close_size = min(float(close_size), float(position["remaining_size"]))
    notional = trigger_price * close_size
    fee_pct = LIMIT_FEE_PCT if execution_type.startswith("TP") else MARKET_FEE_PCT
    fee_paid = calc_fee(notional, fee_pct)

    execution_event = {
        "account_id": account_id,
        "symbol": symbol,
        "position_side": side,
        "execution_type": execution_type,
        "order_type": "limit" if execution_type.startswith("TP") else "market",
        "fill_price": trigger_price,
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