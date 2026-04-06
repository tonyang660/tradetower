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

FEATURE_FACTORY_VERSION = "v2"
SNAPSHOT_SCHEMA_VERSION = "market_snapshot_v2"

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

def classify_rsi_state(rsi_value: float) -> str:
    if rsi_value <= 30:
        return "oversold"
    elif rsi_value < 45:
        return "bearish_but_not_oversold"
    elif rsi_value <= 55:
        return "neutral"
    elif rsi_value < 70:
        return "bullish_but_not_overextended"
    return "overbought"

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

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
    latest_rsi = float(rsi.iloc[-1])
    latest_atr = float(atr.iloc[-1])
    latest_macd_hist = float(macd_hist.iloc[-1])
    prev_macd_hist = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else latest_macd_hist

    atr_percent = float((latest_atr / latest_close) * 100) if latest_close != 0 else 0.0
    ema_separation_pct = float(((latest_ema_fast - latest_ema_slow) / latest_ema_slow) * 100) if latest_ema_slow != 0 else 0.0
    macd_histogram_slope = float(latest_macd_hist - prev_macd_hist)

    return {
        "rsi": latest_rsi,
        "atr": latest_atr,
        "ema_fast": latest_ema_fast,
        "ema_slow": latest_ema_slow,
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(macd_signal.iloc[-1]),
        "macd_histogram": latest_macd_hist,
        "volume_sma": float(volume_sma.iloc[-1]),
        "price_vs_ema_fast_pct": float(((latest_close - latest_ema_fast) / latest_ema_fast) * 100) if latest_ema_fast != 0 else 0.0,
        "price_vs_ema_slow_pct": float(((latest_close - latest_ema_slow) / latest_ema_slow) * 100) if latest_ema_slow != 0 else 0.0,

        "ema_separation_pct": ema_separation_pct,
        "macd_histogram_slope": macd_histogram_slope,
        "rsi_state": classify_rsi_state(latest_rsi),
        "atr_percent": atr_percent,
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
    macd = indicators["macd"]
    macd_signal = indicators["macd_signal"]
    price_vs_ema_slow_pct = indicators["price_vs_ema_slow_pct"]
    atr_pct = indicators["atr_percent"]

    if ema_fast > ema_slow:
        trend_direction = "up"
    elif ema_fast < ema_slow:
        trend_direction = "down"
    else:
        trend_direction = "neutral"

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

    if higher_highs and higher_lows and not lower_highs and not lower_lows:
        swing_bias = "bullish"
        structure_state = "clean_trend"
    elif lower_highs and lower_lows and not higher_highs and not higher_lows:
        swing_bias = "bearish"
        structure_state = "clean_trend"
    elif market_type == "range":
        swing_bias = "neutral"
        structure_state = "range"
    elif market_type == "transition":
        swing_bias = "neutral"
        structure_state = "transition"
    else:
        swing_bias = "neutral"
        structure_state = "chop"

    structure_quality_score = 0.0
    if higher_highs and higher_lows:
        structure_quality_score += 40
    if lower_highs and lower_lows:
        structure_quality_score += 40
    if market_type == "trend":
        structure_quality_score += 25
    elif market_type == "range":
        structure_quality_score += 15
    elif market_type == "transition":
        structure_quality_score -= 10
    if higher_highs and lower_lows:
        structure_quality_score -= 20
    if lower_highs and higher_lows:
        structure_quality_score -= 20
    structure_quality_score = clamp(structure_quality_score, 0.0, 100.0)

    trend_consistency_score = 0.0
    if (ema_fast > ema_slow and higher_highs and higher_lows) or (ema_fast < ema_slow and lower_highs and lower_lows):
        trend_consistency_score += 50
    if (macd > macd_signal and ema_fast > ema_slow) or (macd < macd_signal and ema_fast < ema_slow):
        trend_consistency_score += 25
    if abs(price_vs_ema_slow_pct) > 1.0:
        trend_consistency_score += 15
    if market_type == "transition":
        trend_consistency_score -= 20
    trend_consistency_score = clamp(trend_consistency_score, 0.0, 100.0)

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

        "structure_state": structure_state,
        "structure_quality_score": structure_quality_score,
        "swing_bias": swing_bias,
        "trend_consistency_score": trend_consistency_score,
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

def compute_price_action(df: pd.DataFrame, indicators: dict, structure: dict) -> dict:
    candles = df.copy().reset_index(drop=True)
    last_close = float(candles["close"].iloc[-1])
    atr_value = float(indicators["atr"])
    ema_fast = float(indicators["ema_fast"])

    recent_bos_direction = "none"
    recent_bos_bars_ago = 999
    recent_bos_strength = 0.0
    recent_bos_failed = False

    search_window = min(len(candles), 12)
    for bars_ago in range(1, search_window):
        idx = len(candles) - bars_ago
        if idx < 6:
            continue

        candidate_close = float(candles["close"].iloc[idx])
        prior_high = float(candles["high"].iloc[idx-5:idx].max())
        prior_low = float(candles["low"].iloc[idx-5:idx].min())

        if candidate_close > prior_high:
            recent_bos_direction = "bullish"
            recent_bos_bars_ago = bars_ago - 1
            bos_distance = candidate_close - prior_high
            recent_bos_strength = bos_distance / atr_value if atr_value > 0 else 0.0
            recent_bos_strength = clamp(recent_bos_strength, 0.0, 1.0)
            if last_close < prior_high:
                recent_bos_failed = True
            break

        if candidate_close < prior_low:
            recent_bos_direction = "bearish"
            recent_bos_bars_ago = bars_ago - 1
            bos_distance = prior_low - candidate_close
            recent_bos_strength = bos_distance / atr_value if atr_value > 0 else 0.0
            recent_bos_strength = clamp(recent_bos_strength, 0.0, 1.0)
            if last_close > prior_low:
                recent_bos_failed = True
            break

    recent_high = float(candles["high"].tail(10).max())
    recent_low = float(candles["low"].tail(10).min())
    last_high_idx = int(candles["high"].tail(10).idxmax())
    last_low_idx = int(candles["low"].tail(10).idxmin())

    trend_direction = structure["trend_direction"]

    if trend_direction == "up":
        pullback_bars_ago = len(candles) - 1 - last_high_idx
        pullback_depth_pct = ((recent_high - last_close) / recent_high) * 100 if recent_high != 0 else 0.0
    elif trend_direction == "down":
        pullback_bars_ago = len(candles) - 1 - last_low_idx
        pullback_depth_pct = ((last_close - recent_low) / recent_low) * 100 if recent_low != 0 else 0.0
    else:
        dist_to_high = abs(recent_high - last_close)
        dist_to_low = abs(last_close - recent_low)

        if dist_to_high <= dist_to_low:
            pullback_bars_ago = len(candles) - 1 - last_high_idx
        else:
            pullback_bars_ago = len(candles) - 1 - last_low_idx

        pullback_depth_pct = abs(indicators["price_vs_ema_fast_pct"])

    if pullback_depth_pct <= 0.3:
        pullback_state = "no_pullback"
    elif pullback_depth_pct <= 1.0:
        pullback_state = "shallow_pullback"
    elif pullback_depth_pct <= 2.5:
        pullback_state = "active_pullback"
    elif pullback_depth_pct <= 4.0:
        pullback_state = "deep_pullback"
    else:
        pullback_state = "reversal_risk"

    pullback_quality_score = 0.0
    if pullback_depth_pct <= 0.5:
        pullback_quality_score += 20
    elif pullback_depth_pct <= 1.5:
        pullback_quality_score += 40
    elif pullback_depth_pct <= 3.0:
        pullback_quality_score += 25
    else:
        pullback_quality_score += 5

    if abs(indicators["price_vs_ema_fast_pct"]) <= 0.75:
        pullback_quality_score += 30

    if recent_bos_failed:
        pullback_quality_score -= 25

    pullback_quality_score = clamp(pullback_quality_score, 0.0, 100.0)

    recent_impulse_range = abs(recent_high - recent_low)
    recent_close_change = abs(float(candles["close"].iloc[-1]) - float(candles["close"].iloc[-4])) if len(candles) >= 4 else 0.0

    impulse_strength_score = min(100.0, (recent_impulse_range / atr_value) * 20) if atr_value > 0 else 0.0
    correction_strength_score = min(100.0, (recent_close_change / atr_value) * 20) if atr_value > 0 else 0.0
    impulse_to_correction_ratio = (
        impulse_strength_score / correction_strength_score
        if correction_strength_score > 0 else 999.0
    )

    last_open = float(candles["open"].iloc[-1])
    last_close_val = float(candles["close"].iloc[-1])
    last_high = float(candles["high"].iloc[-1])
    last_low = float(candles["low"].iloc[-1])

    upper_wick = last_high - max(last_open, last_close_val)
    lower_wick = min(last_open, last_close_val) - last_low
    body = abs(last_close_val - last_open)

    if lower_wick > upper_wick * 1.5:
        wick_rejection_bias = "bullish"
    elif upper_wick > lower_wick * 1.5:
        wick_rejection_bias = "bearish"
    else:
        wick_rejection_bias = "neutral"

    wick_rejection_score = 0.0
    if body > 0:
        wick_rejection_score = clamp(max(upper_wick, lower_wick) / body, 0.0, 1.0)

    recent_ranges = (candles["high"] - candles["low"]).tail(5)
    avg_recent_range = float(recent_ranges.mean()) if len(recent_ranges) > 0 else 0.0

    if atr_value > 0 and avg_recent_range > atr_value * 1.8:
        expansion_state = "overextended_expansion"
    elif atr_value > 0 and avg_recent_range > atr_value * 1.2:
        expansion_state = "healthy_expansion"
    else:
        expansion_state = "none"

    if len(recent_ranges) >= 3 and recent_ranges.iloc[-1] < recent_ranges.iloc[-2] < recent_ranges.iloc[-3]:
        compression_state = "strong_compression"
    elif len(recent_ranges) >= 2 and recent_ranges.iloc[-1] < recent_ranges.iloc[-2]:
        compression_state = "mild_compression"
    else:
        compression_state = "none"

    return {
        "recent_bos_direction": recent_bos_direction,
        "recent_bos_bars_ago": int(recent_bos_bars_ago),
        "recent_bos_strength": float(recent_bos_strength),
        "recent_bos_failed": bool(recent_bos_failed),

        "pullback_state": pullback_state,
        "pullback_bars_ago": int(max(0, pullback_bars_ago)),
        "pullback_depth_pct": float(pullback_depth_pct),
        "pullback_quality_score": float(pullback_quality_score),

        "impulse_strength_score": float(impulse_strength_score),
        "correction_strength_score": float(correction_strength_score),
        "impulse_to_correction_ratio": float(impulse_to_correction_ratio),

        "wick_rejection_bias": wick_rejection_bias,
        "wick_rejection_score": float(wick_rejection_score),

        "expansion_state": expansion_state,
        "compression_state": compression_state,
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
    price_action = compute_price_action(df, indicators, structure)
    volatility = compute_volatility(df, indicators)

    emitted_candles = candles[-emit_limit:]

    return {
        "timeframe": timeframe,
        "window_size": emit_limit,
        "candles": emitted_candles,
        "indicators": indicators,
        "structure": structure,
        "price_action": price_action,
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

    generated_at = iso_now()

    snapshot = {
        "snapshot_meta": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "feature_factory_version": FEATURE_FACTORY_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
        },
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "snapshot_timestamp": generated_at,
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