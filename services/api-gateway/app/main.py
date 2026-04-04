from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os
import urllib.request
import urllib.parse

SERVICE_NAME = "api-gateway"
PORT = int(os.getenv("PORT", "8080"))

# Internal timeframe names -> Bitget format
TIMEFRAME_MAP = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
}

PRODUCT_TYPE = "USDT-FUTURES"


def ms_to_iso8601_utc(ms_str: str) -> str:
    dt = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def normalize_bitget_candle(raw_candle: list) -> dict:
    """
    Bitget futures candle response format:
    [timestamp_ms, open, high, low, close, volume_base, volume_quote]
    """
    return {
        "timestamp": ms_to_iso8601_utc(raw_candle[0]),
        "open": float(raw_candle[1]),
        "high": float(raw_candle[2]),
        "low": float(raw_candle[3]),
        "close": float(raw_candle[4]),
        "volume": float(raw_candle[5]),
    }


def fetch_bitget_candles(symbol: str, timeframe: str, limit: int):
    if timeframe not in TIMEFRAME_MAP:
        return None, "invalid_timeframe"

    if limit <= 0:
        return None, "invalid_limit"

    granularity = TIMEFRAME_MAP[timeframe]

    params = urllib.parse.urlencode({
        "symbol": symbol,
        "productType": PRODUCT_TYPE,
        "granularity": granularity,
        "limit": limit,
    })

    url = f"https://api.bitget.com/api/v2/mix/market/candles?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None, "request_failed"

    code = payload.get("code")
    data = payload.get("data")

    if code != "00000":
        return None, "provider_error"

    if not data:
        return None, "no_data"

    candles = []
    for raw in data:
        try:
            candles.append(normalize_bitget_candle(raw))
        except Exception:
            continue

    if not candles:
        return None, "normalization_failed"

    # Sort oldest -> newest for internal consistency
    candles.sort(key=lambda c: c["timestamp"])

    return candles, None


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
                "service": SERVICE_NAME
            })
            return

        if self.path.startswith("/providers/bitget/candles"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

            symbol = query.get("symbol", [None])[0]
            timeframe = query.get("timeframe", [None])[0]

            try:
                limit = int(query.get("limit", [50])[0])
            except ValueError:
                self._send_json({
                    "ok": False,
                    "error": "invalid_limit"
                }, status=400)
                return

            if not symbol or not timeframe:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol", "timeframe"]
                }, status=400)
                return

            candles, error = fetch_bitget_candles(symbol, timeframe, limit)

            if error:
                self._send_json({
                    "ok": False,
                    "provider": "bitget",
                    "error": error,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "provider": "bitget",
                "market": "usdt_perp",
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles
            })
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