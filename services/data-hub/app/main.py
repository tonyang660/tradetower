from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone
import json
import os
from urllib.parse import urlparse, parse_qs

import pandas as pd


SERVICE_NAME = "data-hub"
PORT = int(os.getenv("PORT", "8080"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))

DEFAULT_MARKET_PROVIDER = os.getenv("DEFAULT_MARKET_PROVIDER", "blofin").lower()
DEFAULT_MARKET = os.getenv("DEFAULT_MARKET", "usdt_perp").lower()

MARKET_DATA_MAX_GAP_COUNT = int(os.getenv("MARKET_DATA_MAX_GAP_COUNT", "3"))
MARKET_DATA_STALE_INTERVAL_MULTIPLIER = float(
    os.getenv("MARKET_DATA_STALE_INTERVAL_MULTIPLIER", "2.5")
)

VALID_TIMEFRAMES = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h", "1d",
}

TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


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


def parse_timestamp(value) -> pd.Timestamp | None:
    try:
        ts = pd.to_datetime(value, utc=True)
    except Exception:
        return None

    if pd.isna(ts):
        return None

    return ts


def normalize_candles(candles: list[dict]) -> list[dict]:
    normalized = []

    for candle in candles:
        item = dict(candle)

        ts = parse_timestamp(item.get("timestamp"))
        if ts is None:
            continue

        item["timestamp"] = ts.isoformat().replace("+00:00", "Z")

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


def detect_candle_gaps(
    df: pd.DataFrame,
    timeframe: str,
    max_gaps: int | None = None,
) -> dict:
    if timeframe not in TIMEFRAME_SECONDS:
        return {
            "ok": False,
            "error": "unsupported_timeframe_for_gap_check",
            "expected_interval_seconds": None,
            "gap_count": 0,
            "gaps": [],
        }

    if df.empty or len(df) < 2:
        return {
            "ok": True,
            "expected_interval_seconds": TIMEFRAME_SECONDS[timeframe],
            "gap_count": 0,
            "gaps": [],
        }

    max_gaps = MARKET_DATA_MAX_GAP_COUNT if max_gaps is None else max_gaps
    expected_seconds = TIMEFRAME_SECONDS[timeframe]

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").reset_index(drop=True)

    gaps = []
    previous_ts = None

    for current_ts in work["timestamp"]:
        if previous_ts is not None:
            delta_seconds = int((current_ts - previous_ts).total_seconds())

            if delta_seconds > expected_seconds + 1:
                missing_intervals = max(
                    int(round(delta_seconds / expected_seconds)) - 1,
                    1,
                )
                gaps.append({
                    "from": previous_ts.isoformat().replace("+00:00", "Z"),
                    "to": current_ts.isoformat().replace("+00:00", "Z"),
                    "delta_seconds": delta_seconds,
                    "missing_intervals_estimate": missing_intervals,
                })

                if len(gaps) >= max_gaps:
                    break

        previous_ts = current_ts

    return {
        "ok": True,
        "expected_interval_seconds": expected_seconds,
        "gap_count": len(gaps),
        "gaps": gaps,
    }


def build_market_data_status(
    symbol: str,
    timeframe: str,
    provider: str | None = None,
    market: str | None = None,
    min_rows: int = 1,
    check_gaps: bool = True,
) -> tuple[bool, str | None, dict]:
    if timeframe not in VALID_TIMEFRAMES:
        return False, "invalid_timeframe", {}

    provider = normalize_provider(provider)
    market = normalize_market(market)
    symbol = normalize_symbol(symbol)

    path = get_parquet_path(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        market=market,
    )

    base_status = {
        "provider": provider,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "exists": path.exists(),
        "stored_rows": 0,
        "min_rows": min_rows,
        "has_min_rows": False,
        "expected_interval_seconds": TIMEFRAME_SECONDS.get(timeframe),
        "stale_after_seconds": (
            int(TIMEFRAME_SECONDS[timeframe] * MARKET_DATA_STALE_INTERVAL_MULTIPLIER)
            if timeframe in TIMEFRAME_SECONDS
            else None
        ),
        "now": iso_now(),
        "first_timestamp": None,
        "last_timestamp": None,
        "last_age_seconds": None,
        "is_stale": True,
        "gap_count": None,
        "gap_check_window_rows": None,
        "gaps": [],
        "healthy": False,
        "reason_codes": [],
    }

    if not path.exists():
        base_status["reason_codes"].append("CANDLES_NOT_FOUND")
        return False, "candles_not_found", base_status

    try:
        df = pd.read_parquet(path)
    except Exception as e:
        base_status["reason_codes"].append("PARQUET_READ_FAILED")
        base_status["read_error"] = str(e)
        return False, "parquet_read_failed", base_status

    if "timestamp" not in df.columns:
        base_status["reason_codes"].append("TIMESTAMP_COLUMN_MISSING")
        return False, "invalid_candle_shape", base_status

    if df.empty:
        base_status["reason_codes"].append("NO_STORED_ROWS")
        return False, "no_stored_rows", base_status

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    if df.empty:
        base_status["reason_codes"].append("NO_VALID_TIMESTAMPS")
        return False, "no_valid_timestamps", base_status

    first_ts = df["timestamp"].iloc[0]
    last_ts = df["timestamp"].iloc[-1]
    age_seconds = max(0, int((utc_now() - last_ts.to_pydatetime()).total_seconds()))
    stale_after_seconds = base_status["stale_after_seconds"]

    base_status.update({
        "stored_rows": len(df),
        "has_min_rows": len(df) >= min_rows,
        "first_timestamp": first_ts.isoformat().replace("+00:00", "Z"),
        "last_timestamp": last_ts.isoformat().replace("+00:00", "Z"),
        "last_age_seconds": age_seconds,
        "is_stale": (
            True
            if stale_after_seconds is None
            else age_seconds > stale_after_seconds
        ),
    })

    if not base_status["has_min_rows"]:
        base_status["reason_codes"].append("INSUFFICIENT_ROWS")

    if base_status["is_stale"]:
        base_status["reason_codes"].append("STALE_LAST_CANDLE")

    if check_gaps:
        # For runtime readiness, check the latest requested window rather than the
        # entire historical parquet file. Historical gaps can exist during staged
        # backfills, but strategy execution only needs the latest min_rows window
        # to be contiguous and fresh.
        gap_window_rows = max(int(min_rows or 1), 2)

        gap_df = (
            df
            .sort_values("timestamp")
            .tail(gap_window_rows)
            .reset_index(drop=True)
        )

        gap_status = detect_candle_gaps(gap_df, timeframe)
        base_status["gap_count"] = gap_status.get("gap_count")
        base_status["gaps"] = gap_status.get("gaps", [])
        base_status["gap_check_window_rows"] = len(gap_df)

        if base_status["gap_count"]:
            base_status["reason_codes"].append("GAPS_DETECTED")

    base_status["healthy"] = len(base_status["reason_codes"]) == 0

    return True, None, base_status


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

    _, _, status = build_market_data_status(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        market=market,
        min_rows=1,
        check_gaps=True,
    )

    metadata = {
        "provider": provider,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "first_timestamp": status.get("first_timestamp"),
        "last_timestamp": status.get("last_timestamp"),
        "status": status,
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

    _, _, status = build_market_data_status(
        symbol=symbol,
        timeframe=timeframe,
        provider=provider,
        market=market,
        min_rows=limit,
        check_gaps=True,
    )

    metadata = {
        "provider": provider,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "path": str(path),
        "stored_rows": len(df),
        "first_timestamp": status.get("first_timestamp"),
        "last_timestamp": status.get("last_timestamp"),
        "status": status,
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
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "default_provider": DEFAULT_MARKET_PROVIDER,
                "default_market": DEFAULT_MARKET,
                "market_data_stale_interval_multiplier": MARKET_DATA_STALE_INTERVAL_MULTIPLIER,
                "market_data_max_gap_count": MARKET_DATA_MAX_GAP_COUNT,
            })
            return

        if parsed.path in ("/candles/status", "/market-data/status"):
            query = parse_qs(parsed.query)

            symbol = query.get("symbol", [None])[0]
            timeframe = query.get("timeframe", [None])[0]
            provider = query.get("provider", [DEFAULT_MARKET_PROVIDER])[0]
            market = query.get("market", [DEFAULT_MARKET])[0]

            try:
                min_rows = int(query.get("min_rows", [1])[0])
            except ValueError:
                self._send_json({
                    "ok": False,
                    "error": "invalid_min_rows",
                }, status=400)
                return

            check_gaps = query.get("check_gaps", ["true"])[0].lower() != "false"

            if not symbol or not timeframe:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol", "timeframe"],
                }, status=400)
                return

            ok, error, status_payload = build_market_data_status(
                symbol=symbol,
                timeframe=timeframe,
                provider=provider,
                market=market,
                min_rows=min_rows,
                check_gaps=check_gaps,
            )

            self._send_json({
                "ok": ok,
                "error": error,
                "status": status_payload,
            }, status=404 if error == "candles_not_found" else 200)
            return

        if parsed.path == "/candles":
            query = parse_qs(parsed.query)

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
        parsed = urlparse(self.path)

        if parsed.path == "/candles/ingest":
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
