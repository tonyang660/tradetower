from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from datetime import datetime, timezone
import json
import os

import requests

from btc_macro_policy import (
    BTC_MACRO_POLICY_VERSION,
    build_btc_macro_policy_contract,
    evaluate_btc_macro_risk_adjustment,
)
from correlation_policy import (
    CORRELATION_POLICY_VERSION,
    build_correlation_policy_contract,
    evaluate_correlation_constraints,
)
from leverage_policy import (
    LEVERAGE_POLICY_VERSION,
    build_leverage_policy_contract,
    select_safe_leverage,
)
from portfolio_policy import (
    PORTFOLIO_POLICY_VERSION,
    build_portfolio_policy_contract,
    evaluate_portfolio_constraints,
)
from weekly_drawdown_policy import (
    WEEKLY_DRAWDOWN_POLICY_VERSION,
    build_weekly_drawdown_policy_contract,
    evaluate_weekly_drawdown_threshold,
)
from risk_approval_payload import (
    RISK_APPROVAL_PAYLOAD_VERSION,
    build_risk_approval_payload_contract,
    build_risk_approval_payload_v2,
    build_risk_rejection_payload_v2,
)
from risk_policy import (
    RISK_ENGINE_VERSION,
    RISK_POLICY_VERSION,
    calculate_base_risk_amount,
    extract_strategy_trade_candidate,
    build_rejection,
)


SERVICE_NAME = "risk-engine"
PORT = int(os.getenv("PORT", "8080"))

TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "15.0"))
MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE = float(os.getenv("MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE", "1.0"))
MIN_LIQUIDATION_BUFFER_PCT = float(os.getenv("MIN_LIQUIDATION_BUFFER_PCT", "0.35"))
LEVERAGE_SEQUENCE = [
    float(item.strip())
    for item in os.getenv(
        "LEVERAGE_SEQUENCE",
        "15,14,13,12,11,10,9,8,7",
    ).split(",")
    if item.strip()
]

# v1 TP policy fallback. Strategy Engine/Risk payloads should normally carry
# take_profits from Phase 4 Step 9/12.
TP1_RATIO = 1.5
TP2_RATIO = 2.5
TP3_RATIO = 3.5
TP1_CLOSE_PERCENT = 50
TP2_CLOSE_PERCENT = 30
TP3_CLOSE_PERCENT = 20

RUNTIME_VERSION = "phase5_step10_risk_approval_payload_v2"

WEEKLY_DRAWDOWN_THRESHOLD_PCT = float(os.getenv("WEEKLY_DRAWDOWN_THRESHOLD_PCT", "3.0"))
WEEKLY_DRAWDOWN_SCORE_PENALTY = int(os.getenv("WEEKLY_DRAWDOWN_SCORE_PENALTY", "10"))
BASE_TRADE_SCORE_THRESHOLD = int(os.getenv("BASE_TRADE_SCORE_THRESHOLD", "75"))

MAX_CORRELATED_ENTRIES = int(os.getenv("MAX_CORRELATED_ENTRIES", "2"))

MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_PENDING_ENTRIES = int(os.getenv("MAX_PENDING_ENTRIES", "5"))
MAX_TOTAL_ACTIVE_ENTRIES = int(os.getenv("MAX_TOTAL_ACTIVE_ENTRIES", "5"))
MAX_DIRECTIONAL_ENTRIES = int(os.getenv("MAX_DIRECTIONAL_ENTRIES", "4"))
MAX_PORTFOLIO_NOTIONAL_MULTIPLE = float(os.getenv("MAX_PORTFOLIO_NOTIONAL_MULTIPLE", "10.0"))
MAX_MARGIN_USAGE_PCT = float(os.getenv("MAX_MARGIN_USAGE_PCT", "80.0"))

SYMBOL_UNIVERSE_PATH = os.getenv("SYMBOL_UNIVERSE_PATH", "/app/config/symbol_universe.json")


def load_symbol_universe_metadata() -> list[dict]:
    try:
        with open(SYMBOL_UNIVERSE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []

    items = []
    for item in payload.get("symbols", []) or []:
        if isinstance(item, dict):
            items.append(item)
    return items



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


def fetch_open_positions(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/positions/open",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception:
        return None, "TRADE_GUARDIAN_POSITIONS_UNAVAILABLE"

    if not payload.get("ok"):
        return None, payload.get("error", "TRADE_GUARDIAN_POSITIONS_UNAVAILABLE")

    return payload.get("positions", []), None


def fetch_pending_entry_orders(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/pending-entries",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception:
        return None, "TRADE_GUARDIAN_PENDING_ENTRIES_UNAVAILABLE"

    if not payload.get("ok", False):
        return None, payload.get("error", "TRADE_GUARDIAN_PENDING_ENTRIES_UNAVAILABLE")

    return payload.get("items", []), None


def fetch_guardian_risk_state(account_id: int, guardian_status: dict | None = None):
    """
    Trade Guardian owns risk/account state.

    Preferred future endpoint:
        GET /risk/state?account_id=...

    Backward-compatible fallback:
        use fields already present in /status if /risk/state does not exist.
    """
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/risk/state",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
        if r.status_code == 200 and payload.get("ok", False):
            return payload, None
    except Exception:
        pass

    if guardian_status is not None:
        return {
            "ok": True,
            "source": "trade_guardian_status_fallback",
            **guardian_status,
        }, None

    return None, "TRADE_GUARDIAN_RISK_STATE_UNAVAILABLE"


def build_policy_versions() -> dict:
    return {
        "risk_policy": RISK_POLICY_VERSION,
        "leverage_policy": LEVERAGE_POLICY_VERSION,
        "portfolio_policy": PORTFOLIO_POLICY_VERSION,
        "correlation_policy": CORRELATION_POLICY_VERSION,
        "weekly_drawdown_policy": WEEKLY_DRAWDOWN_POLICY_VERSION,
        "btc_macro_policy": BTC_MACRO_POLICY_VERSION,
        "risk_approval_payload": RISK_APPROVAL_PAYLOAD_VERSION,
    }


def reject_v2(symbol: str, reason_codes: list[str], context: dict | None = None) -> dict:
    # Preserve the existing risk_policy rejection details while adding the v2
    # payload contract fields in a stable shape.
    legacy = build_rejection(
        symbol,
        reason_codes,
        context=context,
    )
    v2 = build_risk_rejection_payload_v2(
        symbol=symbol,
        reason_codes=reason_codes,
        context=legacy.get("risk_context", context or {}),
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        runtime_version=RUNTIME_VERSION,
        policy_versions=build_policy_versions(),
    )
    if legacy.get("reason_details"):
        v2["reason_details"] = legacy["reason_details"]
    return v2


def safe_float(value, default: float | None = None):
    try:
        return float(value)
    except Exception:
        return default


def normalize_position_side(payload: dict):
    for key in ("position_side", "decision_side", "side"):
        value = payload.get(key)
        if value is None:
            continue
        value = str(value).lower()
        if value in ("long", "short"):
            return value
    return None


def extract_v2_signal_payload(payload: dict) -> dict:
    """
    Accept both payload styles:

    1. Scheduler wrapper:
       {
         account_id,
         symbol,
         position_side,
         entry_order_type,
         entry_price,
         stop_loss,
         take_profits,
         strategy_signal: {...}
       }

    2. Direct Strategy Signal v2:
       {
         schema_version: strategy_signal_v2,
         v2_decision: trade_candidate,
         proposed_trade: {...}
       }
    """
    strategy_signal = payload.get("strategy_signal")
    if isinstance(strategy_signal, dict):
        merged = dict(strategy_signal)
        for key in (
            "symbol",
            "position_side",
            "decision_side",
            "entry_order_type",
            "entry_price",
            "stop_loss",
            "take_profits",
            "risk_per_unit",
        ):
            if payload.get(key) is not None:
                merged[key] = payload[key]
        return merged

    return payload


def normalize_take_profits(payload: dict, side: str, entry: float, stop: float) -> dict | None:
    take_profits = payload.get("take_profits")
    if not isinstance(take_profits, dict):
        proposed_trade = payload.get("proposed_trade") or {}
        take_profits = proposed_trade.get("take_profits")

    if isinstance(take_profits, dict):
        try:
            tp1 = take_profits["tp1"]
            tp2 = take_profits["tp2"]
            tp3 = take_profits["tp3"]
            return {
                "tp1": {
                    "price": float(tp1["price"]),
                    "close_percent": float(tp1.get("close_percent", TP1_CLOSE_PERCENT)),
                    "ratio": float(tp1.get("ratio", TP1_RATIO)),
                },
                "tp2": {
                    "price": float(tp2["price"]),
                    "close_percent": float(tp2.get("close_percent", TP2_CLOSE_PERCENT)),
                    "ratio": float(tp2.get("ratio", TP2_RATIO)),
                },
                "tp3": {
                    "price": float(tp3["price"]),
                    "close_percent": float(tp3.get("close_percent", TP3_CLOSE_PERCENT)),
                    "ratio": float(tp3.get("ratio", TP3_RATIO)),
                },
            }
        except Exception:
            return None

    risk_unit = abs(entry - stop)
    if risk_unit <= 0:
        return None

    if side == "long":
        return {
            "tp1": {"price": entry + (risk_unit * TP1_RATIO), "close_percent": TP1_CLOSE_PERCENT, "ratio": TP1_RATIO},
            "tp2": {"price": entry + (risk_unit * TP2_RATIO), "close_percent": TP2_CLOSE_PERCENT, "ratio": TP2_RATIO},
            "tp3": {"price": entry + (risk_unit * TP3_RATIO), "close_percent": TP3_CLOSE_PERCENT, "ratio": TP3_RATIO},
        }

    if side == "short":
        return {
            "tp1": {"price": entry - (risk_unit * TP1_RATIO), "close_percent": TP1_CLOSE_PERCENT, "ratio": TP1_RATIO},
            "tp2": {"price": entry - (risk_unit * TP2_RATIO), "close_percent": TP2_CLOSE_PERCENT, "ratio": TP2_RATIO},
            "tp3": {"price": entry - (risk_unit * TP3_RATIO), "close_percent": TP3_CLOSE_PERCENT, "ratio": TP3_RATIO},
        }

    return None


def validate_signal_intake(payload: dict):
    reason_codes = []

    schema_version = payload.get("schema_version")
    v2_decision = payload.get("v2_decision") or payload.get("decision")

    # During Step 12 compatibility, Scheduler sends legacy decision=trade and
    # may put compact Strategy Signal metadata under strategy_signal. Accept both
    # direct v2 and wrapped compatibility forms.
    direct_v2 = schema_version == "strategy_signal_v2"
    compatible_trade = payload.get("legacy_decision") == "trade" or payload.get("decision") == "trade"

    if not direct_v2 and not compatible_trade:
        reason_codes.append("INVALID_STRATEGY_SIGNAL_SCHEMA")

    if direct_v2 and v2_decision not in ("trade_candidate", "trade"):
        reason_codes.append("NOT_A_TRADE_CANDIDATE")

    side = normalize_position_side(payload)
    if side is None:
        reason_codes.append("MISSING_POSITION_SIDE")
    elif side not in ("long", "short"):
        reason_codes.append("INVALID_POSITION_SIDE")

    entry_order_type = payload.get("entry_order_type")
    if entry_order_type not in ("limit", "market"):
        reason_codes.append("INVALID_ENTRY_ORDER_TYPE")

    entry = safe_float(payload.get("entry_price"))
    if entry is None:
        reason_codes.append("MISSING_ENTRY_PRICE")

    stop = safe_float(payload.get("stop_loss"))
    if stop is None:
        reason_codes.append("MISSING_STOP_LOSS")

    if entry is not None and stop is not None and side in ("long", "short"):
        if compute_stop_distance(side, entry, stop) <= 0:
            reason_codes.append("INVALID_STOP_DISTANCE")

    if entry is not None and stop is not None and side in ("long", "short"):
        tps = normalize_take_profits(payload, side, entry, stop)
        if tps is None:
            reason_codes.append("MISSING_TAKE_PROFITS")

    return reason_codes


def compute_stop_distance(side: str, entry: float, stop: float) -> float:
    if side == "long":
        return entry - stop
    if side == "short":
        return stop - entry
    return 0.0


def build_tp_ladder(side: str, entry: float, stop: float, payload: dict | None = None):
    payload = payload or {}
    take_profits = normalize_take_profits(payload, side, entry, stop)
    if not take_profits:
        return None

    return {
        "tp1_price": take_profits["tp1"]["price"],
        "tp2_price": take_profits["tp2"]["price"],
        "tp3_price": take_profits["tp3"]["price"],
        "tp1_close_percent": take_profits["tp1"]["close_percent"],
        "tp2_close_percent": take_profits["tp2"]["close_percent"],
        "tp3_close_percent": take_profits["tp3"]["close_percent"],
        "tp1_ratio": take_profits["tp1"]["ratio"],
        "tp2_ratio": take_profits["tp2"]["ratio"],
        "tp3_ratio": take_profits["tp3"]["ratio"],
        "take_profits": take_profits,
        "source": "strategy_engine_v1_take_profits" if isinstance(payload.get("take_profits"), dict) else "risk_engine_v1_fallback",
    }


def get_minimum_notional_required(equity: float) -> float:
    max_deployable = equity * MAX_LEVERAGE
    return max_deployable * (MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE / 100.0)


def build_position_sizing(
    *,
    equity: float,
    side: str,
    entry: float,
    stop: float,
    risk_amount_multiplier: float = 1.0,
    risk_adjustment_context: dict | None = None,
) -> dict:
    base_risk = calculate_base_risk_amount(
        equity,
        max_risk_pct_ceiling=MAX_RISK_PCT,
    )
    stop_distance = compute_stop_distance(side, entry, stop)

    if stop_distance <= 0:
        return {
            "ok": False,
            "reason_codes": ["INVALID_STOP_DISTANCE"],
            "base_risk": base_risk,
            "stop_distance": stop_distance,
        }

    base_risk_amount = float(base_risk["risk_amount"])
    risk_amount_multiplier = max(0.0, min(2.0, float(risk_amount_multiplier)))
    risk_amount = base_risk_amount * risk_amount_multiplier

    size = risk_amount / stop_distance
    notional = size * entry

    return {
        "ok": True,
        "risk_engine_version": RISK_ENGINE_VERSION,
        "risk_policy_version": RISK_POLICY_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "dynamic_risk": base_risk,
        "risk_adjustment_context": risk_adjustment_context or {},
        "risk_amount_multiplier": round(risk_amount_multiplier, 8),
        "base_risk_amount": round(base_risk_amount, 8),
        "risk_pct": base_risk["risk_pct"],
        "risk_amount": round(risk_amount, 8),
        "stop_distance": round(stop_distance, 8),
        "size": round(size, 8),
        "notional": round(notional, 8),
    }


def plan_trade(payload: dict):
    account_id = int(payload["account_id"])

    signal_payload = extract_v2_signal_payload(payload)
    normalized_signal = extract_strategy_trade_candidate(signal_payload)

    # Merge normalized signal back into payload for compatibility with existing
    # leverage/margin code.
    working_payload = dict(payload)
    for key in (
        "schema_version",
        "symbol",
        "v2_decision",
        "legacy_decision",
        "position_side",
        "selected_strategy",
        "regime",
        "score",
        "entry_order_type",
        "entry_price",
        "stop_loss",
        "take_profits",
        "risk_per_unit",
        "reason_tags",
    ):
        if normalized_signal.get(key) is not None:
            working_payload[key] = normalized_signal[key]

    symbol = str(working_payload.get("symbol") or "").upper()

    guardian_status, g_error = fetch_guardian_status(account_id)
    if g_error:
        return reject_v2(
            symbol,
            [g_error],
            context={"runtime_version": RUNTIME_VERSION},
        )

    open_positions, open_positions_error = fetch_open_positions(account_id)
    if open_positions_error:
        return reject_v2(
            symbol,
            [open_positions_error],
            context={"runtime_version": RUNTIME_VERSION},
        )

    pending_entries, pending_entries_error = fetch_pending_entry_orders(account_id)
    if pending_entries_error:
        return reject_v2(
            symbol,
            [pending_entries_error],
            context={"runtime_version": RUNTIME_VERSION},
        )

    validation_errors = validate_signal_intake(working_payload)
    if validation_errors:
        return reject_v2(
            symbol,
            validation_errors,
            context={
                "runtime_version": RUNTIME_VERSION,
                "normalized_signal": {
                    k: v for k, v in normalized_signal.items()
                    if k != "raw_signal"
                },
            },
        )

    guardian_risk_state, guardian_risk_state_error = fetch_guardian_risk_state(
        account_id,
        guardian_status=guardian_status,
    )
    if guardian_risk_state_error:
        return reject_v2(
            symbol,
            [guardian_risk_state_error],
            context={"runtime_version": RUNTIME_VERSION},
        )

    weekly_drawdown_result = evaluate_weekly_drawdown_threshold(
        account_state=guardian_risk_state,
        strategy_context=normalized_signal,
        fallback_equity=float(guardian_status["equity"]),
        weekly_drawdown_threshold_pct=WEEKLY_DRAWDOWN_THRESHOLD_PCT,
        weekly_drawdown_score_penalty=WEEKLY_DRAWDOWN_SCORE_PENALTY,
        base_trade_score_threshold=BASE_TRADE_SCORE_THRESHOLD,
    )

    if not weekly_drawdown_result.get("ok"):
        return reject_v2(
            symbol,
            weekly_drawdown_result.get("reason_codes", ["SCORE_BELOW_WEEKLY_DRAWDOWN_THRESHOLD"]),
            context={
                "runtime_version": RUNTIME_VERSION,
                "weekly_drawdown_policy_version": WEEKLY_DRAWDOWN_POLICY_VERSION,
                "weekly_drawdown_result": weekly_drawdown_result,
                "normalized_signal": {
                    k: v for k, v in normalized_signal.items()
                    if k != "raw_signal"
                },
            },
        )

    side = normalize_position_side(working_payload)
    entry_order_type = working_payload["entry_order_type"]
    entry = float(working_payload["entry_price"])
    stop = float(working_payload["stop_loss"])
    leverage_hint = working_payload.get("leverage_hint")

    equity = float(guardian_status["equity"])
    cash_balance = float(guardian_status["cash_balance"])

    btc_macro_result = evaluate_btc_macro_risk_adjustment(
        payload=working_payload,
        base_risk_amount=calculate_base_risk_amount(
            equity,
            max_risk_pct_ceiling=MAX_RISK_PCT,
        )["risk_amount"],
    )

    sizing = build_position_sizing(
        equity=equity,
        side=side,
        entry=entry,
        stop=stop,
        risk_amount_multiplier=btc_macro_result["position_size_mult"],
        risk_adjustment_context={
            "btc_macro": btc_macro_result,
        },
    )
    if not sizing.get("ok"):
        return reject_v2(
            symbol,
            sizing.get("reason_codes", ["INVALID_POSITION_SIZING"]),
            context={"runtime_version": RUNTIME_VERSION, "sizing": sizing},
        )

    size = sizing["size"]
    notional = sizing["notional"]
    risk_amount = sizing["risk_amount"]
    stop_distance = sizing["stop_distance"]

    if size <= 0:
        return reject_v2(
            symbol,
            ["SIZE_NON_POSITIVE"],
            context={"runtime_version": RUNTIME_VERSION, "sizing": sizing},
        )

    minimum_notional_required = get_minimum_notional_required(equity)
    if notional < minimum_notional_required:
        return reject_v2(
            symbol,
            ["NOTIONAL_BELOW_MINIMUM"],
            context={
                "runtime_version": RUNTIME_VERSION,
                "notional": notional,
                "minimum_notional_required": minimum_notional_required,
                "sizing": sizing,
            },
        )

    tp_ladder = build_tp_ladder(side, entry, stop, working_payload)
    if tp_ladder is None:
        return reject_v2(
            symbol,
            ["MISSING_TAKE_PROFITS"],
            context={"runtime_version": RUNTIME_VERSION},
        )

    leverage_result = select_safe_leverage(
        side=side,
        entry=entry,
        stop=stop,
        notional=notional,
        cash_balance=cash_balance,
        max_leverage=MAX_LEVERAGE,
        leverage_hint=leverage_hint,
        min_liquidation_buffer_pct=MIN_LIQUIDATION_BUFFER_PCT,
        leverage_sequence=LEVERAGE_SEQUENCE,
    )

    if not leverage_result.get("ok"):
        return reject_v2(
            symbol,
            [leverage_result.get("reason", "NO_VALID_LEVERAGE_FOUND")],
            context={
                "runtime_version": RUNTIME_VERSION,
                "leverage_policy_version": LEVERAGE_POLICY_VERSION,
                "leverage_result": leverage_result,
                "sizing": sizing,
            },
        )

    portfolio_result = evaluate_portfolio_constraints(
        symbol=symbol,
        side=side,
        new_notional=notional,
        new_margin_required=leverage_result["margin_required"],
        equity=equity,
        cash_balance=cash_balance,
        open_positions=open_positions,
        pending_entries=pending_entries,
        max_open_positions=MAX_OPEN_POSITIONS,
        max_pending_entries=MAX_PENDING_ENTRIES,
        max_total_entries=MAX_TOTAL_ACTIVE_ENTRIES,
        max_directional_entries=MAX_DIRECTIONAL_ENTRIES,
        max_portfolio_notional_multiple=MAX_PORTFOLIO_NOTIONAL_MULTIPLE,
        max_margin_usage_pct=MAX_MARGIN_USAGE_PCT,
    )

    if not portfolio_result.get("ok"):
        return reject_v2(
            symbol,
            portfolio_result.get("reason_codes", ["PORTFOLIO_CONSTRAINT_REJECTED"]),
            context={
                "runtime_version": RUNTIME_VERSION,
                "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
                "portfolio_result": portfolio_result,
                "sizing": sizing,
                "leverage_result": leverage_result,
            },
        )

    symbol_universe = load_symbol_universe_metadata()
    correlation_result = evaluate_correlation_constraints(
        symbol=symbol,
        side=side,
        open_positions=open_positions,
        pending_entries=pending_entries,
        symbol_universe=symbol_universe,
        max_correlated_entries=MAX_CORRELATED_ENTRIES,
    )

    if not correlation_result.get("ok"):
        return reject_v2(
            symbol,
            correlation_result.get("reason_codes", ["CORRELATION_GROUP_LIMIT_REACHED"]),
            context={
                "runtime_version": RUNTIME_VERSION,
                "btc_macro_policy_version": BTC_MACRO_POLICY_VERSION,
                "correlation_policy_version": CORRELATION_POLICY_VERSION,
                "correlation_result": correlation_result,
                "portfolio_result": portfolio_result,
                "sizing": sizing,
                "leverage_result": leverage_result,
            },
        )

    take_profits = tp_ladder["take_profits"]

    return build_risk_approval_payload_v2(
        account_id=account_id,
        symbol=symbol,
        position_side=side,
        entry_order_type=entry_order_type,
        entry_price=entry,
        stop_loss=stop,
        tp_ladder=tp_ladder,
        sizing=sizing,
        leverage_result=leverage_result,
        portfolio_result=portfolio_result,
        correlation_result=correlation_result,
        weekly_drawdown_result=weekly_drawdown_result,
        btc_macro_result=btc_macro_result,
        normalized_signal=normalized_signal,
        risk_engine_version=RISK_ENGINE_VERSION,
        risk_policy_version=RISK_POLICY_VERSION,
        runtime_version=RUNTIME_VERSION,
        leverage_policy_version=LEVERAGE_POLICY_VERSION,
        portfolio_policy_version=PORTFOLIO_POLICY_VERSION,
        correlation_policy_version=CORRELATION_POLICY_VERSION,
        weekly_drawdown_policy_version=WEEKLY_DRAWDOWN_POLICY_VERSION,
        btc_macro_policy_version=BTC_MACRO_POLICY_VERSION,
        minimum_notional_required=minimum_notional_required,
    )


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
                "risk_engine_version": RISK_ENGINE_VERSION,
                "risk_approval_payload_version": RISK_APPROVAL_PAYLOAD_VERSION,
                "risk_policy_version": RISK_POLICY_VERSION,
                "leverage_policy_version": LEVERAGE_POLICY_VERSION,
                "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
                "correlation_policy_version": CORRELATION_POLICY_VERSION,
                "weekly_drawdown_policy_version": WEEKLY_DRAWDOWN_POLICY_VERSION,
                "runtime_version": RUNTIME_VERSION,
                "dynamic_risk_tiers_enabled": True,
                "max_risk_pct_ceiling": MAX_RISK_PCT,
                "leverage_policy": build_leverage_policy_contract(),
                "portfolio_policy": build_portfolio_policy_contract(),
                "btc_macro_policy": build_btc_macro_policy_contract(),
                "risk_approval_payload_contract": build_risk_approval_payload_contract(),
                "correlation_policy": build_correlation_policy_contract(),
                "weekly_drawdown_policy": build_weekly_drawdown_policy_contract(),
                "phase4_step12_tp_policy": {
                    "default_tp_ratios": [TP1_RATIO, TP2_RATIO, TP3_RATIO],
                    "default_tp_close_percents": [TP1_CLOSE_PERCENT, TP2_CLOSE_PERCENT, TP3_CLOSE_PERCENT],
                    "preserves_strategy_take_profits": True,
                }
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
