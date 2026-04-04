from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd
import requests


SERVICE_NAME = "feature-factory"
PORT = int(os.getenv("PORT", "8080"))
DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")

TIMEFRAMES = ["5m", "15m", "1h", "4h"]

FETCH_WINDOWS = {
    "5m": 72,
    "15m": 72,
    "1h": 72,
    "4h": 72,
}

EMIT_WINDOWS = {
    "5m": 72,
    "15m": 48,
    "1h": 30,
    "4h": 16,
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_candles(symbol: str, timeframe: str, limit: int):
    url = f"{DATA_HUB_BASE_URL}/candles"
    params = {
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": limit,
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        payload = response.json()
    except Exception:
        return None, "data_hub_request_failed"

    if not payload.get("ok"):
        return None, payload.get("error", "data_hub_error")

    candles = payload.get("candles", [])
    if len(candles) != limit:
        return None, "insufficient_candle_data"

    return candles, None


def to_dataframe(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr


def compute_macd(close: pd.Series):
    ema_fast = compute_ema(close, 12)
    ema_slow = compute_ema(close, 26)
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist


def compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    volume = df["volume"]

    ema_fast = compute_ema(close, 12)
    ema_slow = compute_ema(close, 26)
    rsi = compute_rsi(close, 14)
    atr = compute_atr(df, 14)
    macd, macd_signal, macd_hist = compute_macd(close)
    volume_sma = volume.rolling(window=20, min_periods=1).mean()

    latest_close = float(close.iloc[-1])
    latest_ema_fast = float(ema_fast.iloc[-1])
    latest_ema_slow = float(ema_slow.iloc[-1])

    return {
        "rsi": float(rsi.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "ema_fast": latest_ema_fast,
        "ema_slow": latest_ema_slow,
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(macd_signal.iloc[-1]),
        "macd_histogram": float(macd_hist.iloc[-1]),
        "volume_sma": float(volume_sma.iloc[-1]),
        "price_vs_ema_fast_pct": float(((latest_close - latest_ema_fast) / latest_ema_fast) * 100),
        "price_vs_ema_slow_pct": float(((latest_close - latest_ema_slow) / latest_ema_slow) * 100),
    }


def compute_structure(df: pd.DataFrame, indicators: dict) -> dict:
    recent = df.tail(20).copy()
    highs = recent["high"].tolist()
    lows = recent["low"].tolist()

    higher_highs = highs[-1] > highs[-5] if len(highs) >= 5 else False
    higher_lows = lows[-1] > lows[-5] if len(lows) >= 5 else False
    lower_highs = highs[-1] < highs[-5] if len(highs) >= 5 else False
    lower_lows = lows[-1] < lows[-5] if len(lows) >= 5 else False

    ema_fast = indicators["ema_fast"]
    ema_slow = indicators["ema_slow"]

    if ema_fast > ema_slow:
        trend_direction = "up"
    elif ema_fast < ema_slow:
        trend_direction = "down"
    else:
        trend_direction = "neutral"

    atr_pct = 0.0
    last_close = float(df["close"].iloc[-1])
    if last_close != 0:
        atr_pct = float((indicators["atr"] / last_close) * 100)

    if (higher_highs and higher_lows) or (lower_highs and lower_lows):
        market_type = "trend"
    elif atr_pct < 0.35:
        market_type = "range"
    else:
        market_type = "transition"

    range_high = float(recent["high"].max())
    range_low = float(recent["low"].min())
    current_close = float(df["close"].iloc[-1])

    range_span = range_high - range_low
    if range_span <= 0:
        dist_high = 0.0
        dist_low = 0.0
    else:
        dist_high = float(((range_high - current_close) / range_span) * 100)
        dist_low = float(((current_close - range_low) / range_span) * 100)

    return {
        "trend_direction": trend_direction,
        "market_type": market_type,
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "lower_highs": lower_highs,
        "lower_lows": lower_lows,
        "range_high": range_high,
        "range_low": range_low,
        "distance_to_range_high_pct": dist_high,
        "distance_to_range_low_pct": dist_low,
    }


def compute_volatility(df: pd.DataFrame, indicators: dict) -> dict:
    last_close = float(df["close"].iloc[-1])
    atr = float(indicators["atr"])

    atr_percent = float((atr / last_close) * 100) if last_close != 0 else 0.0

    if atr_percent < 0.35:
        state = "low"
    elif atr_percent < 0.9:
        state = "medium"
    else:
        state = "high"

    return {
        "atr": atr,
        "atr_percent": atr_percent,
        "volatility_state": state,
    }


def build_timeframe_block(symbol: str, timeframe: str):
    fetch_limit = FETCH_WINDOWS[timeframe]
    emit_limit = EMIT_WINDOWS[timeframe]

    candles, error = fetch_candles(symbol, timeframe, fetch_limit)
    if error:
        return None, error

    if len(candles) < fetch_limit:
        return None, "insufficient_candle_data"

    df = to_dataframe(candles)
    indicators = compute_indicators(df)
    structure = compute_structure(df, indicators)
    volatility = compute_volatility(df, indicators)

    emitted_candles = candles[-emit_limit:]

    return {
        "timeframe": timeframe,
        "window_size": emit_limit,
        "candles": emitted_candles,
        "indicators": indicators,
        "structure": structure,
        "volatility": volatility,
    }, None


def build_market_snapshot(symbol: str):
    timeframes = {}
    missing = []

    for tf in TIMEFRAMES:
        block, error = build_timeframe_block(symbol, tf)
        if error:
            missing.append({"timeframe": tf, "error": error})
        else:
            timeframes[tf] = block

    if missing:
        return None, {
            "ok": False,
            "error": "snapshot_build_failed",
            "symbol": symbol,
            "details": missing
        }

    snapshot = {
        "schema_version": "market_snapshot_v1",
        "symbol": symbol,
        "snapshot_timestamp": iso_now(),
        "source": SERVICE_NAME,
        "timeframes": timeframes
    }

    return snapshot, None


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

        if self.path.startswith("/snapshot"):
            query = parse_qs(urlparse(self.path).query)
            symbol = query.get("symbol", [None])[0]

            if not symbol:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol"]
                }, status=400)
                return

            snapshot, error = build_market_snapshot(symbol)

            if error:
                self._send_json(error, status=400)
                return

            self._send_json(snapshot)
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