
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import PORT, SERVICE_NAME
from datasets.binance_downloader import run_download_job
from datasets.parquet_store import convert_dataset_to_parquet, read_candles
from datasets.local_dataset import dataset_assets_summary, validate_local_dataset_request
from datasets.quality_scanner import quality_summary, scan_dataset_quality
from datasets.registry import (
    create_download_job,
    dataset_defaults,
    get_dataset,
    list_dataset_sources,
    list_datasets,
    register_dataset,
)
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

        if parsed.path == "/datasets/feed-preflight":
            dataset_id = _query_int(query, "dataset_id", 0)
            symbols = query.get("symbols", [])
            timeframes = query.get("timeframes", [])
            start_time = query.get("start_time", [None])[0]
            end_time = query.get("end_time", [None])[0]
            if dataset_id <= 0:
                self._send_json({"ok": False, "error": "invalid_dataset_id"}, status=400)
                return
            validation = validate_local_dataset_request(dataset_id=dataset_id, symbols=symbols, timeframes=timeframes, start_time=start_time, end_time=end_time)
            self._send_json({"ok": validation.get("ok", False), "validation": validation}, status=200 if validation.get("ok") else 400)
            return

        if parsed.path == "/datasets/assets-summary":
            dataset_id = _query_int(query, "dataset_id", 0)
            if dataset_id <= 0:
                self._send_json({"ok": False, "error": "invalid_dataset_id"}, status=400)
                return
            self._send_json({"ok": True, "dataset_id": dataset_id, "assets": dataset_assets_summary(dataset_id)})
            return

        if parsed.path == "/datasets/quality-summary":
            dataset_id = _query_int(query, "dataset_id", 0)
            if dataset_id <= 0:
                self._send_json({"ok": False, "error": "invalid_dataset_id"}, status=400)
                return
            self._send_json(quality_summary(dataset_id))
            return

        if parsed.path == "/datasets/candles":
            dataset_id = _query_int(query, "dataset_id", 0)
            symbol = query.get("symbol", [""])[0]
            timeframe = query.get("timeframe", [""])[0]
            limit = _query_int(query, "limit", 100)
            if not symbol or not timeframe:
                self._send_json({"ok": False, "error": "symbol_and_timeframe_required"}, status=400)
                return
            candles = read_candles(symbol=symbol, timeframe=timeframe, dataset_id=dataset_id or None, limit=limit)
            self._send_json({"ok": True, "dataset_id": dataset_id or None, "symbol": symbol, "timeframe": timeframe, "count": len(candles), "candles": candles})
            return

        if parsed.path == "/datasets/defaults":
            self._send_json({"ok": True, "defaults": dataset_defaults()})
            return

        if parsed.path == "/datasets/sources":
            self._send_json({"ok": True, "sources": list_dataset_sources()})
            return

        if parsed.path == "/datasets":
            limit = _query_int(query, "limit", 50)
            self._send_json({"ok": True, "datasets": list_datasets(limit=limit)})
            return

        if parsed.path == "/datasets/detail":
            dataset_id = _query_int(query, "dataset_id", 0)
            if dataset_id <= 0:
                self._send_json({"ok": False, "error": "invalid_dataset_id"}, status=400)
                return
            dataset = get_dataset(dataset_id)
            if not dataset:
                self._send_json({"ok": False, "error": "dataset_not_found", "dataset_id": dataset_id}, status=404)
                return
            self._send_json({"ok": True, "dataset": dataset})
            return

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

        if parsed.path == "/datasets/register":
            try:
                payload = _read_json(self)
                result = register_dataset(payload)
                self._send_json(result)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if parsed.path == "/datasets/scan-quality":
            try:
                payload = _read_json(self)
                dataset_id = int(payload.get("dataset_id"))
                result = scan_dataset_quality(dataset_id=dataset_id, symbols=payload.get("symbols"), timeframes=payload.get("timeframes"))
                self._send_json(result, status=200 if result.get("ok") else 500)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if parsed.path == "/datasets/convert-parquet":
            try:
                payload = _read_json(self)
                dataset_id = int(payload.get("dataset_id"))
                result = convert_dataset_to_parquet(dataset_id=dataset_id, symbols=payload.get("symbols"), timeframes=payload.get("timeframes"))
                self._send_json(result, status=200 if result.get("ok") else 500)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if parsed.path == "/datasets/download-binance":
            try:
                payload = _read_json(self)
                result = run_download_job(payload)
                self._send_json(result, status=200 if result.get("ok") else 500)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if parsed.path == "/datasets/download-jobs":
            try:
                payload = _read_json(self)
                result = create_download_job(payload)
                self._send_json(result)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

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
