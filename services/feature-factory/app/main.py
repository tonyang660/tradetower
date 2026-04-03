from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from datetime import datetime, timedelta, timezone


SERVICE_NAME = "feature-factory"
PORT = int(os.getenv("PORT", "8080"))


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_candles(tf_label: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    candles = []

    # Simple placeholder timing logic for now
    if tf_label == "5m":
        delta = timedelta(minutes=5)
    elif tf_label == "15m":
        delta = timedelta(minutes=15)
    elif tf_label == "1h":
        delta = timedelta(hours=1)
    elif tf_label == "4h":
        delta = timedelta(hours=4)
    else:
        raise ValueError(f"Unsupported timeframe: {tf_label}")

    for i in range(50):
        ts = now - delta * (49 - i)
        candles.append({
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0
        })

    return candles


def make_timeframe_block(tf_label: str) -> dict:
    return {
        "timeframe": tf_label,
        "window_size": 50,
        "candles": generate_candles(tf_label),
        "indicators": {
            "rsi": 50.0,
            "atr": 10.0,
            "ema_fast": 100.0,
            "ema_slow": 105.0,
            "macd": 1.0,
            "macd_signal": 0.5,
            "macd_histogram": 0.5,
            "volume_sma": 1000.0,
            "price_vs_ema_fast_pct": 0.5,
            "price_vs_ema_slow_pct": -0.2
        },
        "structure": {
            "trend_direction": "neutral",
            "market_type": "range",
            "higher_highs": False,
            "higher_lows": False,
            "lower_highs": False,
            "lower_lows": False,
            "range_high": 110.0,
            "range_low": 90.0,
            "distance_to_range_high_pct": 0.2,
            "distance_to_range_low_pct": 0.8
        },
        "volatility": {
            "atr": 10.0,
            "atr_percent": 0.5,
            "volatility_state": "medium"
        }
    }


def build_sample_snapshot(symbol: str = "BTCUSDT") -> dict:
    return {
        "schema_version": "market_snapshot_v1",
        "symbol": symbol,
        "snapshot_timestamp": iso_now(),
        "source": SERVICE_NAME,
        "timeframes": {
            "5m": make_timeframe_block("5m"),
            "15m": make_timeframe_block("15m"),
            "1h": make_timeframe_block("1h"),
            "4h": make_timeframe_block("4h")
        }
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
        if self.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "env": os.getenv("APP_ENV", "unknown")
            })
            return

        if self.path == "/snapshot/sample":
            self._send_json(build_sample_snapshot())
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