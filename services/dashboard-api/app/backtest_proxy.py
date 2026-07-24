from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any



BACKTEST_ENGINE_BASE_URL = os.getenv("BACKTEST_ENGINE_BASE_URL", "http://backtest-engine:8080").rstrip("/")


def _read_response(response) -> tuple[dict[str, Any], int]:
    raw = response.read().decode("utf-8")
    try:
        return json.loads(raw), int(response.status)
    except Exception:
        return {"ok": False, "error": "invalid_json_from_backtest_engine", "raw": raw[:500]}, 502


def _proxy_get(path: str, query: str = "") -> tuple[dict[str, Any], int]:
    url = f"{BACKTEST_ENGINE_BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return _read_response(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return json.loads(raw), exc.code
        except Exception:
            return {"ok": False, "error": "backtest_engine_http_error", "status": exc.code, "raw": raw[:500]}, exc.code
    except Exception as exc:
        return {"ok": False, "error": "backtest_engine_unreachable", "details": str(exc), "url": url}, 502


def _proxy_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    url = f"{BACKTEST_ENGINE_BASE_URL}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as response:
            return _read_response(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return json.loads(raw), exc.code
        except Exception:
            return {"ok": False, "error": "backtest_engine_http_error", "status": exc.code, "raw": raw[:500]}, exc.code
    except Exception as exc:
        return {"ok": False, "error": "backtest_engine_unreachable", "details": str(exc), "url": url}, 502


def handle_backtest_get(handler, parsed) -> bool:
    query = parsed.query

    route_map = {
        "/backtest/strategies": "/strategies",
        "/backtest/strategy-detail": "/strategies/detail",
        "/backtest/runs": "/backtests/runs",
        "/backtest/run-detail": "/backtests/run",
        "/backtest/summary": "/backtests/run/summary",
        "/backtest/trades": "/backtests/run/trades",
        "/backtest/equity-curve": "/backtests/run/equity-curve",
        "/backtest/metrics": "/backtests/run/metrics",
        "/backtest/logs": "/backtests/run/logs",
        "/backtest/result-bundle": "/backtests/run/result-bundle",
        "/backtest/progress": "/backtests/progress",
    }

    target = route_map.get(parsed.path)
    if not target:
        return False

    payload, status = _proxy_get(target, query)
    handler._send_json(payload, status=status)
    return True


def handle_backtest_post(handler, parsed, payload: dict[str, Any]) -> bool:
    route_map = {
        "/backtest/run": "/backtests/run",
        "/backtest/start": "/backtests/start",
        "/backtest/cancel": "/backtests/cancel",
        "/backtest/validate-run": "/strategies/validate-run",
    }

    target = route_map.get(parsed.path)
    if not target:
        return False

    result, status = _proxy_post(target, payload)
    handler._send_json(result, status=status)
    return True
