from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from threading import Thread
import json

from config import APP_ENV, PORT, SERVICE_NAME
from execution import apply_execution_report
from guardian_state import (
    evaluate_and_refresh_guardian_state,
    fetch_guardian_status,
    set_manual_halt,
)
from guards import compute_entry_guard_check, compute_maintenance_guard_check
from loops import mark_to_market_loop
from market_data import refresh_mark_to_market
from orders import fetch_all_open_orders, reprice_protective_order, mark_order_open, ensure_entry_order, cancel_entry_order, fetch_pending_entry_orders
from position_events import fetch_position_events
from reconciliation import (
    ensure_reconciliation_state,
    fetch_reconciliation_state,
    update_reconciliation_state,
)
from positions import fetch_all_open_positions, fetch_open_position_for_api
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
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "env": APP_ENV,
                "timestamp": iso_now(),
            })
            return

        if self.path.startswith("/status"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)
                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id,
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    **status,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path.startswith("/position/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])
                symbol = query.get("symbol", [None])[0]

                if not symbol:
                    self._send_json({
                        "ok": False,
                        "error": "missing_parameters",
                        "required": ["symbol"],
                    }, status=400)
                    return

                position = fetch_open_position_for_api(account_id, symbol.upper())

                if not position:
                    self._send_json({
                        "ok": False,
                        "error": "open_position_not_found",
                        "account_id": account_id,
                        "symbol": symbol.upper(),
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    "position": position,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path.startswith("/reconciliation/status"):
            query = parse_qs(urlparse(self.path).query)

            try:
                account_id = int(query.get("account_id", ["1"])[0])
                state = fetch_reconciliation_state(account_id)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "state": state,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "reconciliation_status_fetch_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path.startswith("/positions/events"):
            query = parse_qs(urlparse(self.path).query)

            try:
                account_id = int(query.get("account_id", ["1"])[0])
                position_id_raw = query.get("position_id", [None])[0]
                position_id = (
                    int(position_id_raw)
                    if position_id_raw is not None
                    else None
                )

                items = fetch_position_events(
                    account_id=account_id,
                    position_id=position_id,
                )

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "position_id": position_id,
                    "count": len(items),
                    "items": items,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "position_events_fetch_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path.startswith("/positions/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                positions = fetch_all_open_positions(account_id)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "positions": positions,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path.startswith("/orders/pending-entries"):
            query = parse_qs(urlparse(self.path).query)

            try:
                account_id = int(query.get("account_id", ["1"])[0])
                items = fetch_pending_entry_orders(account_id)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "count": len(items),
                    "items": items,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "pending_entry_orders_fetch_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path.startswith("/orders/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                payload = fetch_all_open_orders(account_id)
                self._send_json(payload)
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

    def do_POST(self):
        if self.path == "/guard/check-entry":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))
                symbol = payload.get("symbol")
                ignore_pending_order = bool(payload.get("ignore_pending_order", False))

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)

                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id,
                    }, status=404)
                    return

                result = compute_entry_guard_check(
                    status,
                    symbol=symbol,
                    ignore_pending_order=ignore_pending_order,
                )

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "symbol": symbol.upper() if symbol else None,
                    "ignore_pending_order": ignore_pending_order,
                    **result,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/guard/check-maintenance":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))
                symbol = payload.get("symbol")

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)

                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id,
                    }, status=404)
                    return

                result = compute_maintenance_guard_check(status, symbol=symbol)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "symbol": symbol.upper() if symbol else None,
                    **result,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/guard/manual-halt":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))

                account_id = int(payload["account_id"])
                enabled = bool(payload["enabled"])
                reason_code = payload.get("reason_code", "MANUAL_HALT")

                set_manual_halt(account_id, enabled, reason_code)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "manual_halt": enabled,
                    "reason_code": reason_code,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/orders/entry/ensure":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                order_id = ensure_entry_order(
                    account_id=int(payload["account_id"]),
                    symbol=str(payload["symbol"]),
                    position_side=str(payload["position_side"]).lower(),
                    order_type=str(payload["order_type"]).lower(),
                    requested_price=(
                        float(payload["requested_price"])
                        if payload.get("requested_price") is not None
                        else None
                    ),
                    requested_size=float(payload["requested_size"]),
                    order_id=(
                        int(payload["order_id"])
                        if payload.get("order_id") is not None
                        else None
                    ),
                    execution_context=payload.get("execution_context"),
                    retry_attempt=int(payload.get("retry_attempt", 0)),
                    max_retry_attempts=(
                        int(payload["max_retry_attempts"])
                        if payload.get("max_retry_attempts") is not None
                        else None
                    ),
                    originating_cycle_id=payload.get("originating_cycle_id"),
                )

                self._send_json({
                    "ok": True,
                    "order_id": order_id,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "entry_order_ensure_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path == "/orders/mark-open":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                order_id = int(payload["order_id"])
                mark_order_open(order_id)

                self._send_json({
                    "ok": True,
                    "order_id": order_id,
                    "status": "open",
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "order_mark_open_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path == "/reconciliation/update":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                state = update_reconciliation_state(
                    account_id=int(payload["account_id"]),
                    status=str(payload["status"]).lower(),
                    provider=str(payload.get("provider", "blofin")).lower(),
                    account_match=payload.get("account_match"),
                    positions_match=payload.get("positions_match"),
                    orders_match=payload.get("orders_match"),
                    mismatch_count=int(payload.get("mismatch_count", 0)),
                    details=payload.get("details"),
                )

                self._send_json({
                    "ok": True,
                    "state": state,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "reconciliation_update_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path == "/orders/entry/cancel":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                result = cancel_entry_order(
                    account_id=int(payload["account_id"]),
                    order_id=int(payload["order_id"]),
                )

                if result is None:
                    self._send_json({
                        "ok": False,
                        "error": "active_entry_order_not_found",
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    **result,
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "entry_order_cancel_failed",
                    "details": str(e),
                }, status=400)
                return

        if self.path == "/execution/apply":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))

                result = apply_execution_report(payload)

                status_code = 200 if result.get("ok") else 400
                self._send_json(result, status=status_code)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/mark-to-market/refresh":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))

                result = refresh_mark_to_market(account_id)
                self._send_json(result)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/orders/reprice-protective":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload["account_id"])
                order_id = int(payload["order_id"])
                new_price = float(payload["new_price"])

                updated = reprice_protective_order(account_id, order_id, new_price)
                if not updated:
                    self._send_json({
                        "ok": False,
                        "error": "protective_order_not_found_or_not_open",
                        "account_id": account_id,
                        "order_id": order_id,
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    **updated,
                })
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
    loop_thread = Thread(target=mark_to_market_loop, daemon=True)
    loop_thread.start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
