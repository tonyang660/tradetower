from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import json

import state
from accounts import enabled_account_ids, PHASE8_SCHEDULER_ACCOUNTS_VERSION
from api_clients import fetch_pending_entry_orders
from config import (
    ACCOUNT_ID,
    AUTO_LOOP_DEFAULT,
    LOOP_INTERVAL_SECONDS,
    MAINTENANCE_LOOP_INTERVAL_SECONDS,
    PENDING_EXIT_LOOP_INTERVAL_SECONDS,
    PAPER_EXECUTION_ENTRY_PATH,
    PORT,
    SERVICE_NAME,
)
from cycle import run_one_cycle
from cycle_utils import build_pending_entry_status
from loops import (
    open_position_maintenance_loop,
    pending_entry_loop,
    pending_exit_loop,
    scheduler_loop,
)
from time_utils import iso_now


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
            pending_entries, pending_entries_error = (
                fetch_pending_entry_orders(ACCOUNT_ID)
            )

            enabled_ids, enabled_accounts_error = enabled_account_ids(ACCOUNT_ID)

            if pending_entries_error:
                self._send_json({
                    "ok": False,
                    "service": SERVICE_NAME,
                    "error": pending_entries_error,
                    "timestamp": iso_now(),
                }, status=502)
                return

            pending_status = build_pending_entry_status(
                pending_entries
            )

            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now(),
                "auto_loop_enabled": state.AUTO_LOOP_ENABLED_STATE,
                "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                "enabled_account_ids": enabled_ids,
                "enabled_accounts_error": enabled_accounts_error,
                "auto_loop_default": AUTO_LOOP_DEFAULT,
                "loop_interval_seconds": LOOP_INTERVAL_SECONDS,
                "paper_execution_entry_path": PAPER_EXECUTION_ENTRY_PATH,
                "pending_entry_loop_interval_seconds": pending_status["pending_entry_loop_interval_seconds"],
                "pending_entry_max_attempts": pending_status["pending_entry_max_attempts"],
                "pending_entries_count": pending_status["pending_entries_count"],
                "pending_entries": pending_status["pending_entries"],
                "last_pending_entry_loop_at": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("timestamp"),
                "last_pending_entry_loop_processed": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("processed", 0),
                "last_pending_entry_loop_fills": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("fills", 0),
                "last_pending_entry_loop_pending": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("pending", 0),
                "last_pending_entry_loop_cancelled": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("cancelled", 0),
                "last_pending_entry_loop_blocked": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("blocked", 0),
                "last_pending_entry_loop_errors": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("errors", 0),
                "last_pending_entry_loop_results": state.LAST_PENDING_ENTRY_LOOP_RESULT.get("results", []),
                "maintenance_loop_interval_seconds": MAINTENANCE_LOOP_INTERVAL_SECONDS,
                "last_maintenance_loop_at": state.LAST_MAINTENANCE_LOOP_RESULT.get("timestamp"),
                "last_maintenance_loop_checked": state.LAST_MAINTENANCE_LOOP_RESULT.get("checked", 0),
                "last_maintenance_loop_actions_triggered": state.LAST_MAINTENANCE_LOOP_RESULT.get("actions_triggered", 0),
                "last_maintenance_loop_no_action": state.LAST_MAINTENANCE_LOOP_RESULT.get("no_action", 0),
                "last_maintenance_loop_blocked": state.LAST_MAINTENANCE_LOOP_RESULT.get("blocked", 0),
                "last_maintenance_loop_errors": state.LAST_MAINTENANCE_LOOP_RESULT.get("errors", 0),
                "last_maintenance_loop_results": state.LAST_MAINTENANCE_LOOP_RESULT.get("results", []),
                "pending_exit_loop_interval_seconds": PENDING_EXIT_LOOP_INTERVAL_SECONDS,
                "pending_exit_orders_count": len(state.PENDING_EXIT_ORDERS),
                "last_pending_exit_loop_at": state.LAST_PENDING_EXIT_LOOP_RESULT.get("timestamp"),
                "last_pending_exit_loop_processed": state.LAST_PENDING_EXIT_LOOP_RESULT.get("processed", 0),
                "last_pending_exit_loop_filled": state.LAST_PENDING_EXIT_LOOP_RESULT.get("filled", 0),
                "last_pending_exit_loop_pending": state.LAST_PENDING_EXIT_LOOP_RESULT.get("pending", 0),
                "last_pending_exit_loop_forced_market": state.LAST_PENDING_EXIT_LOOP_RESULT.get("forced_market", 0),
                "last_pending_exit_loop_errors": state.LAST_PENDING_EXIT_LOOP_RESULT.get("errors", 0),
                "last_pending_exit_loop_results": state.LAST_PENDING_EXIT_LOOP_RESULT.get("results", []),
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)

    def do_POST(self):
        if self.path == "/controls/auto-loop":
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

            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                self._send_json({
                    "ok": False,
                    "error": "invalid_enabled_flag",
                    "required": {"enabled": "boolean"},
                }, status=400)
                return

            state.AUTO_LOOP_ENABLED_STATE = enabled
            enabled_ids, enabled_accounts_error = enabled_account_ids(ACCOUNT_ID)

            self._send_json({
                "ok": True,
                "auto_loop_enabled": state.AUTO_LOOP_ENABLED_STATE,
                "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                "enabled_account_ids": enabled_ids,
                "enabled_accounts_error": enabled_accounts_error,
                "timestamp": iso_now(),
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
                    "details": str(e),
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
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
