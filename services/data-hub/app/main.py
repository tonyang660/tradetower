from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import os
from urllib.parse import urlparse, parse_qs

import pandas as pd


SERVICE_NAME = "data-hub"
PORT = int(os.getenv("PORT", "8080"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))

VALID_TIMEFRAMES = {"5m", "15m", "1h", "4h"}


def get_parquet_path(symbol: str, timeframe: str) -> Path:
    return DATA_ROOT / "market" / "bitget" / "usdt_perp" / symbol / timeframe / "data.parquet"


def ensure_parent_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def write_candles(symbol: str, timeframe: str, candles: list[dict]) -> tuple[bool, str | None, int]:
    if timeframe not in VALID_TIMEFRAMES:
        return False, "invalid_timeframe", 0

    if not candles:
        return False, "no_candles_provided", 0

    path = get_parquet_path(symbol, timeframe)
    ensure_parent_dir(path)

    new_df = pd.DataFrame(candles)

    required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required_cols.issubset(new_df.columns):
        return False, "invalid_candle_shape", 0

    if path.exists():
        old_df = pd.read_parquet(path)
        df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        df = new_df

    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    df.to_parquet(path, index=False)
    return True, None, len(df)


def read_latest_candles(symbol: str, timeframe: str, limit: int) -> tuple[bool, str | None, list[dict]]:
    if timeframe not in VALID_TIMEFRAMES:
        return False, "invalid_timeframe", []

    if limit <= 0:
        return False, "invalid_limit", []

    path = get_parquet_path(symbol, timeframe)

    if not path.exists():
        return False, "candles_not_found", []

    df = pd.read_parquet(path).sort_values("timestamp")
    candles = df.tail(limit).to_dict(orient="records")
    return True, None, candles


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

        if self.path.startswith("/candles"):
            query = parse_qs(urlparse(self.path).query)

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

            ok, error, candles = read_latest_candles(symbol, timeframe, limit)

            if not ok:
                self._send_json({
                    "ok": False,
                    "error": error,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit
                }, status=404 if error == "candles_not_found" else 400)
                return

            self._send_json({
                "ok": True,
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

    def do_POST(self):
        if self.path == "/candles/ingest":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({
                    "ok": False,
                    "error": "invalid_json"
                }, status=400)
                return

            symbol = payload.get("symbol")
            timeframe = payload.get("timeframe")
            candles = payload.get("candles")

            if not symbol or not timeframe or not isinstance(candles, list):
                self._send_json({
                    "ok": False,
                    "error": "missing_or_invalid_fields",
                    "required": ["symbol", "timeframe", "candles"]
                }, status=400)
                return

            ok, error, total_rows = write_candles(symbol, timeframe, candles)

            if not ok:
                self._send_json({
                    "ok": False,
                    "error": error,
                    "symbol": symbol,
                    "timeframe": timeframe
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "stored_rows": total_rows
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