from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import json
import os

import requests


SERVICE_NAME = "candidate-filter"
PORT = int(os.getenv("PORT", "8080"))
FEATURE_FACTORY_BASE_URL = os.getenv("FEATURE_FACTORY_BASE_URL", "http://feature-factory:8080")
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "6"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "50"))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_snapshot(symbol: str):
    url = f"{FEATURE_FACTORY_BASE_URL}/snapshot"
    try:
        response = requests.get(url, params={"symbol": symbol}, timeout=15)
        payload = response.json()
    except Exception:
        return None, "snapshot_request_failed"

    if not isinstance(payload, dict):
        return None, "invalid_snapshot_response"

    if not payload.get("schema_version") == "market_snapshot_v1":
        return None, payload.get("error", "snapshot_unavailable")

    return payload, None


def determine_bias(snapshot: dict) -> str:
    tf_4h = snapshot["timeframes"]["4h"]
    tf_1h = snapshot["timeframes"]["1h"]
    tf_15m = snapshot["timeframes"]["15m"]

    dir_4h = tf_4h["structure"]["trend_direction"]
    dir_1h = tf_1h["structure"]["trend_direction"]
    dir_15m = tf_15m["structure"]["trend_direction"]

    if dir_4h == "up" and (dir_1h == "up" or dir_15m == "up"):
        return "long"
    if dir_4h == "down" and (dir_1h == "down" or dir_15m == "down"):
        return "short"
    return "neutral"

def score_snapshot(snapshot: dict):
    total_score = 0.0
    reasons = []

    tf_5m = snapshot["timeframes"]["5m"]
    tf_15m = snapshot["timeframes"]["15m"]
    tf_1h = snapshot["timeframes"]["1h"]
    tf_4h = snapshot["timeframes"]["4h"]

    bias = determine_bias(snapshot)

    sub_scores = {
        "bias_alignment": 0.0,
        "momentum": 0.0,
        "setup": 0.0,
        "execution": 0.0,
        "volatility": 0.0,
    }

    # 1) Higher timeframe bias alignment (25)
    if bias != "neutral":
        sub_scores["bias_alignment"] = 25.0
        reasons.append("HTF_BIAS_ALIGN")
    else:
        reasons.append("HTF_BIAS_CONFLICT")

    # 2) Momentum quality (25)
    momentum_points = 0.0

    if tf_1h["indicators"]["macd_histogram"] > 0 and bias == "long":
        momentum_points += 10
    elif tf_1h["indicators"]["macd_histogram"] < 0 and bias == "short":
        momentum_points += 10

    if tf_15m["indicators"]["macd_histogram"] > 0 and bias == "long":
        momentum_points += 8
    elif tf_15m["indicators"]["macd_histogram"] < 0 and bias == "short":
        momentum_points += 8

    if bias == "long":
        if tf_15m["indicators"]["price_vs_ema_fast_pct"] > 0:
            momentum_points += 4
        if tf_1h["indicators"]["price_vs_ema_fast_pct"] > 0:
            momentum_points += 3
    elif bias == "short":
        if tf_15m["indicators"]["price_vs_ema_fast_pct"] < 0:
            momentum_points += 4
        if tf_1h["indicators"]["price_vs_ema_fast_pct"] < 0:
            momentum_points += 3

    sub_scores["momentum"] = momentum_points

    if momentum_points >= 15:
        reasons.append("MOMENTUM_SUPPORT")
    else:
        reasons.append("MOMENTUM_WEAK")

    # 3) Setup quality on 15m (25)
    setup_points = 0.0
    market_type_15m = tf_15m["structure"]["market_type"]
    dir_15m = tf_15m["structure"]["trend_direction"]

    if market_type_15m in ("trend", "transition"):
        setup_points += 10

    if bias == "long" and dir_15m == "up":
        setup_points += 8
    elif bias == "short" and dir_15m == "down":
        setup_points += 8

    rsi_15m = tf_15m["indicators"]["rsi"]
    if bias == "long" and 45 <= rsi_15m <= 70:
        setup_points += 7
    elif bias == "short" and 30 <= rsi_15m <= 55:
        setup_points += 7

    sub_scores["setup"] = setup_points

    if setup_points >= 14:
        reasons.append("SETUP_QUALITY_OK")
    else:
        reasons.append("SETUP_QUALITY_WEAK")

    # 4) Execution readiness on 5m (15)
    exec_points = 0.0
    dir_5m = tf_5m["structure"]["trend_direction"]

    if bias == "long" and dir_5m == "up":
        exec_points += 8
    elif bias == "short" and dir_5m == "down":
        exec_points += 8

    if bias == "long" and tf_5m["indicators"]["price_vs_ema_fast_pct"] > 0:
        exec_points += 7
    elif bias == "short" and tf_5m["indicators"]["price_vs_ema_fast_pct"] < 0:
        exec_points += 7

    sub_scores["execution"] = exec_points

    if exec_points >= 8:
        reasons.append("EXECUTION_ALIGN")
    else:
        reasons.append("EXECUTION_CONFLICT")

    # 5) Volatility suitability (10)
    vol_points = 0.0
    vol_state_15m = tf_15m["volatility"]["volatility_state"]

    if vol_state_15m == "medium":
        vol_points = 10.0
        reasons.append("VOLATILITY_OK")
    elif vol_state_15m == "low":
        vol_points = 3.0
        reasons.append("VOLATILITY_TOO_LOW")
    else:
        vol_points = 5.0
        reasons.append("VOLATILITY_TOO_HIGH")

    sub_scores["volatility"] = vol_points

    total_score = round(sum(sub_scores.values()), 2)

    if total_score < MIN_SCORE:
        reasons.append("LOW_CONVICTION")

    return total_score, bias, reasons, sub_scores

def rank_symbols(symbols: list[str]):
    candidates = []
    rejected = []

    for symbol in symbols:
        snapshot, error = fetch_snapshot(symbol)

        if error:
            rejected.append({
                "symbol": symbol,
                "score": 0.0,
                "bias": "neutral",
                "reasons": ["SNAPSHOT_UNAVAILABLE"]
            })
            continue

        score, bias, reasons, sub_scores = score_snapshot(snapshot)

        item = {
            "symbol": symbol,
            "score": score,
            "bias": bias,
            "sub_scores": sub_scores,
            "reasons": reasons
        }

        if score >= MIN_SCORE:
            candidates.append(item)
        else:
            rejected.append(item)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    rejected.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:MAX_CANDIDATES], rejected


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
                "env": os.getenv("APP_ENV", "unknown")
            })
            return

        if self.path.startswith("/candidates"):
            try:
                query = parse_qs(urlparse(self.path).query)
                symbols_param = query.get("symbols", [None])[0]

                if not symbols_param:
                    self._send_json({
                        "ok": False,
                        "error": "missing_parameters",
                        "required": ["symbols"]
                    }, status=400)
                    return

                symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
                if not symbols:
                    self._send_json({
                        "ok": False,
                        "error": "no_symbols_provided"
                    }, status=400)
                    return

                candidates, rejected = rank_symbols(symbols)

                self._send_json({
                    "ok": True,
                    "generated_at": iso_now(),
                    "max_candidates": MAX_CANDIDATES,
                    "min_score": MIN_SCORE,
                    "candidates": candidates,
                    "rejected": rejected
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
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()