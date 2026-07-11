from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import os
from urllib.parse import urlparse, parse_qs

import pandas as pd


SERVICE_NAME = "data-hub"
PORT = int(os.getenv("PORT", "8080"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))

DEFAULT_MARKET_PROVIDER = os.getenv(
    "DEFAULT_MARKET_PROVIDER",
    "blofin",
).lower()

DEFAULT_MARKET = os.getenv(
    "DEFAULT_MARKET",
    "usdt_perp",
).lower()

VALID_TIMEFRAMES = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def normalize_provider(provider: str | None) -> str:
    return str(provider or DEFAULT_MARKET_PROVIDER).strip().lower()


def normalize_market(market: str | None) -> str:
    return str(market or DEFAULT_MARKET).strip().lower()


def get_parquet_path(
    symbol: str,
    timeframe: str,
    provider: str | None = None,
    market: str | None = None,
) -> Path:
    return (
        DATA_ROOT
        / "market"
        / normalize_provider(provider)
        / normalize_market(market)
        / normalize_symbol(symbol)
        / timeframe
        / "data.parquet"
    )


def ensure_parent_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_candles(candles: list[dict]) -> list[dict]:
    normalized = []

    for candle in candles:
        item = dict(candle)

        if "timestamp" not in item:
            continue

        for key in ("open", "high", "low", "close", "volume"):
            if key not in item:
                item[key] = None

        try:
            item["open"] = float(item["open"])
            item["high"] = float(item["high"])
            item["low"] = float(item["low"])
            item["close"] = float(item["close"])
            item["volume"] = float(item["volume"])
        except Exception:
            continue

        normalized.append(item)

    return normalized


def write_candles(
    symbol: str,
    timeframe: str,
    candles: list[dict],
    provider: str | None = None,
    market: str | None = None,
) -> tuple[bool, str | None, int, dict]:
    if timeframe not in VALID_TIMEFRAMES:
        return False, "invalid_timeframe", 0, {}

    if not candles:
        return False, "no_candles_provided", 0, {}

    provider = normalize_provider(provider)
    market = normalize_market(market)
    symbol = normalize_symbol(symbol)

    normalized_candles = normalize_candles(candles)
    if not normalized_candles:
        return False, "invalid_candle_shape", 0, {}

    path = get_parquet_path(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        market=market,
    )
    ensure_parent_dir(path)

    new_df = pd.DataFrame(normalized_candles)

    required_cols = {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not required_cols.issubset(new_df.columns):
        return False, "invalid_candle_shape", 0, {}

    if path.exists():
        old_df = pd.read_parquet(path)
        df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        df = new_df

    df = (
        df
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    df.to_parquet(path, index=False)

    metadata = {
        "provider": provider,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "first_timestamp": (
            str(df["timestamp"].iloc[0])
            if len(df) > 0
            else None
        ),
        "last_timestamp": (
            str(df["timestamp"].iloc[-1])
            if len(df) > 0
            else None
        ),
    }

    return True, None, len(df), metadata


def read_latest_candles(
    symbol: str,
    timeframe: str,
    limit: int,
    provider: str | None = None,
    market: str | None = None,
) -> tuple[bool, str | None, list[dict], dict]:
    if timeframe not in VALID_TIMEFRAMES:
        return False, "invalid_timeframe", [], {}

    if limit <= 0:
        return False, "invalid_limit", [], {}

    provider = normalize_provider(provider)
    market = normalize_market(market)
    symbol = normalize_symbol(symbol)

    path = get_parquet_path(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        market=market,
    )

    if not path.exists():
        return False, "candles_not_found", [], {
            "provider": provider,
            "market": market,
            "symbol": symbol,
            "timeframe": timeframe,
            "path": str(path),
        }

    df = pd.read_parquet(path).sort_values("timestamp")
    candles = df.tail(limit).to_dict(orient="records")

    metadata = {
        "provider": provider,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "stored_rows": len(df),
        "first_timestamp": (
            str(df["timestamp"].iloc[0])
            if len(df) > 0
            else None
        ),
        "last_timestamp": (
            str(df["timestamp"].iloc[-1])
            if len(df) > 0
            else None
        ),
    }

    return True, None, candles, metadata


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
                "default_provider": DEFAULT_MARKET_PROVIDER,
                "default_market": DEFAULT_MARKET,
            })
            return

        if self.path.startswith("/candles"):
            query = parse_qs(urlparse(self.path).query)

            symbol = query.get("symbol", [None])[0]
            timeframe = query.get("timeframe", [None])[0]
            provider = query.get("provider", [DEFAULT_MARKET_PROVIDER])[0]
            market = query.get("market", [DEFAULT_MARKET])[0]

            try:
                limit = int(query.get("limit", [50])[0])
            except ValueError:
                self._send_json({
                    "ok": False,
                    "error": "invalid_limit",
                }, status=400)
                return

            if not symbol or not timeframe:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol", "timeframe"],
                }, status=400)
                return

            ok, error, candles, metadata = read_latest_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                provider=provider,
                market=market,
            )

            if not ok:
                self._send_json({
                    "ok": False,
                    "error": error,
                    "symbol": normalize_symbol(symbol),
                    "timeframe": timeframe,
                    "provider": normalize_provider(provider),
                    "market": normalize_market(market),
                    "limit": limit,
                    "metadata": metadata,
                }, status=404 if error == "candles_not_found" else 400)
                return

            self._send_json({
                "ok": True,
                "symbol": normalize_symbol(symbol),
                "timeframe": timeframe,
                "provider": metadata["provider"],
                "market": metadata["market"],
                "count": len(candles),
                "metadata": metadata,
                "candles": candles,
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
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
                    "error": "invalid_json",
                }, status=400)
                return

            symbol = payload.get("symbol")
            timeframe = payload.get("timeframe")
            candles = payload.get("candles")
            provider = payload.get("provider", DEFAULT_MARKET_PROVIDER)
            market = payload.get("market", DEFAULT_MARKET)

            if not symbol or not timeframe or not isinstance(candles, list):
                self._send_json({
                    "ok": False,
                    "error": "missing_or_invalid_fields",
                    "required": ["symbol", "timeframe", "candles"],
                }, status=400)
                return

            ok, error, total_rows, metadata = write_candles(
                symbol=symbol,
                timeframe=timeframe,
                candles=candles,
                provider=provider,
                market=market,
            )

            if not ok:
                self._send_json({
                    "ok": False,
                    "error": error,
                    "symbol": normalize_symbol(symbol),
                    "timeframe": timeframe,
                    "provider": normalize_provider(provider),
                    "market": normalize_market(market),
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "symbol": metadata["symbol"],
                "timeframe": metadata["timeframe"],
                "provider": metadata["provider"],
                "market": metadata["market"],
                "stored_rows": total_rows,
                "metadata": metadata,
            })
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