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
INDICATOR_CONTRACT_VERSION = "v1_indicator_parity_step3"
STRUCTURE_CONTRACT_VERSION = "v1_structure_parity_step4"
REGIME_INPUTS_CONTRACT_VERSION = "v1_volatility_regime_inputs_step5"
MULTI_TIMEFRAME_CONTEXT_CONTRACT_VERSION = "v1_multi_timeframe_context_step6"
FEATURE_FACTORY_ENDPOINT_CONTRACT_VERSION = "feature_factory_endpoint_cleanup_step7"

# V1 crypto-signal-bot indicator parameters.
# Keep these explicit here so Feature Factory's output contract is readable.
EMA_FAST_PERIOD = 21
EMA_MEDIUM_PERIOD = 50
EMA_SLOW_PERIOD = 200
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
ATR_PERIOD = 14
ATR_SMA_PERIOD = 20
RSI_PERIOD = 14
ADX_PERIOD = 14
VOLUME_SMA_PERIOD = 100


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def finite_float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)

    if not np.isfinite(result):
        return float(default)

    return result


def safe_pct(numerator: float, denominator: float, default: float = 0.0) -> float:
    denominator = finite_float(denominator)
    if denominator == 0:
        return float(default)
    return finite_float((finite_float(numerator) / denominator) * 100.0, default)


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
            code = f"{item.get('timeframe')}:{reason}"
            reason_codes.append(code)

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
        "open": finite_float(last.get("open")),
        "high": finite_float(last.get("high")),
        "low": finite_float(last.get("low")),
        "close": finite_float(last.get("close")),
        "volume": finite_float(last.get("volume")),
    }

    for key in ("volume_contracts", "volume_base", "volume_quote", "confirm", "provider_ts"):
        if key in last:
            result[key] = last[key]

    return result


def to_dataframe(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx.fillna(0.0)


def compute_macd(close: pd.Series):
    ema_fast = compute_ema(close, MACD_FAST_PERIOD)
    ema_slow = compute_ema(close, MACD_SLOW_PERIOD)
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=MACD_SIGNAL_PERIOD, adjust=False).mean()
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


def build_indicator_meta() -> dict:
    return {
        "contract_version": INDICATOR_CONTRACT_VERSION,
        "v1_parity_status": "indicator_names_and_periods_aligned",
        "ema_fast_period": EMA_FAST_PERIOD,
        "ema_medium_period": EMA_MEDIUM_PERIOD,
        "ema_slow_period": EMA_SLOW_PERIOD,
        "macd_fast_period": MACD_FAST_PERIOD,
        "macd_slow_period": MACD_SLOW_PERIOD,
        "macd_signal_period": MACD_SIGNAL_PERIOD,
        "atr_period": ATR_PERIOD,
        "atr_sma_period": ATR_SMA_PERIOD,
        "rsi_period": RSI_PERIOD,
        "adx_period": ADX_PERIOD,
        "volume_sma_period": VOLUME_SMA_PERIOD,
        "notes": [
            "EMA/ATR/RSI/ADX are implemented with pandas smoothing for dependency-light runtime.",
            "Indicator names and periods now match the v1 crypto-signal-bot contract.",
        ],
    }


def compute_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    volume = df["volume"]

    ema_fast = compute_ema(close, EMA_FAST_PERIOD)
    ema_medium = compute_ema(close, EMA_MEDIUM_PERIOD)
    ema_slow = compute_ema(close, EMA_SLOW_PERIOD)

    rsi = compute_rsi(close, RSI_PERIOD)
    atr = compute_atr(df, ATR_PERIOD)
    atr_sma = atr.rolling(window=ATR_SMA_PERIOD, min_periods=1).mean()
    adx = compute_adx(df, ADX_PERIOD)
    macd, macd_signal, macd_hist = compute_macd(close)
    volume_sma = volume.rolling(window=VOLUME_SMA_PERIOD, min_periods=1).mean()

    latest_close = finite_float(close.iloc[-1])
    latest_ema_fast = finite_float(ema_fast.iloc[-1])
    latest_ema_medium = finite_float(ema_medium.iloc[-1])
    latest_ema_slow = finite_float(ema_slow.iloc[-1])
    latest_rsi = finite_float(rsi.iloc[-1], 50.0)
    latest_atr = finite_float(atr.iloc[-1])
    latest_atr_sma = finite_float(atr_sma.iloc[-1])
    latest_adx = finite_float(adx.iloc[-1])
    latest_macd = finite_float(macd.iloc[-1])
    latest_macd_signal = finite_float(macd_signal.iloc[-1])
    latest_macd_hist = finite_float(macd_hist.iloc[-1])
    prev_macd_hist = finite_float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else latest_macd_hist

    atr_percent = safe_pct(latest_atr, latest_close)
    atr_ratio = finite_float(latest_atr / latest_atr_sma, 1.0) if latest_atr_sma != 0 else 1.0
    ema_fast_medium_spread_pct = safe_pct(latest_ema_fast - latest_ema_medium, latest_ema_medium)
    ema_fast_slow_spread_pct = safe_pct(latest_ema_fast - latest_ema_slow, latest_ema_slow)
    ema_medium_slow_spread_pct = safe_pct(latest_ema_medium - latest_ema_slow, latest_ema_slow)
    macd_histogram_slope = finite_float(latest_macd_hist - prev_macd_hist)

    return {
        "indicator_meta": build_indicator_meta(),

        # V1 canonical names and values.
        "ema_fast": latest_ema_fast,
        "ema_medium": latest_ema_medium,
        "ema_slow": latest_ema_slow,
        "macd": latest_macd,
        "macd_signal": latest_macd_signal,
        "macd_hist": latest_macd_hist,
        "atr": latest_atr,
        "atr_sma": latest_atr_sma,
        "rsi": latest_rsi,
        "adx": latest_adx,
        "volume_sma": finite_float(volume_sma.iloc[-1]),

        # Explicit period-labelled aliases.
        "ema_21": latest_ema_fast,
        "ema_50": latest_ema_medium,
        "ema_200": latest_ema_slow,
        "atr_14": latest_atr,
        "atr_sma_20": latest_atr_sma,
        "rsi_14": latest_rsi,
        "adx_14": latest_adx,
        "volume_sma_100": finite_float(volume_sma.iloc[-1]),

        # Backward-compatible aliases used by existing TradeTower code.
        "macd_histogram": latest_macd_hist,
        "price_vs_ema_fast_pct": safe_pct(latest_close - latest_ema_fast, latest_ema_fast),
        "price_vs_ema_medium_pct": safe_pct(latest_close - latest_ema_medium, latest_ema_medium),
        "price_vs_ema_slow_pct": safe_pct(latest_close - latest_ema_slow, latest_ema_slow),
        "ema_separation_pct": ema_fast_slow_spread_pct,
        "ema_fast_medium_spread_pct": ema_fast_medium_spread_pct,
        "ema_fast_slow_spread_pct": ema_fast_slow_spread_pct,
        "ema_medium_slow_spread_pct": ema_medium_slow_spread_pct,
        "macd_histogram_slope": macd_histogram_slope,
        "rsi_state": classify_rsi_state(latest_rsi),
        "atr_percent": atr_percent,
        "atr_ratio": atr_ratio,
    }



def get_trend_direction_v1(df: pd.DataFrame) -> str:
    """
    V1-compatible trend direction based on EMA 21/50/200 alignment and
    momentum/strong-price-action fallbacks.

    Returns: bullish, bearish, or neutral.
    """
    try:
        last_price = finite_float(df["close"].iloc[-1])
        ema_fast = finite_float(df["ema_fast"].iloc[-1])
        ema_medium = finite_float(df["ema_medium"].iloc[-1])
        ema_slow = finite_float(df["ema_slow"].iloc[-1])

        if last_price > ema_fast and ema_fast > ema_medium and ema_medium > ema_slow:
            return "bullish"

        if last_price > ema_fast and last_price > ema_medium and ema_fast > ema_medium:
            ema_fast_above_medium = (ema_fast - ema_medium) / ema_medium if ema_medium else 0.0
            if ema_fast_above_medium > 0.005:
                return "bullish"

        if last_price > ema_fast and last_price > ema_medium and last_price > ema_slow:
            price_above_slow = (last_price - ema_slow) / ema_slow if ema_slow else 0.0
            if price_above_slow > 0.02:
                return "bullish"

        if last_price < ema_fast and ema_fast < ema_medium and ema_medium < ema_slow:
            return "bearish"

        if last_price < ema_fast and last_price < ema_medium and ema_fast < ema_medium:
            ema_fast_below_medium = (ema_medium - ema_fast) / ema_medium if ema_medium else 0.0
            if ema_fast_below_medium > 0.005:
                return "bearish"

        if last_price < ema_fast and last_price < ema_medium and last_price < ema_slow:
            price_below_slow = (ema_slow - last_price) / ema_slow if ema_slow else 0.0
            if price_below_slow > 0.02:
                return "bearish"

        return "neutral"
    except Exception:
        return "neutral"


def find_swing_low(df: pd.DataFrame, lookback: int = 20) -> float | None:
    if len(df) < 1:
        return None
    return finite_float(df.tail(lookback)["low"].min())


def find_swing_high(df: pd.DataFrame, lookback: int = 20) -> float | None:
    if len(df) < 1:
        return None
    return finite_float(df.tail(lookback)["high"].max())


def detect_break_of_structure(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 20,
    confirmation_bars: int = 20,
) -> tuple[bool, int, float]:
    """
    V1-compatible BOS detection.

    For long: recent high breaks above prior swing high.
    For short: recent low breaks below prior swing low.
    """
    if len(df) < lookback + confirmation_bars:
        return False, 0, 0.0

    historical_df = df.iloc[:-confirmation_bars] if confirmation_bars > 0 else df
    if len(historical_df) < lookback:
        return False, 0, 0.0

    recent_df = df.tail(confirmation_bars)

    if direction == "long":
        structure_level = finite_float(historical_df.tail(lookback)["high"].max())
        for i in range(len(recent_df) - 1, -1, -1):
            if finite_float(recent_df.iloc[i]["high"]) > structure_level:
                bars_ago = len(recent_df) - 1 - i
                return True, int(bars_ago), structure_level
        return False, 0, structure_level

    if direction == "short":
        structure_level = finite_float(historical_df.tail(lookback)["low"].min())
        for i in range(len(recent_df) - 1, -1, -1):
            if finite_float(recent_df.iloc[i]["low"]) < structure_level:
                bars_ago = len(recent_df) - 1 - i
                return True, int(bars_ago), structure_level
        return False, 0, structure_level

    return False, 0, 0.0


def get_bos_quality_score(bos_detected: bool, bars_ago: int, max_points: int = 15) -> tuple[int, str]:
    if not bos_detected:
        return 0, "No break of structure detected"

    if bars_ago <= 3:
        return int(max_points), f"Fresh BOS within {bars_ago} bars"
    if bars_ago <= 7:
        return int(round(max_points * 0.77)), f"Recent BOS {bars_ago} bars ago"
    if bars_ago <= 12:
        return int(round(max_points * 0.46)), f"Older BOS {bars_ago} bars ago"

    return int(round(max_points * 0.2)), f"Stale BOS {bars_ago} bars ago"


def analyze_mean_reversion_range(df: pd.DataFrame, lookback: int = 24) -> dict:
    """V1-compatible local sideways range analysis for mean reversion inputs."""
    if len(df) < lookback:
        return {
            "valid": False,
            "reason": f"Need at least {lookback} bars for local range analysis",
        }

    recent = df.tail(lookback)
    current_price = finite_float(df["close"].iloc[-1])
    support = finite_float(recent["low"].min())
    resistance = finite_float(recent["high"].max())
    range_width = resistance - support

    if range_width <= 0:
        return {"valid": False, "reason": "Invalid local range width"}

    atr = finite_float(df["atr"].iloc[-1]) if "atr" in df.columns else 0.0
    atr_sma = finite_float(df["atr_sma"].iloc[-1]) if "atr_sma" in df.columns else atr
    atr_ratio = finite_float(atr / atr_sma, 1.0) if atr_sma else 1.0
    range_width_atr = finite_float(range_width / atr, 0.0) if atr else 0.0
    range_position = finite_float((current_price - support) / range_width, 0.5)
    range_position = clamp(range_position, 0.0, 1.0)

    buffer = 0.15 * atr if atr else 0.0
    recent_closes = recent["close"].tail(8)
    closes_above = int((recent_closes > resistance + buffer).sum())
    closes_below = int((recent_closes < support - buffer).sum())
    last_close = finite_float(recent["close"].iloc[-1])
    previous_close = finite_float(recent["close"].iloc[-2]) if len(recent) > 1 else last_close
    upper_pressure = range_position >= 0.85 and last_close > previous_close
    lower_pressure = range_position <= 0.15 and last_close < previous_close

    adx = finite_float(df["adx"].iloc[-1]) if "adx" in df.columns else 0.0
    ema_fast = finite_float(df["ema_fast"].iloc[-1]) if "ema_fast" in df.columns else current_price
    ema_slow = finite_float(df["ema_slow"].iloc[-1]) if "ema_slow" in df.columns else current_price
    ema_spread_pct = abs(ema_fast - ema_slow) / current_price if current_price else 0.0

    breakout_risk_reasons = []
    if closes_above or closes_below:
        breakout_risk_reasons.append("recent close outside range")
    if atr_ratio > 1.0:
        breakout_risk_reasons.append(f"ATR expanding ({atr_ratio:.2f}x avg)")
    if adx > 16:
        breakout_risk_reasons.append(f"ADX too high ({adx:.1f})")
    if ema_spread_pct > 0.01:
        breakout_risk_reasons.append(f"EMA spread too wide ({ema_spread_pct * 100:.2f}%)")
    if range_width_atr < 1.5:
        breakout_risk_reasons.append(f"range too tight ({range_width_atr:.1f} ATR)")
    if range_width_atr > 5.0:
        breakout_risk_reasons.append(f"range too wide ({range_width_atr:.1f} ATR)")
    if upper_pressure:
        breakout_risk_reasons.append("price pressing upper boundary")
    if lower_pressure:
        breakout_risk_reasons.append("price pressing lower boundary")

    return {
        "valid": len(breakout_risk_reasons) == 0,
        "support": support,
        "resistance": resistance,
        "width": finite_float(range_width),
        "position": range_position,
        "atr": atr,
        "atr_ratio": atr_ratio,
        "range_width_atr": range_width_atr,
        "buffer": finite_float(buffer),
        "adx": adx,
        "ema_spread_pct": finite_float(ema_spread_pct),
        "closes_above": closes_above,
        "closes_below": closes_below,
        "upper_pressure": bool(upper_pressure),
        "lower_pressure": bool(lower_pressure),
        "breakout_risk_reasons": breakout_risk_reasons,
        "reason": "; ".join(breakout_risk_reasons) if breakout_risk_reasons else "Contained local range",
    }

def compute_structure(df: pd.DataFrame, indicators: dict) -> dict:
    work = df.copy().reset_index(drop=True)

    # Attach v1 canonical indicator columns so the structure helpers operate on
    # the same names as crypto-signal-bot.
    work["ema_fast"] = compute_ema(work["close"], EMA_FAST_PERIOD)
    work["ema_medium"] = compute_ema(work["close"], EMA_MEDIUM_PERIOD)
    work["ema_slow"] = compute_ema(work["close"], EMA_SLOW_PERIOD)
    work["atr"] = compute_atr(work, ATR_PERIOD)
    work["atr_sma"] = work["atr"].rolling(window=ATR_SMA_PERIOD, min_periods=1).mean()
    work["adx"] = compute_adx(work, ADX_PERIOD)

    recent = work.tail(20).copy()
    highs = recent["high"].tolist()
    lows = recent["low"].tolist()

    higher_highs = highs[-1] > highs[-5] if len(highs) >= 5 else False
    higher_lows = lows[-1] > lows[-5] if len(lows) >= 5 else False
    lower_highs = highs[-1] < highs[-5] if len(highs) >= 5 else False
    lower_lows = lows[-1] < lows[-5] if len(lows) >= 5 else False

    trend_direction_v1 = get_trend_direction_v1(work)
    trend_direction = {
        "bullish": "up",
        "bearish": "down",
        "neutral": "neutral",
    }.get(trend_direction_v1, "neutral")

    range_high = finite_float(recent["high"].max())
    range_low = finite_float(recent["low"].min())
    current_close = finite_float(work["close"].iloc[-1])
    range_span = range_high - range_low

    if range_span <= 0:
        dist_high = 0.0
        dist_low = 0.0
    else:
        dist_high = finite_float(((range_high - current_close) / range_span) * 100)
        dist_low = finite_float(((current_close - range_low) / range_span) * 100)

    atr_pct = finite_float(indicators.get("atr_percent"))
    if (higher_highs and higher_lows) or (lower_highs and lower_lows):
        market_type = "trend"
    elif atr_pct < 0.35:
        market_type = "range"
    else:
        market_type = "transition"

    if higher_highs and higher_lows and not lower_highs and not lower_lows:
        swing_bias = "bullish"
        structure_state = "clean_trend"
    elif lower_highs and lower_lows and not higher_highs and not lower_lows:
        swing_bias = "bearish"
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

    ema_fast = indicators["ema_fast"]
    ema_medium = indicators["ema_medium"]
    ema_slow = indicators["ema_slow"]
    macd = indicators["macd"]
    macd_signal = indicators["macd_signal"]
    price_vs_ema_slow_pct = indicators["price_vs_ema_slow_pct"]

    trend_consistency_score = 0.0
    if (ema_fast > ema_medium and ema_medium > ema_slow and higher_highs and higher_lows) or (ema_fast < ema_medium and ema_medium < ema_slow and lower_highs and lower_lows):
        trend_consistency_score += 50
    if (macd > macd_signal and ema_fast > ema_slow) or (macd < macd_signal and ema_fast < ema_slow):
        trend_consistency_score += 25
    if abs(price_vs_ema_slow_pct) > 1.0:
        trend_consistency_score += 15
    if market_type == "transition":
        trend_consistency_score -= 20
    trend_consistency_score = clamp(trend_consistency_score, 0.0, 100.0)

    swing_high = find_swing_high(work, lookback=20)
    swing_low = find_swing_low(work, lookback=20)

    bullish_bos, bullish_bars_ago, bullish_level = detect_break_of_structure(work, "long", lookback=20, confirmation_bars=20)
    bearish_bos, bearish_bars_ago, bearish_level = detect_break_of_structure(work, "short", lookback=20, confirmation_bars=20)
    bullish_bos_points, bullish_bos_details = get_bos_quality_score(bullish_bos, bullish_bars_ago, max_points=15)
    bearish_bos_points, bearish_bos_details = get_bos_quality_score(bearish_bos, bearish_bars_ago, max_points=15)

    mean_reversion_range = analyze_mean_reversion_range(work, lookback=24)

    return {
        "structure_contract_version": STRUCTURE_CONTRACT_VERSION,
        "v1_parity_status": "structure_names_and_core_algorithms_aligned",

        # Backward-compatible TradeTower fields.
        "trend_direction": trend_direction,
        "market_type": market_type,
        "higher_highs": bool(higher_highs),
        "higher_lows": bool(higher_lows),
        "lower_highs": bool(lower_highs),
        "lower_lows": bool(lower_lows),
        "range_high": range_high,
        "range_low": range_low,
        "distance_to_range_high_pct": dist_high,
        "distance_to_range_low_pct": dist_low,
        "structure_state": structure_state,
        "structure_quality_score": structure_quality_score,
        "swing_bias": swing_bias,
        "trend_consistency_score": trend_consistency_score,

        # V1 canonical structure outputs.
        "v1_trend_direction": trend_direction_v1,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "break_of_structure": {
            "bullish": {
                "detected": bool(bullish_bos),
                "bars_ago": int(bullish_bars_ago),
                "structure_level": finite_float(bullish_level),
                "quality_points": int(bullish_bos_points),
                "quality_details": bullish_bos_details,
            },
            "bearish": {
                "detected": bool(bearish_bos),
                "bars_ago": int(bearish_bars_ago),
                "structure_level": finite_float(bearish_level),
                "quality_points": int(bearish_bos_points),
                "quality_details": bearish_bos_details,
            },
        },
        "mean_reversion_range": mean_reversion_range,
    }

def compute_volatility(df: pd.DataFrame, indicators: dict) -> dict:
    last_close = finite_float(df["close"].iloc[-1])
    atr = finite_float(indicators["atr"])
    atr_sma = finite_float(indicators.get("atr_sma"))

    atr_percent = safe_pct(atr, last_close)
    atr_ratio = finite_float(atr / atr_sma, 1.0) if atr_sma != 0 else 1.0

    if atr_ratio < 0.7:
        state = "low"
    elif atr_ratio <= 2.0:
        state = "normal"
    elif atr_ratio < 3.0:
        state = "high"
    else:
        state = "extreme"

    return {
        "atr": atr,
        "atr_sma": atr_sma,
        "atr_percent": atr_percent,
        "atr_ratio": atr_ratio,
        "volatility_state": state,
        "v1_volatility_min_ratio": 0.7,
        "v1_volatility_max_ratio": 2.0,
        "v1_extreme_volatility_multiplier": 3.0,
    }


def compute_ema_slope_pct(df: pd.DataFrame, ema_col: str = "ema_medium", periods: int = 20) -> float:
    if ema_col not in df.columns or len(df) < periods:
        return 0.0

    ema_values = df[ema_col].tail(periods)
    start_ema = finite_float(ema_values.iloc[0])
    end_ema = finite_float(ema_values.iloc[-1])

    if start_ema == 0:
        return 0.0

    return safe_pct(end_ema - start_ema, start_ema)


def detect_price_velocity(df: pd.DataFrame, lookback_bars: int = 16) -> float:
    if len(df) < lookback_bars + 1:
        return 0.0

    price_current = finite_float(df["close"].iloc[-1])
    price_past = finite_float(df["close"].iloc[-lookback_bars])

    if price_past == 0:
        return 0.0

    return finite_float((price_current - price_past) / price_past)


def detect_strong_primary_trend_inputs(df: pd.DataFrame, direction: str) -> dict:
    trend_direction = get_trend_direction_v1(df)

    if direction == "long" and trend_direction != "bullish":
        return {
            "detected": False,
            "reason": f"Primary trend ({trend_direction}) opposes direction",
        }

    if direction == "short" and trend_direction != "bearish":
        return {
            "detected": False,
            "reason": f"Primary trend ({trend_direction}) opposes direction",
        }

    if "macd_hist" not in df.columns or len(df) < 3:
        return {
            "detected": False,
            "reason": "Insufficient MACD data",
        }

    macd_hist = [finite_float(v) for v in df["macd_hist"].tail(3).values]

    if direction == "long":
        accelerating = macd_hist[-1] > macd_hist[-2] > macd_hist[-3] and macd_hist[-1] > 0
    else:
        accelerating = macd_hist[-1] < macd_hist[-2] < macd_hist[-3] and macd_hist[-1] < 0

    if not accelerating:
        return {
            "detected": False,
            "reason": "MACD not accelerating in direction",
            "macd_hist_tail": macd_hist,
        }

    return {
        "detected": True,
        "reason": "Accelerating MACD with aligned primary trend",
        "macd_hist_tail": macd_hist,
    }


def detect_fast_rally_inputs(df: pd.DataFrame, direction: str) -> dict:
    velocity_short = detect_price_velocity(df, 6)   # v1: 1.5h on 15m primary
    velocity_medium = detect_price_velocity(df, 12) # v1: 3h on 15m primary
    strong_primary = detect_strong_primary_trend_inputs(df, direction)

    detected = False
    strength = "none"

    if strong_primary.get("detected"):
        if direction == "long":
            if velocity_short > 0.05:
                detected = True
                strength = "explosive"
            elif velocity_short > 0.03 or velocity_medium > 0.045:
                detected = True
                strength = "strong"
            elif velocity_short > 0.015:
                detected = True
                strength = "moderate"
        else:
            if velocity_short < -0.05:
                detected = True
                strength = "explosive"
            elif velocity_short < -0.03 or velocity_medium < -0.045:
                detected = True
                strength = "strong"
            elif velocity_short < -0.015:
                detected = True
                strength = "moderate"

    return {
        "detected": detected,
        "strength": strength,
        "velocity_short": velocity_short,
        "velocity_medium": velocity_medium,
        "strong_primary_trend": strong_primary,
    }


def detect_regime_v1(df: pd.DataFrame, period: int = 20) -> tuple[str, dict]:
    required_columns = {
        "close",
        "high",
        "low",
        "ema_fast",
        "ema_medium",
        "ema_slow",
        "atr",
        "atr_sma",
        "adx",
    }

    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        return "Sideways", {
            "reason": "missing_columns",
            "missing_columns": missing_columns,
        }

    if len(df) < max(period, 50):
        return "Sideways", {
            "reason": "not_enough_data",
            "required_rows": max(period, 50),
            "actual_rows": len(df),
        }

    trend_direction = get_trend_direction_v1(df)
    ema_slope_pct = compute_ema_slope_pct(df, "ema_medium", period)
    adx = finite_float(df["adx"].iloc[-1])
    current_atr = finite_float(df["atr"].iloc[-1])
    avg_atr = finite_float(df["atr_sma"].iloc[-1])
    atr_ratio = current_atr / avg_atr if avg_atr else 1.0

    recent = df.tail(50)
    current_close = finite_float(df["close"].iloc[-1])
    range_pct = (
        (finite_float(recent["high"].max()) - finite_float(recent["low"].min())) / current_close
        if current_close else 0.0
    )
    ema_spread_pct = (
        abs(finite_float(df["ema_fast"].iloc[-1]) - finite_float(df["ema_slow"].iloc[-1])) / current_close
        if current_close else 0.0
    )

    thresholds = {
        "uptrend_threshold": 0.25,
        "downtrend_threshold": -0.25,
        "min_trend_adx": 18,
        "sideways_max_adx": 16,
        "sideways_max_range_pct": 0.035,
        "sideways_max_ema_spread_pct": 0.012,
        "sideways_max_atr_ratio": 1.15,
    }

    if trend_direction == "bullish" and (ema_slope_pct > thresholds["uptrend_threshold"] or adx >= thresholds["min_trend_adx"]):
        regime = "Uptrend"
        reason = "bullish_structure_with_slope_or_adx"
    elif trend_direction == "bearish" and (ema_slope_pct < thresholds["downtrend_threshold"] or adx >= thresholds["min_trend_adx"]):
        regime = "Downtrend"
        reason = "bearish_structure_with_slope_or_adx"
    elif (
        trend_direction == "neutral"
        and abs(ema_slope_pct) < thresholds["uptrend_threshold"]
        and adx <= thresholds["sideways_max_adx"]
        and range_pct <= thresholds["sideways_max_range_pct"]
        and ema_spread_pct <= thresholds["sideways_max_ema_spread_pct"]
        and atr_ratio <= thresholds["sideways_max_atr_ratio"]
    ):
        regime = "Sideways"
        reason = "neutral_compressed_low_trend_strength"
    elif ema_slope_pct > thresholds["uptrend_threshold"]:
        regime = "Uptrend"
        reason = "positive_ema_medium_slope"
    elif ema_slope_pct < thresholds["downtrend_threshold"]:
        regime = "Downtrend"
        reason = "negative_ema_medium_slope"
    else:
        regime = "Sideways"
        reason = "default_sideways"

    inputs = {
        "trend_direction": trend_direction,
        "ema_slope_pct": ema_slope_pct,
        "adx": adx,
        "atr_ratio": finite_float(atr_ratio, 1.0),
        "range_pct": finite_float(range_pct),
        "ema_spread_pct": finite_float(ema_spread_pct),
        "thresholds": thresholds,
        "reason": reason,
    }

    return regime, inputs


def get_regime_strategy(regime: str) -> str:
    if regime in ("Uptrend", "Downtrend"):
        return "Trend-Following"
    if regime == "Sideways":
        return "Mean-Reversion"
    return "Trend-Following"


def check_btc_macro_regime_inputs(df: pd.DataFrame) -> dict:
    btc_trend = get_trend_direction_v1(df)
    btc_rsi = finite_float(df["rsi"].iloc[-1]) if "rsi" in df.columns else 50.0

    adjustments = {
        "score_threshold_adj": 0,
        "position_size_mult": 1.0,
        "max_signals_adj": 0,
    }

    if btc_trend == "bullish" and 30 < btc_rsi < 70:
        adjustments.update({
            "score_threshold_adj": -5,
            "position_size_mult": 1.1,
            "max_signals_adj": 1,
        })
        regime = "favorable_long"
        reason = f"BTC is bullish (RSI: {btc_rsi:.1f})"
    elif btc_trend == "bearish" and 30 < btc_rsi < 70:
        adjustments.update({
            "score_threshold_adj": -5,
            "position_size_mult": 1.1,
            "max_signals_adj": 1,
        })
        regime = "favorable_short"
        reason = f"BTC is bearish (RSI: {btc_rsi:.1f})"
    elif btc_rsi > 75:
        adjustments.update({
            "score_threshold_adj": 10,
            "position_size_mult": 0.7,
            "max_signals_adj": -1,
        })
        regime = "extended"
        reason = f"BTC is overbought (RSI: {btc_rsi:.1f}), caution on new longs"
    elif btc_rsi < 25:
        adjustments.update({
            "score_threshold_adj": 10,
            "position_size_mult": 0.7,
            "max_signals_adj": -1,
        })
        regime = "extended"
        reason = f"BTC is oversold (RSI: {btc_rsi:.1f}), caution on new shorts"
    else:
        adjustments.update({
            "score_threshold_adj": 5,
            "position_size_mult": 0.9,
            "max_signals_adj": 0,
        })
        regime = "neutral"
        reason = f"BTC is in a neutral state (RSI: {btc_rsi:.1f})"

    return {
        "regime": regime,
        "reason": reason,
        "btc_trend": btc_trend,
        "btc_rsi": btc_rsi,
        **adjustments,
    }


def compute_regime_inputs(df: pd.DataFrame, indicators: dict, structure: dict, volatility: dict) -> dict:
    work = df.copy().reset_index(drop=True)

    work["ema_fast"] = compute_ema(work["close"], EMA_FAST_PERIOD)
    work["ema_medium"] = compute_ema(work["close"], EMA_MEDIUM_PERIOD)
    work["ema_slow"] = compute_ema(work["close"], EMA_SLOW_PERIOD)
    macd, macd_signal, macd_hist = compute_macd(work["close"])
    work["macd"] = macd
    work["macd_signal"] = macd_signal
    work["macd_hist"] = macd_hist
    work["atr"] = compute_atr(work, ATR_PERIOD)
    work["atr_sma"] = work["atr"].rolling(window=ATR_SMA_PERIOD, min_periods=1).mean()
    work["rsi"] = compute_rsi(work["close"], RSI_PERIOD)
    work["adx"] = compute_adx(work, ADX_PERIOD)

    regime, regime_detection_inputs = detect_regime_v1(work)
    strategy = get_regime_strategy(regime)

    velocity = {
        "short_6_bars": detect_price_velocity(work, 6),
        "medium_12_bars": detect_price_velocity(work, 12),
        "long_16_bars": detect_price_velocity(work, 16),
    }

    return {
        "regime_contract_version": REGIME_INPUTS_CONTRACT_VERSION,
        "v1_regime": regime,
        "v1_regime_strategy": strategy,
        "v1_regime_detection_inputs": regime_detection_inputs,
        "trend_direction": regime_detection_inputs.get("trend_direction"),
        "ema_slope_pct": regime_detection_inputs.get("ema_slope_pct"),
        "adx": regime_detection_inputs.get("adx"),
        "atr_ratio": regime_detection_inputs.get("atr_ratio"),
        "range_pct": regime_detection_inputs.get("range_pct"),
        "ema_spread_pct": regime_detection_inputs.get("ema_spread_pct"),
        "volatility_state": volatility.get("volatility_state"),
        "price_velocity": velocity,
        "fast_rally_long": detect_fast_rally_inputs(work, "long"),
        "fast_rally_short": detect_fast_rally_inputs(work, "short"),
        "btc_macro_regime_inputs": check_btc_macro_regime_inputs(work),
        "notes": [
            "Feature Factory exposes v1-compatible regime inputs only.",
            "Strategy Engine decides whether and how to use these inputs in Phase 4.",
            "btc_macro_regime_inputs are meaningful when this block is built from BTCUSDT data.",
        ],
    }


def compute_price_action(df: pd.DataFrame, indicators: dict, structure: dict) -> dict:
    candles = df.copy().reset_index(drop=True)
    last_close = finite_float(candles["close"].iloc[-1])
    atr_value = finite_float(indicators["atr"])

    recent_bos_direction = "none"
    recent_bos_bars_ago = 999
    recent_bos_strength = 0.0
    recent_bos_failed = False

    search_window = min(len(candles), 12)
    for bars_ago in range(1, search_window):
        idx = len(candles) - bars_ago
        if idx < 6:
            continue

        candidate_close = finite_float(candles["close"].iloc[idx])
        prior_high = finite_float(candles["high"].iloc[idx - 5:idx].max())
        prior_low = finite_float(candles["low"].iloc[idx - 5:idx].min())

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

    recent_high = finite_float(candles["high"].tail(10).max())
    recent_low = finite_float(candles["low"].tail(10).min())
    last_high_idx = int(candles["high"].tail(10).idxmax())
    last_low_idx = int(candles["low"].tail(10).idxmin())

    trend_direction = structure["trend_direction"]

    if trend_direction == "up":
        pullback_bars_ago = len(candles) - 1 - last_high_idx
        pullback_depth_pct = safe_pct(recent_high - last_close, recent_high)
    elif trend_direction == "down":
        pullback_bars_ago = len(candles) - 1 - last_low_idx
        pullback_depth_pct = safe_pct(last_close - recent_low, recent_low)
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
    recent_close_change = abs(finite_float(candles["close"].iloc[-1]) - finite_float(candles["close"].iloc[-4])) if len(candles) >= 4 else 0.0

    impulse_strength_score = min(100.0, (recent_impulse_range / atr_value) * 20) if atr_value > 0 else 0.0
    correction_strength_score = min(100.0, (recent_close_change / atr_value) * 20) if atr_value > 0 else 0.0
    impulse_to_correction_ratio = (
        impulse_strength_score / correction_strength_score
        if correction_strength_score > 0 else 999.0
    )

    last_open = finite_float(candles["open"].iloc[-1])
    last_close_val = finite_float(candles["close"].iloc[-1])
    last_high = finite_float(candles["high"].iloc[-1])
    last_low = finite_float(candles["low"].iloc[-1])

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
    avg_recent_range = finite_float(recent_ranges.mean()) if len(recent_ranges) > 0 else 0.0

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
        "recent_bos_strength": finite_float(recent_bos_strength),
        "recent_bos_failed": bool(recent_bos_failed),
        "pullback_state": pullback_state,
        "pullback_bars_ago": int(max(0, pullback_bars_ago)),
        "pullback_depth_pct": finite_float(pullback_depth_pct),
        "pullback_quality_score": finite_float(pullback_quality_score),
        "impulse_strength_score": finite_float(impulse_strength_score),
        "correction_strength_score": finite_float(correction_strength_score),
        "impulse_to_correction_ratio": finite_float(impulse_to_correction_ratio, 999.0),
        "wick_rejection_bias": wick_rejection_bias,
        "wick_rejection_score": finite_float(wick_rejection_score),
        "expansion_state": expansion_state,
        "compression_state": compression_state,
    }


def build_timeframe_block(symbol: str, timeframe: str):
    fetch_limit = FETCH_WINDOWS[timeframe]
    emit_limit = EMIT_WINDOWS[timeframe]

    candles, metadata, fetch_error = fetch_candles(symbol, timeframe, fetch_limit)
    data_quality = build_timeframe_data_quality(
        timeframe=timeframe,
        limit=fetch_limit,
        candles=candles,
        metadata=metadata,
        fetch_error=fetch_error,
    )

    if fetch_error:
        return None, {
            "timeframe": timeframe,
            "error": "market_data_fetch_failed",
            "data_quality": data_quality,
        }

    if not data_quality.get("healthy", False):
        return None, {
            "timeframe": timeframe,
            "error": "market_data_unhealthy",
            "data_quality": data_quality,
        }

    if len(candles) < fetch_limit:
        return None, {
            "timeframe": timeframe,
            "error": "insufficient_candle_data",
            "data_quality": data_quality,
        }

    df = to_dataframe(candles)
    indicators = compute_indicators(df)
    structure = compute_structure(df, indicators)
    price_action = compute_price_action(df, indicators, structure)
    volatility = compute_volatility(df, indicators)
    regime_inputs = compute_regime_inputs(df, indicators, structure, volatility)

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
        "regime_inputs": regime_inputs,
    }, None


def normalize_v1_trend_for_direction(trend: str | None) -> str:
    if trend in ("bullish", "up"):
        return "long"
    if trend in ("bearish", "down"):
        return "short"
    return "neutral"


def compute_alignment_score(entry_direction: str, primary_direction: str, htf_direction: str) -> int:
    score = 0

    if entry_direction != "neutral":
        score += 20
    if primary_direction != "neutral":
        score += 30
    if htf_direction != "neutral":
        score += 30

    if entry_direction == primary_direction and entry_direction != "neutral":
        score += 10
    if primary_direction == htf_direction and primary_direction != "neutral":
        score += 10

    return int(max(0, min(100, score)))


def extract_timeframe_context_block(block: dict, role: str) -> dict:
    structure = block.get("structure", {})
    regime_inputs = block.get("regime_inputs", {})
    volatility = block.get("volatility", {})
    indicators = block.get("indicators", {})
    data_quality = block.get("data_quality", {})

    v1_trend = (
        structure.get("v1_trend_direction")
        or regime_inputs.get("trend_direction")
        or structure.get("trend_direction")
    )

    direction_bias = normalize_v1_trend_for_direction(v1_trend)

    return {
        "role": role,
        "timeframe": block.get("timeframe"),
        "data_quality_healthy": data_quality.get("healthy"),
        "last_timestamp": data_quality.get("last_timestamp"),
        "v1_trend_direction": v1_trend,
        "direction_bias": direction_bias,
        "v1_regime": regime_inputs.get("v1_regime"),
        "v1_regime_strategy": regime_inputs.get("v1_regime_strategy"),
        "volatility_state": volatility.get("volatility_state"),
        "atr_ratio": volatility.get("atr_ratio") or regime_inputs.get("atr_ratio"),
        "adx": regime_inputs.get("adx") or indicators.get("adx"),
        "rsi": indicators.get("rsi"),
        "ema_slope_pct": regime_inputs.get("ema_slope_pct"),
        "range_pct": regime_inputs.get("range_pct"),
        "ema_spread_pct": regime_inputs.get("ema_spread_pct"),
        "fast_rally_long": regime_inputs.get("fast_rally_long", {}),
        "fast_rally_short": regime_inputs.get("fast_rally_short", {}),
    }


def determine_direction_consensus(entry_ctx: dict, primary_ctx: dict, htf_ctx: dict) -> dict:
    directions = {
        "entry": entry_ctx.get("direction_bias"),
        "primary": primary_ctx.get("direction_bias"),
        "higher_timeframe": htf_ctx.get("direction_bias"),
    }

    long_votes = sum(1 for value in directions.values() if value == "long")
    short_votes = sum(1 for value in directions.values() if value == "short")
    neutral_votes = sum(1 for value in directions.values() if value == "neutral")

    if long_votes >= 2 and short_votes == 0:
        consensus = "long"
    elif short_votes >= 2 and long_votes == 0:
        consensus = "short"
    elif long_votes == 3:
        consensus = "long"
    elif short_votes == 3:
        consensus = "short"
    else:
        consensus = "mixed"

    return {
        "directions": directions,
        "long_votes": long_votes,
        "short_votes": short_votes,
        "neutral_votes": neutral_votes,
        "consensus": consensus,
        "fully_aligned": (
            directions["entry"] == directions["primary"] == directions["higher_timeframe"]
            and directions["entry"] != "neutral"
        ),
        "entry_primary_aligned": (
            directions["entry"] == directions["primary"]
            and directions["entry"] != "neutral"
        ),
        "primary_htf_aligned": (
            directions["primary"] == directions["higher_timeframe"]
            and directions["primary"] != "neutral"
        ),
        "entry_conflicts_with_htf": (
            directions["entry"] in ("long", "short")
            and directions["higher_timeframe"] in ("long", "short")
            and directions["entry"] != directions["higher_timeframe"]
        ),
    }


def build_conflict_flags(entry_ctx: dict, primary_ctx: dict, htf_ctx: dict, consensus: dict) -> list[str]:
    flags = []

    if consensus.get("entry_conflicts_with_htf"):
        flags.append("ENTRY_CONFLICTS_WITH_HTF")

    if primary_ctx.get("v1_regime") == "Sideways" and htf_ctx.get("v1_regime") in ("Uptrend", "Downtrend"):
        flags.append("PRIMARY_SIDEWAYS_HTF_TRENDING")

    if primary_ctx.get("v1_regime") in ("Uptrend", "Downtrend") and htf_ctx.get("v1_regime") == "Sideways":
        flags.append("PRIMARY_TRENDING_HTF_SIDEWAYS")

    for ctx in (entry_ctx, primary_ctx, htf_ctx):
        if ctx.get("data_quality_healthy") is False:
            flags.append(f"{ctx.get('role', 'UNKNOWN').upper()}_DATA_QUALITY_UNHEALTHY")
        if ctx.get("volatility_state") == "extreme":
            flags.append(f"{ctx.get('role', 'UNKNOWN').upper()}_EXTREME_VOLATILITY")

    return sorted(set(flags))


def build_v1_btc_macro_policy_note(primary_ctx: dict) -> dict:
    btc_macro = primary_ctx.get("btc_macro_regime_inputs") or {}

    return {
        "status": "placeholder_until_cross_symbol_context",
        "meaning": (
            "The v1 BTC macro fields should adjust only new candidate evaluation. "
            "position_size_mult multiplies the risk budget for a new entry. "
            "max_signals_adj affects admission of future new signals only, not currently open positions."
        ),
        "risk_budget_example": {
            "base_equity": 2000,
            "base_risk_pct": 0.01,
            "base_risk_amount": 20,
            "position_size_mult_1_1": 22,
            "position_size_mult_0_9": 18,
            "position_size_mult_0_7": 14,
        },
        "current_symbol_block": btc_macro,
    }


def build_multi_timeframe_context(timeframes: dict) -> dict:
    entry_tf = "5m"
    primary_tf = "15m"
    htf = "4h"

    entry_block = timeframes.get(entry_tf, {})
    primary_block = timeframes.get(primary_tf, {})
    htf_block = timeframes.get(htf, {})

    entry_ctx = extract_timeframe_context_block(entry_block, "entry")
    primary_ctx = extract_timeframe_context_block(primary_block, "primary")
    htf_ctx = extract_timeframe_context_block(htf_block, "higher_timeframe")

    consensus = determine_direction_consensus(entry_ctx, primary_ctx, htf_ctx)
    alignment_score = compute_alignment_score(
        entry_ctx.get("direction_bias"),
        primary_ctx.get("direction_bias"),
        htf_ctx.get("direction_bias"),
    )

    conflict_flags = build_conflict_flags(entry_ctx, primary_ctx, htf_ctx, consensus)

    return {
        "context_contract_version": MULTI_TIMEFRAME_CONTEXT_CONTRACT_VERSION,
        "entry_timeframe": entry_tf,
        "primary_timeframe": primary_tf,
        "higher_timeframe": htf,
        "v1_timeframe_roles": {
            "entry": entry_tf,
            "primary": primary_tf,
            "higher_timeframe": htf,
        },
        "role_context": {
            "entry": entry_ctx,
            "primary": primary_ctx,
            "higher_timeframe": htf_ctx,
        },
        "alignment": {
            **consensus,
            "alignment_score": alignment_score,
            "conflict_flags": conflict_flags,
        },
        "regime_context": {
            "entry_regime": entry_ctx.get("v1_regime"),
            "primary_regime": primary_ctx.get("v1_regime"),
            "higher_timeframe_regime": htf_ctx.get("v1_regime"),
            "primary_strategy": primary_ctx.get("v1_regime_strategy"),
            "higher_timeframe_strategy": htf_ctx.get("v1_regime_strategy"),
        },
        "btc_macro_policy": build_v1_btc_macro_policy_note(primary_ctx),
        "strategy_engine_notes": [
            "Feature Factory exposes multi-timeframe context only.",
            "Strategy Engine Phase 4 owns final long/short scoring and entry decisions.",
            "Risk Engine owns final risk budget and must treat BTC macro multipliers as new-entry risk-budget modifiers only.",
            "Max-signal adjustments affect future new entries only and must not force-close or resize existing positions.",
        ],
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
            "indicator_contract_version": INDICATOR_CONTRACT_VERSION,
                "structure_contract_version": STRUCTURE_CONTRACT_VERSION,
                "regime_inputs_contract_version": REGIME_INPUTS_CONTRACT_VERSION,
                "multi_timeframe_context_contract_version": MULTI_TIMEFRAME_CONTEXT_CONTRACT_VERSION,
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


def build_versions_payload() -> dict:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "feature_factory_version": FEATURE_FACTORY_VERSION,
        "contract_version": MARKET_SNAPSHOT_CONTRACT_VERSION,
        "indicator_contract_version": INDICATOR_CONTRACT_VERSION,
        "structure_contract_version": STRUCTURE_CONTRACT_VERSION,
        "regime_inputs_contract_version": REGIME_INPUTS_CONTRACT_VERSION,
        "multi_timeframe_context_contract_version": MULTI_TIMEFRAME_CONTEXT_CONTRACT_VERSION,
        "endpoint_contract_version": FEATURE_FACTORY_ENDPOINT_CONTRACT_VERSION,
        "v1_parity": build_v1_parity_contract(),
        "timeframes": TIMEFRAMES,
        "fetch_windows": FETCH_WINDOWS,
        "emit_windows": EMIT_WINDOWS,
        "v1_timeframe_roles": {
            "entry": "5m",
            "primary": "15m",
            "higher_timeframe": "4h",
        },
        "v1_indicator_periods": {
            "ema_fast": EMA_FAST_PERIOD,
            "ema_medium": EMA_MEDIUM_PERIOD,
            "ema_slow": EMA_SLOW_PERIOD,
            "macd_fast": MACD_FAST_PERIOD,
            "macd_slow": MACD_SLOW_PERIOD,
            "macd_signal": MACD_SIGNAL_PERIOD,
            "atr": ATR_PERIOD,
            "atr_sma": ATR_SMA_PERIOD,
            "rsi": RSI_PERIOD,
            "adx": ADX_PERIOD,
            "volume_sma": VOLUME_SMA_PERIOD,
        },
    }


def build_error_response(
    error: str,
    status_code: int = 400,
    symbol: str | None = None,
    details: list | dict | None = None,
    reason_codes: list[str] | None = None,
    data_quality: dict | None = None,
) -> tuple[dict, int]:
    payload = {
        "ok": False,
        "service": SERVICE_NAME,
        "error": error,
        "reason_codes": reason_codes or [error.upper()],
        "versions": {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "feature_factory_version": FEATURE_FACTORY_VERSION,
            "endpoint_contract_version": FEATURE_FACTORY_ENDPOINT_CONTRACT_VERSION,
        },
    }

    if symbol:
        payload["symbol"] = normalize_symbol(symbol)

    if details is not None:
        payload["details"] = details

    if data_quality is not None:
        payload["data_quality"] = data_quality

    return payload, status_code


def build_snapshot_success_response(snapshot: dict) -> dict:
    # Keep the existing snapshot top-level shape for compatibility, but make the
    # successful response explicit and versioned.
    snapshot = dict(snapshot)
    snapshot["ok"] = True
    snapshot["endpoint_contract_version"] = FEATURE_FACTORY_ENDPOINT_CONTRACT_VERSION
    snapshot["versions"] = build_versions_payload()
    return snapshot


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
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
                "versions": build_versions_payload(),
            })
            return

        if self.path.startswith("/versions"):
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "versions": build_versions_payload(),
            })
            return

        if self.path.startswith("/snapshot"):
            query = parse_qs(urlparse(self.path).query)
            symbol = query.get("symbol", [None])[0]

            if not symbol:
                payload, status_code = build_error_response(
                    error="missing_parameters",
                    status_code=400,
                    reason_codes=["MISSING_SYMBOL"],
                    details={"required": ["symbol"]},
                )
                self._send_json(payload, status=status_code)
                return

            snapshot, error = build_market_snapshot(symbol)

            if error:
                payload, status_code = build_error_response(
                    error=error.get("error", "snapshot_build_failed"),
                    status_code=400,
                    symbol=symbol,
                    details=error.get("details"),
                    reason_codes=error.get("reason_codes", ["SNAPSHOT_BUILD_FAILED"]),
                    data_quality=error.get("data_quality"),
                )
                self._send_json(payload, status=status_code)
                return

            self._send_json(build_snapshot_success_response(snapshot))
            return

        payload, status_code = build_error_response(
            error="not_found",
            status_code=404,
            reason_codes=["ENDPOINT_NOT_FOUND"],
            details={"path": self.path},
        )
        self._send_json(payload, status=status_code)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
