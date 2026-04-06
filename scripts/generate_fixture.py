import json
from datetime import datetime, timedelta, timezone

WINDOWS = {
    "5m": 72,
    "15m": 48,
    "1h": 30,
    "4h": 16,
}


def tf_delta(tf: str):
    if tf == "5m":
        return timedelta(minutes=5)
    if tf == "15m":
        return timedelta(minutes=15)
    if tf == "1h":
        return timedelta(hours=1)
    if tf == "4h":
        return timedelta(hours=4)
    raise ValueError(f"Unsupported timeframe: {tf}")


def gen_candles(tf: str, n: int):
    base_time = datetime.now(timezone.utc)
    delta = tf_delta(tf)
    candles = []

    for i in range(n):
        t = base_time - delta * (n - 1 - i)
        candles.append({
            "timestamp": t.isoformat().replace("+00:00", "Z"),
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0
        })

    return candles


def make_tf(tf: str):
    n = WINDOWS[tf]
    return {
        "timeframe": tf,
        "window_size": n,
        "candles": gen_candles(tf, n),
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
            "price_vs_ema_slow_pct": -0.2,
            "ema_separation_pct": -4.76,
            "macd_histogram_slope": 0.1,
            "rsi_state": "neutral",
            "atr_percent": 0.5
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
            "distance_to_range_high_pct": 40.0,
            "distance_to_range_low_pct": 60.0,
            "structure_state": "range",
            "structure_quality_score": 55.0,
            "swing_bias": "neutral",
            "trend_consistency_score": 35.0
        },
        "price_action": {
            "recent_bos_direction": "none",
            "recent_bos_bars_ago": 999,
            "recent_bos_strength": 0.0,
            "recent_bos_failed": False,
            "pullback_state": "active_pullback",
            "pullback_bars_ago": 2,
            "pullback_depth_pct": 1.0,
            "pullback_quality_score": 60.0,
            "impulse_strength_score": 50.0,
            "correction_strength_score": 30.0,
            "impulse_to_correction_ratio": 1.67,
            "wick_rejection_bias": "neutral",
            "wick_rejection_score": 0.3,
            "expansion_state": "none",
            "compression_state": "none"
        },
        "volatility": {
            "atr": 10.0,
            "atr_percent": 0.5,
            "volatility_state": "medium"
        }
    }


generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

snapshot = {
    "snapshot_meta": {
        "schema_version": "market_snapshot_v2",
        "feature_factory_version": "v2",
        "generated_at": generated_at,
        "symbol": "BTCUSDT"
    },
    "schema_version": "market_snapshot_v2",
    "symbol": "BTCUSDT",
    "snapshot_timestamp": generated_at,
    "source": "feature-factory",
    "timeframes": {
        "5m": make_tf("5m"),
        "15m": make_tf("15m"),
        "1h": make_tf("1h"),
        "4h": make_tf("4h")
    }
}

with open("tests/fixtures/market_snapshot_v2_sample.json", "w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2)