import json
from datetime import datetime, timedelta, timezone

def gen_candles():
    base_time = datetime.now(timezone.utc)
    candles = []

    for i in range(50):
        t = base_time - timedelta(minutes=i)
        candles.append({
            "timestamp": t.isoformat() + "Z",
            "open": 100,
            "high": 105,
            "low": 95,
            "close": 102,
            "volume": 1000
        })

    return list(reversed(candles))


def make_tf(tf):
    return {
        "timeframe": tf,
        "window_size": 50,
        "candles": gen_candles(),
        "indicators": {
            "rsi": 50,
            "atr": 10,
            "ema_fast": 100,
            "ema_slow": 105,
            "macd": 1,
            "macd_signal": 0.5,
            "macd_histogram": 0.5,
            "volume_sma": 1000,
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
            "range_high": 110,
            "range_low": 90,
            "distance_to_range_high_pct": 0.2,
            "distance_to_range_low_pct": 0.8
        },
        "volatility": {
            "atr": 10,
            "atr_percent": 0.5,
            "volatility_state": "medium"
        }
    }


snapshot = {
    "schema_version": "market_snapshot_v1",
    "symbol": "BTCUSDT",
    "snapshot_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "source": "feature-factory",
    "timeframes": {
        "5m": make_tf("5m"),
        "15m": make_tf("15m"),
        "1h": make_tf("1h"),
        "4h": make_tf("4h")
    }
}

with open("tests/fixtures/market_snapshot_v1_sample.json", "w") as f:
    json.dump(snapshot, f, indent=2)
