from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import json

from bootstrap import (
    get_bootstrap_overview,
    get_bootstrap_live_cycle_monitor,
    get_bootstrap_system_health,
)
from config import SERVICE_NAME, PORT
from configuration import get_bootstrap_configuration
from controls import set_configuration_auto_loop, set_manual_halt, set_scheduler_auto_loop
from data_fetchers import (
    get_bootstrap_performance,
    get_execution_history,
    get_open_orders,
    get_open_positions,
    get_recent_positions,
    get_bootstrap_strategy_analytics,
)
from health import get_market_session_banner, get_system_health
from symbol_config import (
    normalize_symbol_item,
    save_symbol_universe_config,
    validate_symbol_via_api_gateway,
)
from time_utils import iso_now

from dashboard_aggregation_v2_routes import handle_dashboard_aggregation_v2_get
from positions_orders_v2_routes import handle_positions_orders_v2_get
from performance_page_v2_routes import handle_performance_page_v2_get


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_json({
                "ok": False,
                "error": "invalid_json",
                "details": str(e),
            }, status=400)
            return

        if parsed.path == "/controls/trading/suspend":
            account_id = int(payload.get("account_id", 1))
            result, status = set_manual_halt(account_id, True)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/trading/resume":
            account_id = int(payload.get("account_id", 1))
            result, status = set_manual_halt(account_id, False)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/scheduler/enable":
            result, status = set_scheduler_auto_loop(True)
            self._send_json(result, status=status)
            return

        if parsed.path == "/controls/scheduler/disable":
            result, status = set_scheduler_auto_loop(False)
            self._send_json(result, status=status)
            return

        if parsed.path == "/configuration/validate-symbol":
            symbol = payload.get("symbol", "")
            result, status = validate_symbol_via_api_gateway(symbol)
            self._send_json(result, status=status)
            return

        if parsed.path == "/configuration/symbol-universe":
            symbols = payload.get("symbols")

            if not isinstance(symbols, list):
                self._send_json({
                    "ok": False,
                    "error": "invalid_symbols_payload",
                    "required": {
                        "symbols": [
                            {
                                "symbol": "BTCUSDT",
                                "enabled": True,
                                "priority": 1,
                                "correlation_group": "btc_followers",
                            }
                        ]
                    },
                }, status=400)
                return

            normalized_items = []
            seen = set()
            validation_errors = []

            for raw_item in symbols:
                item = normalize_symbol_item(raw_item)
                if not item:
                    continue

                symbol = item["symbol"]
                if symbol in seen:
                    continue
                seen.add(symbol)

                validation_result, validation_status = validate_symbol_via_api_gateway(symbol)
                if validation_status != 200 or not validation_result.get("valid", False):
                    validation_errors.append({
                        "symbol": symbol,
                        "error": validation_result.get("error", "symbol_not_found"),
                    })
                    continue

                normalized_items.append(item)

            if validation_errors:
                self._send_json({
                    "ok": False,
                    "error": "symbol_validation_failed",
                    "validation_errors": validation_errors,
                }, status=400)
                return

            result = save_symbol_universe_config(normalized_items)
            self._send_json(result, status=200 if result.get("ok") else 400)
            return

        if parsed.path == "/configuration/auto-loop":
            enabled = payload.get("enabled")

            if not isinstance(enabled, bool):
                self._send_json({
                    "ok": False,
                    "error": "invalid_enabled_flag",
                    "required": {"enabled": "boolean"},
                }, status=400)
                return

            result, status = set_configuration_auto_loop(enabled)
            self._send_json(result, status=status)
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
            })
            return
        
        if handle_dashboard_aggregation_v2_get(self, parsed): return
        if handle_positions_orders_v2_get(self, parsed): return
        if handle_performance_page_v2_get(self, parsed): return

        if parsed.path == "/market/banner":
            self._send_json(get_market_session_banner())
            return

        if parsed.path == "/system/health":
            self._send_json(get_system_health())
            return

        if parsed.path == "/bootstrap/overview":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_overview(account_id))
            return

        if parsed.path == "/bootstrap/live-cycle-monitor":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["15"])[0])
            self._send_json(get_bootstrap_live_cycle_monitor(account_id, limit))
            return

        if parsed.path == "/positions/open":
            account_id = int(query.get("account_id", ["1"])[0])
            refresh = query.get("refresh", ["true"])[0].lower() == "true"
            payload, status = get_open_positions(account_id, refresh)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/positions/recent":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["20"])[0])
            payload, status = get_recent_positions(account_id, limit)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/orders/open":
            account_id = int(query.get("account_id", ["1"])[0])
            payload, status = get_open_orders(account_id)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/orders/executed":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["50"])[0])
            payload, status = get_execution_history(account_id, limit)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/bootstrap/performance":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_performance(account_id))
            return

        if parsed.path == "/bootstrap/strategy-analytics":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_strategy_analytics(account_id))
            return

        if parsed.path == "/bootstrap/system-health":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_bootstrap_system_health(account_id))
            return

        if parsed.path == "/bootstrap/configuration":
            self._send_json(get_bootstrap_configuration())
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
