from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import json

from config import SERVICE_NAME, PORT
from cycles import get_cycle_history, get_latest_cycle
from decision import get_decision_funnel
from equity import get_equity_history
from ingest import apply_pending_entry_event, ingest_cycle_summary, ingest_equity_snapshot
from orders import get_executed_orders, get_open_orders
from overview import build_overview
from performance import (
    get_calendar_performance,
    get_directional_breakdown,
    get_drawdown_series,
    get_hourly_performance,
    get_monthly_summary,
    get_performance_pnl_series,
    get_performance_summary,
    get_performance_summary_extended,
    get_session_performance,
    get_weekday_performance,
)
from positions import get_recent_closed_positions
from analytics import (
    get_strategy_analytics_exit_outcomes,
    get_strategy_analytics_fee_pressure,
    get_strategy_analytics_holding_times,
    get_strategy_analytics_summary,
    get_strategy_analytics_score_buckets,
    get_strategy_analytics_symbols
    
)
from time_utils import iso_now
from trade_guardian_client import (
    fetch_trade_guardian_open_positions,
    refresh_trade_guardian_mark_to_market,
)
from position_lifecycle_routes import handle_position_lifecycle_get
from tp_leg_analytics_routes import handle_tp_leg_analytics_get
from stop_management_analytics_routes import handle_stop_management_analytics_get


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        
        if handle_position_lifecycle_get(self, parsed): return
        if handle_tp_leg_analytics_get(self, parsed):return
        if handle_stop_management_analytics_get(self, parsed):return

        if parsed.path == "/overview":
            account_id = int(query.get("account_id", ["1"])[0])
            payload, error = build_overview(account_id)
            if error:
                self._send_json({
                    "ok": False,
                    "error": error,
                }, status=500)
                return
            self._send_json(payload)
            return

        if parsed.path == "/positions/open":
            account_id = int(query.get("account_id", ["1"])[0])
            refresh = query.get("refresh", ["true"])[0].lower() == "true"

            if refresh:
                mtm_payload, error = refresh_trade_guardian_mark_to_market(account_id)
                if error:
                    self._send_json({
                        "ok": False,
                        "error": error,
                    }, status=500)
                    return

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "count": len(mtm_payload.get("positions", [])),
                    "items": mtm_payload.get("positions", []),
                    "account_status": mtm_payload.get("account_status"),
                    "pricing_errors": mtm_payload.get("pricing_errors", []),
                })
                return

            positions, error = fetch_trade_guardian_open_positions(account_id)
            if error:
                self._send_json({
                    "ok": False,
                    "error": error,
                }, status=500)
                return

            self._send_json({
                "ok": True,
                "account_id": account_id,
                "count": len(positions),
                "items": positions,
            })
            return

        if parsed.path == "/positions/recent":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["20"])[0])
            self._send_json(get_recent_closed_positions(account_id, limit))
            return

        if parsed.path == "/equity/history":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["100"])[0])
            self._send_json(get_equity_history(account_id, limit))
            return

        if parsed.path == "/cycles/latest":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_latest_cycle(account_id))
            return

        if parsed.path == "/cycles/history":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["50"])[0])
            self._send_json(get_cycle_history(account_id, limit))
            return

        if parsed.path == "/performance/summary":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_performance_summary(account_id))
            return

        if parsed.path == "/performance/pnl-series":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["200"])[0])
            self._send_json(get_performance_pnl_series(account_id, limit))
            return

        if parsed.path == "/analytics/decision-funnel":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_decision_funnel(account_id))
            return

        if parsed.path == "/orders/open":
            account_id = int(query.get("account_id", ["1"])[0])
            payload, status = get_open_orders(account_id)
            self._send_json(payload, status=status)
            return

        if parsed.path == "/orders/executed":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["50"])[0])
            self._send_json(get_executed_orders(account_id, limit))
            return

        if parsed.path == "/performance/summary-extended":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_performance_summary_extended(account_id))
            return

        if parsed.path == "/performance/drawdown-series":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["1000"])[0])
            self._send_json(get_drawdown_series(account_id, limit))
            return

        if parsed.path == "/performance/directional-breakdown":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_directional_breakdown(account_id))
            return

        if parsed.path == "/performance/hourly":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_hourly_performance(account_id))
            return

        if parsed.path == "/performance/weekday":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_weekday_performance(account_id))
            return

        if parsed.path == "/performance/session":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_session_performance(account_id))
            return

        if parsed.path == "/performance/calendar":
            account_id = int(query.get("account_id", ["1"])[0])
            limit_days = int(query.get("limit_days", ["120"])[0])
            self._send_json(get_calendar_performance(account_id, limit_days))
            return

        if parsed.path == "/performance/monthly-summary":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_monthly_summary(account_id))
            return

        if parsed.path == "/strategy-analytics/summary":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_summary(account_id))
            return

        if parsed.path == "/strategy-analytics/score-buckets":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_score_buckets(account_id))
            return

        if parsed.path == "/strategy-analytics/symbols":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_symbols(account_id))
            return

        if parsed.path == "/strategy-analytics/holding-times":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_holding_times(account_id))
            return

        if parsed.path == "/strategy-analytics/exit-outcomes":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_exit_outcomes(account_id))
            return

        if parsed.path == "/strategy-analytics/fee-pressure":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_strategy_analytics_fee_pressure(account_id))
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)

    def do_POST(self):
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

        if self.path == "/ingest/cycle-summary":
            try:
                result = ingest_cycle_summary(payload)
                self._send_json(result)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "cycle_ingest_failed",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/ingest/equity-snapshot":
            try:
                result = ingest_equity_snapshot(payload)
                self._send_json(result)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "equity_ingest_failed",
                    "details": str(e),
                }, status=500)
                return

        if self.path == "/ingest/pending-entry-event":
            try:
                result = apply_pending_entry_event(payload)
                self._send_json(result, status=200 if result.get("ok") else 400)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "pending_entry_event_ingest_failed",
                    "details": str(e),
                }, status=500)
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
