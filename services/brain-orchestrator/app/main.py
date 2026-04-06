from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os

import requests


SERVICE_NAME = "brain-orchestrator"
PORT = int(os.getenv("PORT", "8080"))
LLM_SERVICE_BASE_URL = os.getenv("LLM_SERVICE_BASE_URL", "http://llm-service:8080")
ROLE_CONFIDENCE_THRESHOLD = int(os.getenv("ROLE_CONFIDENCE_THRESHOLD", "70"))

ROLES = ["regime", "structure", "strategy"]
VALID_DECISIONS = {"long", "short", "no_trade", "abstain"}


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_role_output(role_output: dict):
    required = [
        "role",
        "decision",
        "confidence",
        "thesis_summary",
        "reason_tags",
        "entry_preference",
        "stop_loss_hint",
        "tp1_hint",
        "tp2_hint",
        "tp3_hint",
        "leverage_hint",
    ]

    for key in required:
        if key not in role_output:
            return False, f"missing_field:{key}"

    if role_output["role"] not in ROLES:
        return False, "invalid_role"

    if role_output["decision"] not in VALID_DECISIONS:
        return False, "invalid_decision"

    try:
        confidence = int(role_output["confidence"])
    except Exception:
        return False, "invalid_confidence"

    if confidence < 0 or confidence > 100:
        return False, "invalid_confidence_range"

    try:
        lev = float(role_output["leverage_hint"])
    except Exception:
        return False, "invalid_leverage_hint"

    if lev < 5.0 or lev > 15.0:
        return False, "invalid_leverage_hint_range"

    if not isinstance(role_output["reason_tags"], list):
        return False, "invalid_reason_tags"

    return True, None


def call_llm_service(role: str, candidate_packet: dict):
    payload = {
        "role": role,
        "candidate_packet": candidate_packet
    }

    try:
        r = requests.post(
            f"{LLM_SERVICE_BASE_URL}/infer",
            json=payload,
            timeout=30
        )
        response = r.json()
    except Exception as e:
        return None, f"llm_service_unavailable:{str(e)}"

    if not response.get("ok"):
        return None, response.get("error", "llm_service_error")

    output = response.get("output")
    if not isinstance(output, dict):
        return None, "invalid_llm_output"

    valid, err = validate_role_output(output)
    if not valid:
        return None, err

    return output, None


def build_role_prompt_payload(role: str, candidate_packet: dict):
    # For now, the prompt construction is represented as structured payload assembly.
    # The future llm-service can convert this into a real prompt template.
    return {
        "role": role,
        "candidate_packet": candidate_packet,
        "prompt_version": "brain_v1"
    }


def consensus_decision(role_outputs: list[dict]):
    votes = [r["decision"] for r in role_outputs]
    non_abstain = [v for v in votes if v != "abstain"]

    if len(non_abstain) < 2:
        return {
            "decision": "no_trade",
            "consensus_score": 0.0,
            "reason": "INSUFFICIENT_NON_ABSTAINING_VOTES"
        }

    long_count = non_abstain.count("long")
    short_count = non_abstain.count("short")
    no_trade_count = non_abstain.count("no_trade")

    if no_trade_count >= 2:
        return {
            "decision": "no_trade",
            "consensus_score": 0.0,
            "reason": "NO_TRADE_MAJORITY"
        }

    if long_count >= 2 and short_count == 0:
        agreeing = [r for r in role_outputs if r["decision"] == "long"]
        avg_conf = sum(int(r["confidence"]) for r in agreeing) / len(agreeing)
        if avg_conf >= ROLE_CONFIDENCE_THRESHOLD:
            return {
                "decision": "long",
                "consensus_score": round(avg_conf / 100.0, 2),
                "reason": "LONG_MAJORITY"
            }
        return {
            "decision": "no_trade",
            "consensus_score": round(avg_conf / 100.0, 2),
            "reason": "LONG_MAJORITY_CONFIDENCE_TOO_LOW"
        }

    if short_count >= 2 and long_count == 0:
        agreeing = [r for r in role_outputs if r["decision"] == "short"]
        avg_conf = sum(int(r["confidence"]) for r in agreeing) / len(agreeing)
        if avg_conf >= ROLE_CONFIDENCE_THRESHOLD:
            return {
                "decision": "short",
                "consensus_score": round(avg_conf / 100.0, 2),
                "reason": "SHORT_MAJORITY"
            }
        return {
            "decision": "no_trade",
            "consensus_score": round(avg_conf / 100.0, 2),
            "reason": "SHORT_MAJORITY_CONFIDENCE_TOO_LOW"
        }

    return {
        "decision": "no_trade",
        "consensus_score": 0.0,
        "reason": "CONFLICTING_VOTES"
    }


def merge_outputs(candidate_packet: dict, role_outputs: list[dict], consensus: dict):
    leverage_hints = [float(r["leverage_hint"]) for r in role_outputs if r["decision"] in ("long", "short")]
    avg_leverage_hint = 10.0
    if leverage_hints:
        avg_leverage_hint = round(sum(leverage_hints) / len(leverage_hints), 2)

    merged_reason_tags = []
    for r in role_outputs:
        for tag in r["reason_tags"]:
            if tag not in merged_reason_tags:
                merged_reason_tags.append(tag)

    confidence_values = [int(r["confidence"]) for r in role_outputs if r["decision"] != "abstain"]
    final_confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0

    thesis_parts = []
    for r in role_outputs:
        thesis_parts.append(f"[{r['role']}] {r['thesis_summary']}")

    return {
        "ok": True,
        "symbol": candidate_packet["symbol"],
        "decision": consensus["decision"],
        "confidence": final_confidence,
        "consensus_score": consensus["consensus_score"],
        "strategy_style": candidate_packet.get("strategy_style_hint", "unspecified"),
        "role_votes": [
            {
                "role": r["role"],
                "decision": r["decision"],
                "confidence": r["confidence"]
            } for r in role_outputs
        ],
        "leverage_hint": avg_leverage_hint,
        "entry_preference": next((r["entry_preference"] for r in role_outputs if r["decision"] == consensus["decision"]), "none"),
        "stop_loss_hint": next((r["stop_loss_hint"] for r in role_outputs if r["decision"] == consensus["decision"]), "none"),
        "tp1_hint": next((r["tp1_hint"] for r in role_outputs if r["decision"] == consensus["decision"]), "none"),
        "tp2_hint": next((r["tp2_hint"] for r in role_outputs if r["decision"] == consensus["decision"]), "none"),
        "tp3_hint": next((r["tp3_hint"] for r in role_outputs if r["decision"] == consensus["decision"]), "none"),
        "thesis_summary": " | ".join(thesis_parts),
        "reason_tags": merged_reason_tags,
        "model_version": "stubbed-llm-v1",
        "prompt_version": "brain_v1",
        "snapshot_hash": candidate_packet.get("snapshot_hash", "unknown"),
        "consensus_reason": consensus["reason"]
    }


def analyze_candidate(candidate_packet: dict):
    role_outputs = []
    errors = []

    for role in ROLES:
        _ = build_role_prompt_payload(role, candidate_packet)
        output, err = call_llm_service(role, candidate_packet)
        if err:
            errors.append({"role": role, "error": err})
            continue
        role_outputs.append(output)

    if len(role_outputs) < 2:
        return {
            "ok": False,
            "error": "INSUFFICIENT_VALID_ROLE_OUTPUTS",
            "role_errors": errors
        }

    consensus = consensus_decision(role_outputs)
    merged = merge_outputs(candidate_packet, role_outputs, consensus)
    merged["role_errors"] = errors
    return merged


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
                "roles": ROLES
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
                payload = json.loads(raw.decode("utf-8"))

                candidate_packet = payload.get("candidate_packet")
                if not isinstance(candidate_packet, dict):
                    self._send_json({
                        "ok": False,
                        "error": "missing_candidate_packet"
                    }, status=400)
                    return

                result = analyze_candidate(candidate_packet)
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


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()