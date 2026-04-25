from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone
import json
import os

import requests


SERVICE_NAME = "risk-engine"
PORT = int(os.getenv("PORT", "8080"))

TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "15.0"))
MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE = float(os.getenv("MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE", "1.0"))
MIN_LIQUIDATION_BUFFER_PCT = float(os.getenv("MIN_LIQUIDATION_BUFFER_PCT", "0.35"))
LEVERAGE_SEQUENCE = [15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0]


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_guardian_status(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/status",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception:
        return None, "TRADE_GUARDIAN_STATUS_UNAVAILABLE"

    if not payload.get("ok"):
        return None, payload.get("error", "TRADE_GUARDIAN_STATUS_UNAVAILABLE")

    return payload, None


def validate_proposal(payload: dict):
    reason_codes = []

    side = payload.get("position_side")
    order_type = payload.get("entry_order_type")

    try:
        entry = float(payload["entry_price"])
        stop = float(payload["stop_loss"])
    except Exception:
        return ["INVALID_NUMERIC_FIELDS"]

    if side not in ("long", "short"):
        reason_codes.append("INVALID_POSITION_SIDE")

    if order_type not in ("limit", "market"):
        reason_codes.append("INVALID_ENTRY_ORDER_TYPE")

    if side == "long":
        if not (stop < entry):
            reason_codes.append("INVALID_STOP_LOSS")

    elif side == "short":
        if not (stop > entry):
            reason_codes.append("INVALID_STOP_LOSS")

    return reason_codes


def compute_stop_distance(side: str, entry: float, stop: float) -> float:
    if side == "long":
        return entry - stop
    if side == "short":
        return stop - entry
    return 0.0

def build_tp_ladder(side: str, entry: float, stop: float):
    risk_unit = abs(entry - stop)

    if risk_unit <= 0:
        return None

    if side == "long":
        return {
            "tp1_price": entry + (1.0 * risk_unit),
            "tp2_price": entry + (2.0 * risk_unit),
            "tp3_price": entry + (3.5 * risk_unit),
        }

    if side == "short":
        return {
            "tp1_price": entry - (1.0 * risk_unit),
            "tp2_price": entry - (2.0 * risk_unit),
            "tp3_price": entry - (3.5 * risk_unit),
        }

    return None

def approximate_liquidation_price(side: str, entry: float, leverage: float) -> float | None:
    if leverage <= 0:
        return None

    # Simplified isolated-margin style approximation for paper trading.
    # Long liquidation is below entry, short liquidation is above entry.
    if side == "long":
        return entry * (1.0 - (1.0 / leverage))
    if side == "short":
        return entry * (1.0 + (1.0 / leverage))
    return None


def liquidation_buffer_pct(side: str, stop: float, liquidation_price: float, entry: float) -> float:
    if entry <= 0:
        return 0.0

    if side == "long":
        # want liquidation below stop; positive buffer means safe
        return ((stop - liquidation_price) / entry) * 100.0

    if side == "short":
        # want liquidation above stop; positive buffer means safe
        return ((liquidation_price - stop) / entry) * 100.0

    return 0.0


def is_liquidation_safely_beyond_stop(
    side: str,
    stop: float,
    liquidation_price: float,
    entry: float,
) -> bool:
    buffer_pct = liquidation_buffer_pct(side, stop, liquidation_price, entry)
    return buffer_pct >= MIN_LIQUIDATION_BUFFER_PCT

def get_minimum_notional_required(equity: float) -> float:
    max_deployable = equity * MAX_LEVERAGE
    return max_deployable * (MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE / 100.0)


def pick_starting_leverage(leverage_hint):
    if leverage_hint is not None:
        try:
            lev = float(leverage_hint)
            if lev <= 0:
                return None, "LEVERAGE_TOO_LOW"
            if lev > MAX_LEVERAGE:
                return None, "LEVERAGE_TOO_HIGH"
            return lev, None
        except Exception:
            return None, "INVALID_LEVERAGE_HINT"

    return MAX_LEVERAGE, None


def build_leverage_candidates(start_leverage: float | None = None):
    seq = sorted(set(LEVERAGE_SEQUENCE), reverse=True)
    seq = [x for x in seq if x <= MAX_LEVERAGE and x > 0]

    if start_leverage is not None and start_leverage > 0 and start_leverage <= MAX_LEVERAGE:
        if start_leverage not in seq:
            seq.append(start_leverage)
            seq = sorted(set(seq), reverse=True)

    return seq


def plan_trade(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    side = payload["position_side"]
    entry_order_type = payload["entry_order_type"]
    entry = float(payload["entry_price"])
    stop = float(payload["stop_loss"])
    leverage_hint = payload.get("leverage_hint")

    guardian_status, g_error = fetch_guardian_status(account_id)
    if g_error:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": [g_error]
        }

    validation_errors = validate_proposal(payload)
    if validation_errors:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": validation_errors
        }

    equity = float(guardian_status["equity"])
    cash_balance = float(guardian_status["cash_balance"])

    risk_amount = equity * (MAX_RISK_PCT / 100.0)
    stop_distance = compute_stop_distance(side, entry, stop)

    tp_ladder = build_tp_ladder(side, entry, stop)
    if tp_ladder is None:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": ["INVALID_TP_LADDER_BUILD"]
        }

    if stop_distance <= 0:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": ["STOP_DISTANCE_NON_POSITIVE"]
        }

    size = risk_amount / stop_distance
    if size <= 0:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": ["SIZE_NON_POSITIVE"]
        }

    notional = size * entry
    minimum_notional_required = get_minimum_notional_required(equity)

    if notional < minimum_notional_required:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": ["NOTIONAL_BELOW_MINIMUM"]
        }

    start_leverage, lev_error = pick_starting_leverage(leverage_hint)
    if lev_error:
        return {
            "ok": True,
            "approved": False,
            "reason_codes": [lev_error]
        }

    leverage_candidates = build_leverage_candidates(start_leverage)
    chosen_leverage = None
    margin_required = None
    liquidation_price = None
    liquidation_buffer = None
    leverage_rejections = []

    for lev in leverage_candidates:
        required = notional / lev
        liq_price = approximate_liquidation_price(side, entry, lev)

        if liq_price is None:
            leverage_rejections.append({
                "leverage": lev,
                "reason": "INVALID_LIQUIDATION_MODEL"
            })
            continue

        if required > cash_balance:
            leverage_rejections.append({
                "leverage": lev,
                "reason": "MARGIN_EXCEEDS_AVAILABLE_CAPITAL",
                "margin_required": round(required, 8),
            })
            continue

        if not is_liquidation_safely_beyond_stop(side, stop, liq_price, entry):
            leverage_rejections.append({
                "leverage": lev,
                "reason": "LIQUIDATION_TOO_CLOSE_TO_STOP",
                "liquidation_price": round(liq_price, 8),
                "liquidation_buffer_pct": round(liquidation_buffer_pct(side, stop, liq_price, entry), 6),
            })
            continue

        chosen_leverage = lev
        margin_required = required
        liquidation_price = liq_price
        liquidation_buffer = liquidation_buffer_pct(side, stop, liq_price, entry)
        break

    if chosen_leverage is None:
        rejection_codes = [x["reason"] for x in leverage_rejections] or ["NO_VALID_LEVERAGE_FOUND"]

        primary_reason = (
            "LIQUIDATION_CONSTRAINT_OR_MARGIN_EXCEEDED"
            if any(x["reason"] == "LIQUIDATION_TOO_CLOSE_TO_STOP" for x in leverage_rejections)
            else "MARGIN_EXCEEDS_AVAILABLE_CAPITAL"
        )

        return {
            "ok": True,
            "approved": False,
            "reason_codes": [primary_reason],
            "leverage_rejections": leverage_rejections,
        }

    return {
        "ok": True,
        "approved": True,
        "account_id": account_id,
        "symbol": symbol,
        "position_side": side,
        "entry_order_type": entry_order_type,
        "entry_price": round(entry, 8),
        "stop_loss": round(stop, 8),
        "tp1_price": round(tp_ladder["tp1_price"], 8),
        "tp2_price": round(tp_ladder["tp2_price"], 8),
        "tp3_price": round(tp_ladder["tp3_price"], 8),
        "risk_amount": round(risk_amount, 8),
        "risk_pct": MAX_RISK_PCT,
        "stop_distance": round(stop_distance, 8),
        "size": round(size, 8),
        "notional": round(notional, 8),
        "leverage": round(chosen_leverage, 8),
        "margin_required": round(margin_required, 8),
        "minimum_notional_required": round(minimum_notional_required, 8),
        "liquidation_price_estimate": round(liquidation_price, 8) if liquidation_price is not None else None,
        "liquidation_buffer_pct": round(liquidation_buffer, 6) if liquidation_buffer is not None else None,
        "reason_codes": []
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
        if self.path == "/plan":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
                result = plan_trade(payload)
                self._send_json(result, status=200 if result.get("ok") else 400)
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
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()