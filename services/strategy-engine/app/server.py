import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from analyzer import analyze_symbol
from config import OBSERVE_SCORE_THRESHOLD, PORT, SERVICE_NAME, STRICT_SCORE_THRESHOLD, TRADE_SCORE_THRESHOLD
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
                "timestamp": iso_now(),
                "strict_score_threshold_legacy": STRICT_SCORE_THRESHOLD,
                "trade_score_threshold": TRADE_SCORE_THRESHOLD,
                "observe_score_threshold": OBSERVE_SCORE_THRESHOLD
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/analyze":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                symbol = payload.get("symbol")
                if not symbol:
                    self._send_json({
                        "ok": False,
                        "error": "missing_symbol"
                    }, status=400)
                    return

                result = analyze_symbol(symbol.upper())
                self._send_json(result, status=200 if result.get("ok") else 400)
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


def run():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
