
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd
import requests

try:
    from market_snapshot_contract import (
        MARKET_SNAPSHOT_SCHEMA_VERSION,
        MARKET_SNAPSHOT_CONTRACT_VERSION,
        build_v1_parity_contract,
    )
except Exception:
    MARKET_SNAPSHOT_SCHEMA_VERSION = "market_snapshot_v2"
    MARKET_SNAPSHOT_CONTRACT_VERSION = "phase3_step1"

    def build_v1_parity_contract() -> dict:
        return {
            "benchmark_repo": "tonyang660/crypto-signal-bot",
            "mode": "v1_parity_first",
            "behavior_policy": "Fallback contract loaded; install market_snapshot_contract.py.",
        }


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
SNAPSHOT_SCHEMA_VERSION = MARKET_SNAPSHOT_SCHEMA_VERSION


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def build_fetch_error_payload(error: str, payload: dict | None = None) -> dict:
    result = {
        "healthy": False,
        "reason_codes": [error],
        "source": "feature_factory",
    }

    if payload is not None:
        result["data_hub_payload"] = payload

    return result


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
        return None, {}, build_fetch_error_payload("DATA_HUB_REQUEST_FAILED")

    if not payload.get("ok"):
        return None, payload.get("metadata", {}), build_fetch_error_payload(
            payload.get("error", "DATA_HUB_ERROR"),
            payload=payload,
        )

    candles = payload.get("candles", [])
    metadata = payload.get("metadata", {}) or {}

    if len(candles) != limit:
        return candles, metadata, build_fetch_error_payload(
            "INSUFFICIENT_CANDLE_DATA",
            payload={
                "requested_limit": limit,
                "received_count": len(candles),
                "metadata": metadata,
            },
        )

    return candles, metadata, None


def build_timeframe_data_quality(
    timeframe: str,
    limit: int,
    candles: list[dict] | None,
    metadata: dict | None,
    fetch_error: dict | None = None,
) -> dict:
    metadata = metadata or {}
    status = metadata.get("status", {}) or {}

    reason_codes = []
    if fetch_error:
        reason_codes.extend(fetch_error.get("reason_codes", ["FETCH_ERROR"]))

    reason_codes.extend(status.get("reason_codes", []) or [])

    candle_count = len(candles or [])
    if candle_count < limit and "INSUFFICIENT_CANDLE_DATA" not in reason_codes:
        reason_codes.append("INSUFFICIENT_CANDLE_DATA")

    seen = set()
    deduped_reason_codes = []
    for reason in reason_codes:
        if reason not in seen:
            deduped_reason_codes.append(reason)
            seen.add(reason)

    data_hub_healthy = status.get("healthy")
    if data_hub_healthy is None:
        data_hub_healthy = fetch_error is None and candle_count >= limit

    healthy = bool(data_hub_healthy) and not deduped_reason_codes and candle_count >= limit

    return {
        "healthy": healthy,
        "reason_codes": deduped_reason_codes,
        "timeframe": timeframe,
        "requested_rows": limit,
        "received_rows": candle_count,
        "provider": metadata.get("provider") or status.get("provider"),
        "market": metadata.get("market") or status.get("market"),
        "stored_rows": metadata.get("stored_rows") or status.get("stored_rows"),
        "first_timestamp": metadata.get("first_timestamp") or status.get("first_timestamp"),
        "last_timestamp": metadata.get("last_timestamp") or status.get("last_timestamp"),
        "last_age_seconds": status.get("last_age_seconds"),
        "is_stale": status.get("is_stale"),
        "has_min_rows": status.get("has_min_rows"),
        "gap_count": status.get("gap_count"),
        "gaps": status.get("gaps", []),
        "source": "data_hub",
        "raw_status": status,
    }


def aggregate_data_quality(timeframe_quality: dict) -> dict:
    reason_codes = []
    for item in timeframe_quality.values():
        for reason in item.get("reason_codes", []):
            reason_codes.append(f"{item.get('timeframe')}:{reason}")

    return {
        "healthy": all(item.get("healthy", False) for item in timeframe_quality.values()),
        "reason_codes": reason_codes,
        "timeframes": timeframe_quality,
    }


def latest_candle_payload(candles: list[dict]) -> dict:
    if not candles:
        return {}
    last = dict(candles[-1])
    result = {
        "timestamp": last.get("timestamp"),
        "open": float(last.get("open", 0.0)),
        "high": float(last.get("high", 0.0)),
        "low": float(last.get("low", 0.0)),
        "close": float(last.get("close", 0.0)),
        "volume": float(last.get("volume", 0.0)),
    }
    for key in ("volume_contracts", "volume_base", "volume_quote", "confirm", "provider_ts"):
        if key in last:
            result[key] = last[key]
    return result


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
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


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
    if rsi_value < 45:
        return "bearish_but_not_oversold"
    if rsi_value <= 55:
        return "neutral"
    if rsi_value < 70:
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
    return {"atr": atr, "atr_percent": atr_percent, "volatility_state": state}


def compute_price_action(df: pd.DataFrame, indicators: dict, structure: dict) -> dict:
    candles = df.copy().reset_index(drop=True)
    last_close = float(candles["close"].iloc[-1])
    atr_value = float(indicators["atr"])
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
        prior_high = float(candles["high"].iloc[idx - 5:idx].max())
        prior_low = float(candles["low"].iloc[idx - 5:idx].min())
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
        pullback_bars_ago = len(candles) - 1 - (last_high_idx if dist_to_high <= dist_to_low else last_low_idx)
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
    impulse_to_correction_ratio = impulse_strength_score / correction_strength_score if correction_strength_score > 0 else 999.0
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
    wick_rejection_score = clamp(max(upper_wick, lower_wick) / body, 0.0, 1.0) if body > 0 else 0.0
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
    candles, metadata, fetch_error = fetch_candles(symbol, timeframe, fetch_limit)
    data_quality = build_timeframe_data_quality(timeframe, fetch_limit, candles, metadata, fetch_error)
    if fetch_error:
        return None, {"timeframe": timeframe, "error": "market_data_fetch_failed", "data_quality": data_quality}
    if not data_quality.get("healthy", False):
        return None, {"timeframe": timeframe, "error": "market_data_unhealthy", "data_quality": data_quality}
    if len(candles) < fetch_limit:
        return None, {"timeframe": timeframe, "error": "insufficient_candle_data", "data_quality": data_quality}
    df = to_dataframe(candles)
    indicators = compute_indicators(df)
    structure = compute_structure(df, indicators)
    price_action = compute_price_action(df, indicators, structure)
    volatility = compute_volatility(df, indicators)
    emitted_candles = candles[-emit_limit:]
    return {
        "timeframe": timeframe,
        "window_size": emit_limit,
        "fetch_window_size": fetch_limit,
        "data_quality": data_quality,
        "latest": latest_candle_payload(candles),
        "candles": emitted_candles,
        "indicators": indicators,
        "structure": structure,
        "price_action": price_action,
        "volatility": volatility,
    }, None


def build_multi_timeframe_context(timeframes: dict) -> dict:
    entry_tf = "5m"
    primary_tf = "15m"
    htf = "4h"
    def trend(tf: str) -> str | None:
        return timeframes.get(tf, {}).get("structure", {}).get("trend_direction")
    entry_trend = trend(entry_tf)
    primary_trend = trend(primary_tf)
    htf_trend = trend(htf)
    aligned = entry_trend is not None and primary_trend is not None and htf_trend is not None and entry_trend == primary_trend == htf_trend and entry_trend != "neutral"
    return {
        "entry_timeframe": entry_tf,
        "primary_timeframe": primary_tf,
        "higher_timeframe": htf,
        "alignment": {
            "entry_trend": entry_trend,
            "primary_trend": primary_trend,
            "higher_timeframe_trend": htf_trend,
            "fully_aligned": aligned,
        },
    }


def build_market_snapshot(symbol: str):
    symbol = normalize_symbol(symbol)
    timeframes = {}
    timeframe_quality = {}
    missing = []
    for tf in TIMEFRAMES:
        block, error = build_timeframe_block(symbol, tf)
        if error:
            missing.append(error)
            dq = error.get("data_quality")
            if dq:
                timeframe_quality[tf] = dq
        else:
            timeframes[tf] = block
            timeframe_quality[tf] = block["data_quality"]
    data_quality = aggregate_data_quality(timeframe_quality)
    if missing:
        return None, {
            "ok": False,
            "error": "snapshot_build_failed",
            "reason_codes": ["MARKET_DATA_QUALITY_FAILED"],
            "symbol": symbol,
            "data_quality": data_quality,
            "details": missing,
        }
    generated_at = iso_now()
    snapshot = {
        "snapshot_meta": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "feature_factory_version": FEATURE_FACTORY_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
            "contract_version": MARKET_SNAPSHOT_CONTRACT_VERSION,
        },
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "snapshot_timestamp": generated_at,
        "source": SERVICE_NAME,
        "v1_parity": build_v1_parity_contract(),
        "data_quality": data_quality,
        "multi_timeframe_context": build_multi_timeframe_context(timeframes),
        "timeframes": timeframes,
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
                "env": os.getenv("APP_ENV", "unknown"),
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "contract_version": MARKET_SNAPSHOT_CONTRACT_VERSION,
            })
            return
        if self.path.startswith("/snapshot"):
            query = parse_qs(urlparse(self.path).query)
            symbol = query.get("symbol", [None])[0]
            if not symbol:
                self._send_json({"ok": False, "error": "missing_parameters", "required": ["symbol"]}, status=400)
                return
            snapshot, error = build_market_snapshot(symbol)
            if error:
                self._send_json(error, status=400)
                return
            self._send_json(snapshot)
            return
        self._send_json({"ok": False, "error": "not_found", "path": self.path}, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
