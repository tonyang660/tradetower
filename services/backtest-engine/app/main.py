import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import PORT, SERVICE_NAME
from runner import list_runs, run_backtest, run_detail


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": SERVICE_NAME, "phase": "14A", "role": "event_driven_backtest_engine_foundation"})
            return
        if parsed.path == "/backtests/runs":
            query = parse_qs(parsed.query)
            limit = max(1, min(int(query.get("limit", ["20"])[0]), 100))
            self.send_json({"ok": True, "runs": list_runs(limit)})
            return
        if parsed.path == "/backtests/run":
            query = parse_qs(parsed.query)
            run_id = int(query.get("run_id", ["0"])[0])
            detail = run_detail(run_id)
            self.send_json({"ok": True, **detail} if detail else {"ok": False, "error": "run_not_found", "run_id": run_id}, 200 if detail else 404)
            return
        self.send_json({"ok": False, "error": "not_found", "path": parsed.path}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/backtests/run":
            try:
                payload = read_json(self)
            except Exception:
                self.send_json({"ok": False, "error": "invalid_json"}, 400)
                return
            result = run_backtest(payload)
            self.send_json(result, 200 if result.get("ok") else 500)
            return
        self.send_json({"ok": False, "error": "not_found", "path": parsed.path}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
