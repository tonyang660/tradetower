
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import PORT, SERVICE_NAME
from result_api import (
    fetch_equity_curve,
    fetch_logs,
    fetch_metrics,
    fetch_orders,
    fetch_positions,
    fetch_result_bundle,
    fetch_run_summary,
    fetch_trades,
)
from runner import list_runs, run_backtest, run_detail
from strategies.registry import get_strategy_detail, list_strategies
from strategies.validation import validate_strategy_payload


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    content_length = int(handler.headers.get("Content-Length", "0"))
    if content_length <= 0:
        return {}
    raw = handler.rfile.read(content_length)
    return json.loads(raw.decode("utf-8"))


def _query_int(query: dict, key: str, default: int) -> int:
    try:
        return int(query.get(key, [str(default)])[0])
    except Exception:
        return default


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run_id_or_error(self, query: dict) -> int | None:
        run_id = _query_int(query, "run_id", 0)
        if run_id <= 0:
            self._send_json({"ok": False, "error": "invalid_run_id"}, status=400)
            return None
        return run_id

    def _paged_result(self, query: dict, fetcher, key: str, default_limit: int = 200):
        run_id = self._run_id_or_error(query)
        if run_id is None:
            return

        limit = _query_int(query, "limit", default_limit)
        offset = _query_int(query, "offset", 0)

        try:
            result = fetcher(run_id, limit=limit, offset=offset)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc), "run_id": run_id}, status=500)
            return

        self._send_json({
            "ok": True,
            "run_id": run_id,
            key: result["rows"],
            "total": result["total"],
            "count": result["count"],
            "limit": result["limit"],
            "offset": result["offset"],
            "has_more": result["has_more"],
        })

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "phase": "14E",
                "role": "event_driven_backtest_engine_with_result_api",
                "result_endpoints": [
                    "/backtests/run/summary",
                    "/backtests/run/trades",
                    "/backtests/run/orders",
                    "/backtests/run/positions",
                    "/backtests/run/equity-curve",
                    "/backtests/run/metrics",
                    "/backtests/run/logs",
                    "/backtests/run/result-bundle",
                ],
            })
            return

        if parsed.path == "/strategies/validate":
            strategy_name = query.get("strategy_name", ["tradetower_baseline_v1"])[0]
            timeframes = query.get("timeframes", [])
            cycle_timeframe = query.get("cycle_timeframe", [None])[0]
            strict = query.get("strict", ["false"])[0].lower() in {"1", "true", "yes"}
            payload = {
                "strategy_name": strategy_name,
                "timeframes": timeframes,
                "cycle_timeframe": cycle_timeframe,
                "strategy_validation_strict_timeframes": strict,
            }
            validation = validate_strategy_payload(payload)
            self._send_json({"ok": validation.get("valid", False), "validation": validation}, status=200 if validation.get("valid") else 400)
            return

        if parsed.path == "/strategies/detail":
            strategy_name = query.get("strategy_name", ["tradetower_baseline_v1"])[0]
            try:
                self._send_json({"ok": True, "strategy": get_strategy_detail(strategy_name)})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=404)
            return

        if parsed.path == "/strategies":
            self._send_json({
                "ok": True,
                "strategies": list_strategies(),
            })
            return

        if parsed.path == "/backtests/runs":
            limit = _query_int(query, "limit", 20)
            self._send_json({
                "ok": True,
                "runs": list_runs(limit=max(1, min(limit, 100))),
            })
            return

        # Legacy full payload endpoint kept for compatibility.
        if parsed.path == "/strategies/validate-run":
            try:
                payload = _read_json(self)
            except Exception:
                self._send_json({"ok": False, "error": "invalid_json"}, status=400)
                return
            validation = validate_strategy_payload(payload)
            self._send_json({"ok": validation.get("valid", False), "validation": validation}, status=200 if validation.get("valid") else 400)
            return

        if parsed.path == "/backtests/run":
            run_id = self._run_id_or_error(query)
            if run_id is None:
                return

            detail = run_detail(run_id)
            if not detail:
                self._send_json({"ok": False, "error": "run_not_found", "run_id": run_id}, status=404)
                return

            self._send_json({"ok": True, **detail})
            return

        if parsed.path == "/backtests/run/summary":
            run_id = self._run_id_or_error(query)
            if run_id is None:
                return

            summary = fetch_run_summary(run_id)
            if not summary:
                self._send_json({"ok": False, "error": "run_not_found", "run_id": run_id}, status=404)
                return

            self._send_json({"ok": True, "run_id": run_id, "run": summary})
            return

        if parsed.path == "/backtests/run/trades":
            self._paged_result(query, fetch_trades, "trades", default_limit=200)
            return

        if parsed.path == "/backtests/run/orders":
            self._paged_result(query, fetch_orders, "orders", default_limit=200)
            return

        if parsed.path == "/backtests/run/positions":
            self._paged_result(query, fetch_positions, "positions", default_limit=200)
            return

        if parsed.path == "/backtests/run/equity-curve":
            self._paged_result(query, fetch_equity_curve, "equity_curve", default_limit=1000)
            return

        if parsed.path == "/backtests/run/metrics":
            self._paged_result(query, fetch_metrics, "metrics", default_limit=500)
            return

        if parsed.path == "/backtests/run/logs":
            self._paged_result(query, fetch_logs, "logs", default_limit=500)
            return

        if parsed.path == "/backtests/run/result-bundle":
            run_id = self._run_id_or_error(query)
            if run_id is None:
                return

            bundle = fetch_result_bundle(run_id)
            if not bundle:
                self._send_json({"ok": False, "error": "run_not_found", "run_id": run_id}, status=404)
                return

            self._send_json({"ok": True, "run_id": run_id, **bundle})
            return

        self._send_json({"ok": False, "error": "not_found", "path": parsed.path}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/backtests/run":
            try:
                payload = _read_json(self)
            except Exception:
                self._send_json({"ok": False, "error": "invalid_json"}, status=400)
                return

            result = run_backtest(payload)
            self._send_json(result, status=200 if result.get("ok") else 500)
            return

        self._send_json({"ok": False, "error": "not_found", "path": parsed.path}, status=404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
