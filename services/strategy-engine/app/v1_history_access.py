"""
Phase 4 Step 11 — v1 indicator history access.

Feature Factory already emits raw recent candles inside each MarketSnapshot v2
timeframe block:

    timeframes.<tf>.candles

This module computes compact v1-style indicator tails from those candles so
Strategy Engine can reproduce dataframe-based v1 checks without adding a new
Data Hub call or changing the runtime service boundary.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

HISTORY_ACCESS_VERSION = "phase4_step11_v1_indicator_history"

EMA_FAST_PERIOD = 21
EMA_MEDIUM_PERIOD = 50
EMA_SLOW_PERIOD = 200
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_SMA_PERIOD = 20

ROLE_TO_TIMEFRAME = {
    "entry": "5m",
    "primary": "15m",
    "htf": "4h",
    "higher_timeframe": "4h",
    "context": "1h",
}


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if not result == result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def timeframe_for_role(role: str) -> str:
    return ROLE_TO_TIMEFRAME.get(str(role), str(role))


def get_candles(snapshot: dict[str, Any], role: str) -> list[dict[str, Any]]:
    timeframe = timeframe_for_role(role)
    block = (snapshot.get("timeframes", {}) or {}).get(timeframe, {}) or {}
    candles = block.get("candles", []) or []
    return list(candles)


def _series(candles: list[dict[str, Any]], field: str) -> list[float]:
    return [finite_float(c.get(field)) for c in candles]


def _ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out: list[float] = [finite_float(values[0])]
    for value in values[1:]:
        out.append((finite_float(value) * alpha) + (out[-1] * (1.0 - alpha)))
    return out


def _rsi(close: list[float], period: int = RSI_PERIOD) -> list[float]:
    if not close:
        return []
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(close)):
        delta = close[i] - close[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    alpha = 1.0 / period
    avg_gain = gains[0]
    avg_loss = losses[0]
    out: list[float] = []
    for gain, loss in zip(gains, losses):
        avg_gain = (gain * alpha) + (avg_gain * (1.0 - alpha))
        avg_loss = (loss * alpha) + (avg_loss * (1.0 - alpha))
        if avg_loss == 0:
            out.append(100.0 if avg_gain > 0 else 50.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out


def _atr(candles: list[dict[str, Any]], period: int = ATR_PERIOD) -> list[float]:
    if not candles:
        return []
    highs = _series(candles, "high")
    lows = _series(candles, "low")
    closes = _series(candles, "close")

    tr_values: list[float] = []
    for i in range(len(candles)):
        high = highs[i]
        low = lows[i]
        if i == 0:
            tr = high - low
        else:
            prev_close = closes[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)

    alpha = 1.0 / period
    out: list[float] = []
    current = tr_values[0]
    for tr in tr_values:
        current = (tr * alpha) + (current * (1.0 - alpha))
        out.append(current)
    return out


def _rolling_mean(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        sample = values[start : i + 1]
        out.append(sum(sample) / len(sample) if sample else 0.0)
    return out


def _tail(values: list[float], n: int = 5) -> list[float]:
    return [finite_float(v) for v in values[-n:]]


def build_indicator_history_from_candles(candles: list[dict[str, Any]], tail_size: int = 5) -> dict[str, Any]:
    close = _series(candles, "close")
    high = _series(candles, "high")
    low = _series(candles, "low")

    ema_fast = _ema(close, EMA_FAST_PERIOD)
    ema_medium = _ema(close, EMA_MEDIUM_PERIOD)
    ema_slow = _ema(close, EMA_SLOW_PERIOD)

    macd_fast = _ema(close, MACD_FAST_PERIOD)
    macd_slow = _ema(close, MACD_SLOW_PERIOD)
    macd = [a - b for a, b in zip(macd_fast, macd_slow)]
    macd_signal = _ema(macd, MACD_SIGNAL_PERIOD)
    macd_hist = [a - b for a, b in zip(macd, macd_signal)]

    rsi = _rsi(close, RSI_PERIOD)
    atr = _atr(candles, ATR_PERIOD)
    atr_sma = _rolling_mean(atr, ATR_SMA_PERIOD)

    return {
        "history_access_version": HISTORY_ACCESS_VERSION,
        "tail_size": tail_size,
        "rows": len(candles),
        "close": _tail(close, tail_size),
        "high": _tail(high, tail_size),
        "low": _tail(low, tail_size),
        "ema_fast": _tail(ema_fast, tail_size),
        "ema_medium": _tail(ema_medium, tail_size),
        "ema_slow": _tail(ema_slow, tail_size),
        "macd": _tail(macd, tail_size),
        "macd_signal": _tail(macd_signal, tail_size),
        "macd_hist": _tail(macd_hist, tail_size),
        "rsi": _tail(rsi, tail_size),
        "atr": _tail(atr, tail_size),
        "atr_sma": _tail(atr_sma, tail_size),
    }


def get_indicator_history(snapshot: dict[str, Any], role: str, tail_size: int = 5) -> dict[str, Any]:
    candles = get_candles(snapshot, role)
    return build_indicator_history_from_candles(candles, tail_size=tail_size)


def get_history_values(snapshot: dict[str, Any], role: str, key: str, tail_size: int = 5) -> list[float]:
    history = get_indicator_history(snapshot, role, tail_size=tail_size)
    values = history.get(key, []) or []
    return [finite_float(v) for v in values]


def latest_from_history(snapshot: dict[str, Any], role: str, key: str, default: float = 0.0) -> float:
    values = get_history_values(snapshot, role, key, tail_size=1)
    if values:
        return finite_float(values[-1], default)
    return float(default)


def is_increasing(values: list[float], strict: bool = True) -> bool:
    if len(values) < 2:
        return False
    pairs = zip(values[:-1], values[1:])
    if strict:
        return all(b > a for a, b in pairs)
    return all(b >= a for a, b in pairs)


def is_decreasing(values: list[float], strict: bool = True) -> bool:
    if len(values) < 2:
        return False
    pairs = zip(values[:-1], values[1:])
    if strict:
        return all(b < a for a, b in pairs)
    return all(b <= a for a, b in pairs)


def build_history_diagnostics(snapshot: dict[str, Any]) -> dict[str, Any]:
    diagnostics = {
        "history_access_version": HISTORY_ACCESS_VERSION,
        "timeframes": {},
    }

    for role in ("entry", "primary", "htf"):
        candles = get_candles(snapshot, role)
        history = get_indicator_history(snapshot, role, tail_size=5)
        diagnostics["timeframes"][role] = {
            "timeframe": timeframe_for_role(role),
            "candle_rows": len(candles),
            "history_rows": history.get("rows"),
            "macd_hist_tail": history.get("macd_hist", []),
            "rsi_tail": history.get("rsi", []),
            "atr_tail": history.get("atr", []),
            "has_v1_tail_requirements": len(history.get("macd_hist", [])) >= 3 and len(history.get("rsi", [])) >= 2,
        }

    return diagnostics


def build_history_access_contract() -> dict[str, Any]:
    return {
        "history_access_version": HISTORY_ACCESS_VERSION,
        "source": "MarketSnapshot v2 timeframes.<tf>.candles",
        "computed_tails": [
            "close",
            "high",
            "low",
            "ema_fast",
            "ema_medium",
            "ema_slow",
            "macd",
            "macd_signal",
            "macd_hist",
            "rsi",
            "atr",
            "atr_sma",
        ],
        "v1_parity_use_cases": [
            "primary macd_hist tail(3)",
            "entry macd_hist latest vs previous",
            "primary rsi latest vs previous",
            "primary atr latest / atr_sma latest",
        ],
        "requires_feature_factory_change": False,
        "reason": "Feature Factory already emits recent raw candles per timeframe.",
    }
