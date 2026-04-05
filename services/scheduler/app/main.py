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

AUTO_LOOP_ENABLED = os.getenv("AUTO_LOOP_ENABLED", "false").lower() == "true"
LOOP_INTERVAL_SECONDS = int(os.getenv("LOOP_INTERVAL_SECONDS", "300"))
ACCOUNT_ID = int(os.getenv("ACCOUNT_ID", "1"))
SYMBOL_UNIVERSE_PATH = os.getenv("SYMBOL_UNIVERSE_PATH", "/app/config/symbol_universe.json")

TIMEFRAMES = ["5m", "15m", "1h", "4h"]
REFRESH_LIMIT = 72


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


# Added here because used in maintenance
PAPER_EXECUTION_BASE_URL = os.getenv("PAPER_EXECUTION_BASE_URL", "http://paper-execution:8080")


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
        "open_positions_count": 0,
        "maintenance": {
            "checked": 0,
            "actions_triggered": 0,
            "results": []
        },
        "entry_gate": None,
        "entry_eligible_symbols": [],
        "candidate_filter": None,
        "errors": []
    }

    try:
        # Phase 0: load universe
        enabled_symbols = load_symbol_universe()
        summary["enabled_symbols"] = enabled_symbols

        # Phase 1: refresh market data for full enabled universe
        for symbol in enabled_symbols:
            refresh_results = refresh_symbol_candles(symbol)
            summary["refresh_results"].extend(refresh_results)

        refreshed_ok_symbols = set()
        for item in summary["refresh_results"]:
            if item["ok"]:
                refreshed_ok_symbols.add(item["symbol"])
        summary["refreshed_symbols_count"] = len(refreshed_ok_symbols)

        # Phase 2: maintenance path
        open_positions, positions_error = fetch_open_positions(ACCOUNT_ID)
        if positions_error:
            summary["errors"].append(positions_error)
            open_positions = []

        summary["open_positions_count"] = len(open_positions)
        open_symbols = [p["symbol"] for p in open_positions]

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

        # Phase 3: entry gate
        entry_gate, entry_error = check_entry_gate(ACCOUNT_ID)
        if entry_error:
            summary["errors"].append(entry_error)
            summary["entry_gate"] = {
                "trade_allowed": False,
                "reason_codes": ["ENTRY_GATE_UNAVAILABLE"]
            }
        else:
            summary["entry_gate"] = entry_gate

        # Phase 4: build entry-eligible universe
        entry_eligible_symbols = [s for s in enabled_symbols if s not in open_symbols]
        summary["entry_eligible_symbols"] = entry_eligible_symbols

        # Phase 5: candidate filter only if entry allowed
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

    except Exception as e:
        summary["ok"] = False
        summary["errors"].append(f"unhandled_cycle_exception: {str(e)}")
        summary["errors"].append(traceback.format_exc())

    summary["completed_at"] = iso_now()
    return summary


def scheduler_loop():
    while True:
        if AUTO_LOOP_ENABLED:
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
                "auto_loop_enabled": AUTO_LOOP_ENABLED,
                "loop_interval_seconds": LOOP_INTERVAL_SECONDS
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
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