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


def run_maintenance(account_id: int, symbol: str):
    try:
        r = requests.post(
            f"{PAPER_EXECUTION_BASE_URL}/maintenance/check",
            json={"account_id": account_id, "symbol": symbol},
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


def check_entry_gate_for_symbol(account_id: int, symbol: str):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/guard/check-entry",
            json={"account_id": account_id, "symbol": symbol},
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


def build_risk_payload_from_strategy(account_id: int, strategy_result: dict):
    return {
        "account_id": account_id,
        "symbol": strategy_result["symbol"],
        "position_side": strategy_result["decision"],
        "entry_order_type": strategy_result["entry_order_type"],
        "entry_price": strategy_result["entry_price"],
        "stop_loss": strategy_result["stop_loss"],
        "tp1_price": strategy_result["tp1_price"],
        "tp2_price": strategy_result["tp2_price"],
        "tp3_price": strategy_result["tp3_price"],
    }


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
        "entry_order_type": strategy_result["entry_order_type"],
        "entry_price": strategy_result["entry_price"],
        "stop_loss": strategy_result["stop_loss"],
        "tp1_price": strategy_result["tp1_price"],
        "tp2_price": strategy_result["tp2_price"],
        "tp3_price": strategy_result["tp3_price"],
    }

    # Merge in the full risk-engine payload so paper-execution gets the final approved plan.
    # Keep strategy-level values above as the default context.
    if isinstance(risk_result, dict):
        payload.update(risk_result)

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
        "fees_paid_total": 0.0,
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

        "open_positions_before_maintenance_count": 0,
        "open_positions_count": 0,

        "maintenance": {
            "checked": 0,
            "actions_triggered": 0,
            "results": []
        },

        "entry_gate": None,
        "entry_eligible_symbols": [],
        "candidate_filter": None,

        "strategy_engine": {
            "analyzed": 0,
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
            "results": []
        },

        "errors": []
    }

    try:
        # Phase 0: load enabled symbol universe
        enabled_symbols = load_symbol_universe()
        summary["enabled_symbols"] = enabled_symbols

        # Phase 1: refresh market data for full enabled universe
        for symbol in enabled_symbols:
            refresh_results = refresh_symbol_candles(symbol)
            summary["refresh_results"].extend(refresh_results)

        refreshed_ok_symbols = set()
        for item in summary["refresh_results"]:
            if item.get("ok"):
                refreshed_ok_symbols.add(item["symbol"])
        summary["refreshed_symbols_count"] = len(refreshed_ok_symbols)

        # Phase 2: maintenance path
        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            summary["errors"].append(positions_error)
            open_positions = []

        summary["open_positions_before_maintenance_count"] = len(open_positions)
        open_symbols_before_maintenance = [p["symbol"] for p in open_positions]

        for pos in open_positions:
            symbol = pos["symbol"]
            summary["maintenance"]["checked"] += 1

            guard_result, guard_error = check_maintenance(ACCOUNT_ID, symbol)
            if guard_error:
                summary["maintenance"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "stage": "trade_guardian",
                    "error": guard_error
                })
                continue

            if not guard_result.get("maintenance_allowed", False):
                summary["maintenance"]["results"].append({
                    "symbol": symbol,
                    "ok": True,
                    "action": "MAINTENANCE_BLOCKED",
                    "reason_codes": guard_result.get("reason_codes", [])
                })
                continue

            maintenance_result, maintenance_error = run_maintenance(ACCOUNT_ID, symbol)
            if maintenance_error:
                summary["maintenance"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "stage": "paper_execution",
                    "error": maintenance_error
                })
                continue

            summary["maintenance"]["results"].append({
                "symbol": symbol,
                "ok": True,
                "result": maintenance_result
            })

            action = maintenance_result.get("action")
            if action and action != "NO_ACTION":
                summary["maintenance"]["actions_triggered"] += 1

        # Refresh open positions after maintenance so entry path uses current state
        post_maintenance_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            summary["errors"].append(positions_error)
            post_maintenance_positions = open_positions

        summary["open_positions_count"] = len(post_maintenance_positions)
        current_open_symbols = [p["symbol"] for p in post_maintenance_positions]

        maintenance_touched_symbols = {
            item["symbol"]
            for item in summary["maintenance"]["results"]
            if item.get("symbol")
        }

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
        entry_eligible_symbols = [
            s for s in enabled_symbols
            if s not in current_open_symbols and s not in maintenance_touched_symbols
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

            if strategy_result.get("decision") == "no_trade":
                continue

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

            summary["risk_engine"]["results"].append(risk_result)

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

            summary["final_entry_gate"]["results"].append(final_gate)

            if not final_gate.get("trade_allowed", False):
                summary["final_entry_gate"]["blocked"] += 1
                continue

            # Phase 9: submit approved plan to paper-execution
            paper_payload = build_paper_execution_payload(ACCOUNT_ID, strategy_result, risk_result)
            paper_result, paper_error = submit_entry_to_paper_execution(paper_payload)
            if paper_error:
                summary["paper_execution"]["results"].append({
                    "symbol": symbol,
                    "ok": False,
                    "error": paper_error
                })
                continue

            summary["paper_execution"]["submitted"] += 1
            if paper_result.get("filled", False):
                summary["paper_execution"]["fills"] += 1

            summary["paper_execution"]["results"].append(paper_result)

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

    return summary


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
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
                "auto_loop_enabled": AUTO_LOOP_ENABLED_STATE,
                "auto_loop_default": AUTO_LOOP_DEFAULT,
                "loop_interval_seconds": LOOP_INTERVAL_SECONDS,
                "paper_execution_entry_path": PAPER_EXECUTION_ENTRY_PATH
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

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()