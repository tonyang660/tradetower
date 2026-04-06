from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os


SERVICE_NAME = "llm-service"
PORT = int(os.getenv("PORT", "8080"))


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_stubbed_output(role: str, candidate_packet: dict):
    symbol = candidate_packet.get("symbol", "UNKNOWN")
    score = float(candidate_packet.get("candidate_score", 50))

    # deterministic stub behavior for development
    if score >= 80:
        decision = "long"
        confidence = 80 if role != "strategy" else 75
    elif score >= 60:
        decision = "no_trade" if role == "strategy" else "long"
        confidence = 68
    else:
        decision = "no_trade"
        confidence = 65 if role != "structure" else 55

    return {
        "role": role,
        "decision": decision,
        "confidence": confidence,
        "thesis_summary": f"{role} analysis for {symbol}: score={score}",
        "reason_tags": [f"{role.upper()}_VIEW"],
        "entry_preference": "pullback" if decision == "long" else "none",
        "stop_loss_hint": "below recent swing low" if decision == "long" else "none",
        "tp1_hint": "first resistance" if decision == "long" else "none",
        "tp2_hint": "second resistance" if decision == "long" else "none",
        "tp3_hint": "trend extension" if decision == "long" else "none",
        "leverage_hint": 10.0
    }


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
                "timestamp": iso_now()
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found"
        }, status=404)

    def do_POST(self):
        if self.path == "/infer":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))

                role = payload.get("role")
                candidate_packet = payload.get("candidate_packet", {})

                if role not in ("regime", "structure", "strategy"):
                    self._send_json({
                        "ok": False,
                        "error": "invalid_role"
                    }, status=400)
                    return

                output = build_stubbed_output(role, candidate_packet)
                self._send_json({
                    "ok": True,
                    "output": output
                })
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
            "error": "not_found"
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()