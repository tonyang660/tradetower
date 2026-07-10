import requests

from config import (
    API_GATEWAY_BASE_URL,
    DATA_HUB_BASE_URL,
    TRADE_GUARDIAN_BASE_URL,
    CANDIDATE_FILTER_BASE_URL,
    STRATEGY_ENGINE_BASE_URL,
    RISK_ENGINE_BASE_URL,
    PAPER_EXECUTION_BASE_URL,
    PAPER_EXECUTION_ENTRY_PATH,
    EVALUATOR_BASE_URL,
)
from time_utils import iso_now


def run_mark_to_market_refresh(account_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/mark-to-market/refresh",
            json={"account_id": account_id},
            timeout=15,
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
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_status_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_status_failed")

    return payload, None


def fetch_candles_from_api_gateway(symbol: str, timeframe: str, limit: int):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}/providers/bitget/candles",
            params={"symbol": symbol, "timeframe": timeframe, "limit": limit},
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"api_gateway_request_failed: {str(e)}"}


def ingest_candles_to_data_hub(payload: dict):
    try:
        r = requests.post(
            f"{DATA_HUB_BASE_URL}/candles/ingest",
            json=payload,
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": f"data_hub_ingest_failed: {str(e)}"}


def fetch_pending_entry_orders(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/pending-entries",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_pending_entries_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "pending_entries_fetch_failed")

    return payload.get("items", []), None


def cancel_pending_entry_order(account_id: int, order_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/entry/cancel",
            json={
                "account_id": account_id,
                "order_id": order_id,
            },
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_pending_entry_cancel_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "pending_entry_cancel_failed")

    return payload, None


def fetch_open_positions(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/positions/open",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_positions_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_positions_failed")

    return payload.get("positions", []), None


def check_maintenance(account_id: int, symbol: str):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/guard/check-maintenance",
            json={"account_id": account_id, "symbol": symbol},
            timeout=10,
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
            timeout=20,
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
            timeout=10,
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
            timeout=10,
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
            "rejected": [],
        }, None

    try:
        r = requests.get(
            f"{CANDIDATE_FILTER_BASE_URL}/candidates",
            params={"account_id": account_id, "symbols": ",".join(symbols)},
            timeout=30,
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
            timeout=30,
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


def run_risk_engine(risk_payload: dict):
    try:
        r = requests.post(
            f"{RISK_ENGINE_BASE_URL}/plan",
            json=risk_payload,
            timeout=30,
        )
        payload = r.json()
    except Exception as e:
        return None, f"risk_engine_request_failed: {str(e)}"

    return payload, None


def submit_entry_to_paper_execution(payload: dict):
    try:
        r = requests.post(
            f"{PAPER_EXECUTION_BASE_URL}{PAPER_EXECUTION_ENTRY_PATH}",
            json=payload,
            timeout=30,
        )
        result = r.json()
    except Exception as e:
        return None, f"paper_execution_entry_submit_failed: {str(e)}"

    return result, None


def ingest_cycle_summary_to_evaluator(summary: dict):
    try:
        r = requests.post(
            f"{EVALUATOR_BASE_URL}/ingest/cycle-summary",
            json=summary,
            timeout=20,
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
            timeout=20,
        )
        return r.json(), None
    except Exception as e:
        return None, f"evaluator_equity_ingest_failed: {str(e)}"
