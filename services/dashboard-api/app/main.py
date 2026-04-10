from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
import json
import os

import requests


SERVICE_NAME = "dashboard-api"
PORT = int(os.getenv("PORT", "8080"))

EVALUATOR_BASE_URL = os.getenv("EVALUATOR_BASE_URL", "http://evaluator:8080")
SCHEDULER_BASE_URL = os.getenv("SCHEDULER_BASE_URL", "http://scheduler:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
CANDIDATE_FILTER_BASE_URL = os.getenv("CANDIDATE_FILTER_BASE_URL", "http://candidate-filter:8080")
STRATEGY_ENGINE_BASE_URL = os.getenv("STRATEGY_ENGINE_BASE_URL", "http://strategy-engine:8080")
RISK_ENGINE_BASE_URL = os.getenv("RISK_ENGINE_BASE_URL", "http://risk-engine:8080")
PAPER_EXECUTION_BASE_URL = os.getenv("PAPER_EXECUTION_BASE_URL", "http://paper-execution:8080")
API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_json(url: str, params: dict | None = None, timeout: int = 15):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        payload = r.json()
        return payload, r.status_code, None
    except Exception as e:
        return None, None, str(e)


def service_health_check(name: str, base_url: str):
    payload, status_code, error = get_json(f"{base_url}/health", timeout=5)

    if error:
        return {
            "service": name,
            "ok": False,
            "reachable": False,
            "status_code": None,
            "error": error,
        }

    return {
        "service": name,
        "ok": bool(payload.get("ok", False)),
        "reachable": True,
        "status_code": status_code,
        "payload": payload,
    }


def get_market_session_banner():
    now_utc = datetime.now(timezone.utc)

    sessions = [
        {
            "name": "Asia",
            "open_hour_utc": 0,   # approx Tokyo open window marker
            "close_hour_utc": 9,
        },
        {
            "name": "UK",
            "open_hour_utc": 8,
            "close_hour_utc": 16,
        },
        {
            "name": "US",
            "open_hour_utc": 13,
            "close_hour_utc": 21,
        },
    ]

    active_session = None
    next_session = None
    min_delta = None

    for session in sessions:
        open_dt = now_utc.replace(
            hour=session["open_hour_utc"], minute=0, second=0, microsecond=0
        )
        close_dt = now_utc.replace(
            hour=session["close_hour_utc"], minute=0, second=0, microsecond=0
        )

        if close_dt <= open_dt:
            close_dt += timedelta(days=1)

        if open_dt <= now_utc < close_dt:
            active_session = session["name"]

        future_open = open_dt
        if future_open <= now_utc:
            future_open += timedelta(days=1)

        delta = future_open - now_utc
        if min_delta is None or delta < min_delta:
            min_delta = delta
            next_session = {
                "name": session["name"],
                "opens_at_utc": future_open.isoformat().replace("+00:00", "Z"),
                "seconds_until_open": int(delta.total_seconds()),
            }

    return {
        "ok": True,
        "generated_at": iso_now(),
        "current_utc_time": now_utc.isoformat().replace("+00:00", "Z"),
        "active_session": active_session,
        "next_session": next_session,
    }


def get_bootstrap_overview(account_id: int):
    overview, overview_status, overview_error = get_json(
        f"{EVALUATOR_BASE_URL}/overview",
        params={"account_id": account_id},
        timeout=20,
    )
    performance, performance_status, performance_error = get_json(
        f"{EVALUATOR_BASE_URL}/performance/summary",
        params={"account_id": account_id},
        timeout=20,
    )
    cycle_latest, cycle_status, cycle_error = get_json(
        f"{EVALUATOR_BASE_URL}/cycles/latest",
        params={"account_id": account_id},
        timeout=20,
    )
    decision_funnel, funnel_status, funnel_error = get_json(
        f"{EVALUATOR_BASE_URL}/analytics/decision-funnel",
        params={"account_id": account_id},
        timeout=20,
    )
    market_banner = get_market_session_banner()

    errors = []
    if overview_error or overview_status != 200:
        errors.append({
            "source": "overview",
            "error": overview_error or overview,
        })
    if performance_error or performance_status != 200:
        errors.append({
            "source": "performance_summary",
            "error": performance_error or performance,
        })
    if cycle_error or cycle_status != 200:
        errors.append({
            "source": "cycles_latest",
            "error": cycle_error or cycle_latest,
        })
    if funnel_error or funnel_status != 200:
        errors.append({
            "source": "decision_funnel",
            "error": funnel_error or decision_funnel,
        })

    account_status = overview.get("account_status", {}) if isinstance(overview, dict) else {}
    trading_enabled = account_status.get("trading_enabled", True)
    manual_halt = account_status.get("manual_halt", False)
    daily_kill_switch = account_status.get("daily_kill_switch", False)
    weekly_kill_switch = account_status.get("weekly_kill_switch", False)

    disable_reasons = []
    if not trading_enabled:
        disable_reasons.append("TRADING_DISABLED")
    if manual_halt:
        disable_reasons.append("MANUAL_HALT")
    if daily_kill_switch:
        disable_reasons.append("DAILY_KILL_SWITCH")
    if weekly_kill_switch:
        disable_reasons.append("WEEKLY_KILL_SWITCH")

    trading_banner = {
        "trading_disabled": len(disable_reasons) > 0,
        "reason_codes": disable_reasons,
        "message": "Trading Disabled" if disable_reasons else "Trading Enabled",
        "maintenance_remains_active": True,
    }

    return {
        "ok": len(errors) == 0,
        "account_id": account_id,
        "generated_at": iso_now(),
        "market_banner": market_banner,
        "trading_banner": trading_banner,
        "overview": overview if isinstance(overview, dict) else None,
        "performance_summary": performance if isinstance(performance, dict) else None,
        "latest_cycle": cycle_latest if isinstance(cycle_latest, dict) else None,
        "decision_funnel": decision_funnel if isinstance(decision_funnel, dict) else None,
        "errors": errors,
    }


def get_system_health():
    services = [
        ("evaluator", EVALUATOR_BASE_URL),
        ("scheduler", SCHEDULER_BASE_URL),
        ("trade-guardian", TRADE_GUARDIAN_BASE_URL),
        ("candidate-filter", CANDIDATE_FILTER_BASE_URL),
        ("strategy-engine", STRATEGY_ENGINE_BASE_URL),
        ("risk-engine", RISK_ENGINE_BASE_URL),
        ("paper-execution", PAPER_EXECUTION_BASE_URL),
        ("api-gateway", API_GATEWAY_BASE_URL),
        ("data-hub", DATA_HUB_BASE_URL),
    ]

    results = [service_health_check(name, base_url) for name, base_url in services]

    total = len(results)
    healthy = sum(1 for x in results if x.get("ok"))
    unhealthy = total - healthy

    return {
        "ok": unhealthy == 0,
        "generated_at": iso_now(),
        "summary": {
            "total_services": total,
            "healthy_services": healthy,
            "unhealthy_services": unhealthy,
        },
        "services": results,
    }


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

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()