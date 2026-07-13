"""
Phase 4 Steps 6-7 — v1 signal scoring with breakdown.

This module ports the v1 SignalScorer breakdown shape to MarketSnapshot v2.

Step 6:
    v1 trend-following score with breakdown

Step 7:
    v1 mean-reversion score with breakdown

This module does not validate entries, calculate SL/TP, size positions, or
execute trades. It assumes entry validation has already run and simply returns a
0-100 strategy score plus a weighted breakdown.
"""

from __future__ import annotations

from typing import Any

from v1_history_access import get_history_values, is_decreasing, is_increasing

from snapshot_v1_adapter import (
    direction_bias,
    get_bos_for_direction,
    get_indicator,
    get_mean_reversion_range,
    get_regime_value,
    get_structure_value,
    get_volatility_value,
    latest_close,
    safe_float,
    v1_trend_direction,
)

V1_SIGNAL_SCORER_VERSION = "phase4_step11_v1_signal_scoring_history"

TREND_WEIGHTS = {
    "htf_alignment": 25,
    "momentum": 20,
    "entry_location": 20,
    "break_of_structure": 15,
    "rsi_quality": 12,
    "volatility": 8,
}

MEAN_REVERSION_WEIGHTS = {
    "range_confirmation": 20,
    "breakout_safety": 15,
    "reversal_pattern": 20,
    "entry_extremity": 20,
    "rsi_divergence": 15,
    "low_volatility": 10,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _empty_breakdown(weights: dict[str, int]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "points": 0,
            "max": max_points,
            "details": "",
        }
        for key, max_points in weights.items()
    }


def _score_result(
    symbol: str,
    direction: str,
    strategy_type: str,
    breakdown: dict[str, dict[str, Any]],
    reason_tags: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = round(sum(float(item.get("points", 0)) for item in breakdown.values()), 2)
    return {
        "ok": True,
        "scorer_version": V1_SIGNAL_SCORER_VERSION,
        "symbol": str(symbol or "").upper(),
        "direction": direction,
        "strategy_type": strategy_type,
        "score": total,
        "max_score": 100,
        "breakdown": breakdown,
        "reason_tags": sorted(set(reason_tags or [])),
        "details": details or {},
    }


def _trend_to_v1(value: str | None) -> str:
    value = str(value or "").lower()
    if value in ("bullish", "up", "long"):
        return "bullish"
    if value in ("bearish", "down", "short"):
        return "bearish"
    return "neutral"


def _indicator(snapshot: dict[str, Any], role: str, *names: str, default: float = 0.0) -> float:
    for name in names:
        value = get_indicator(snapshot, role, name, None)
        if value is not None:
            return safe_float(value, default)
    return default


def _macd_hist(snapshot: dict[str, Any], role: str) -> float:
    return _indicator(snapshot, role, "macd_hist", "macd_histogram", default=0.0)


def _macd_slope(snapshot: dict[str, Any], role: str) -> float:
    return _indicator(snapshot, role, "macd_histogram_slope", "macd_slope", default=0.0)


def _rsi(snapshot: dict[str, Any], role: str = "primary") -> float:
    return _indicator(snapshot, role, "rsi_14", "rsi", default=50.0)


def _atr(snapshot: dict[str, Any], role: str = "primary") -> float:
    return _indicator(snapshot, role, "atr_14", "atr", default=safe_float(get_volatility_value(snapshot, role, "atr", 0.0)))


def _atr_ratio(snapshot: dict[str, Any], role: str = "primary") -> float:
    ratio = get_volatility_value(snapshot, role, "atr_ratio")
    if ratio is not None:
        return safe_float(ratio, 1.0)
    atr = _atr(snapshot, role)
    atr_sma = _indicator(snapshot, role, "atr_sma_20", "atr_sma", default=0.0)
    if atr_sma == 0:
        return 1.0
    return atr / atr_sma


def _ema_slow(snapshot: dict[str, Any], role: str = "htf") -> float:
    return _indicator(snapshot, role, "ema_slow", "ema_200", default=0.0)


def _ema_fast(snapshot: dict[str, Any], role: str = "entry") -> float:
    return _indicator(snapshot, role, "ema_fast", "ema_21", default=0.0)


def _price_vs_ema_slow_pct(snapshot: dict[str, Any], role: str = "htf") -> float:
    existing = get_indicator(snapshot, role, "price_vs_ema_slow_pct", None)
    if existing is not None:
        # Feature Factory usually emits percentage points, e.g. 1.2 means 1.2%.
        return safe_float(existing, 0.0) / 100.0

    price = latest_close(snapshot, role)
    ema = _ema_slow(snapshot, role)
    if price <= 0 or ema <= 0:
        return 0.0
    return (price - ema) / ema


def _score_fast_rally_from_snapshot(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    key = "fast_rally_long" if direction == "long" else "fast_rally_short"
    rally = get_regime_value(snapshot, "primary", key, {}) or {}
    velocity = get_regime_value(snapshot, "primary", "price_velocity", {}) or {}

    velocity_short = safe_float(rally.get("velocity_short", velocity.get("short_6_bars", 0.0)))
    velocity_medium = safe_float(rally.get("velocity_medium", velocity.get("medium_12_bars", 0.0)))
    detected = bool(rally.get("detected", False))
    strength = str(rally.get("strength", "none"))

    primary_trend = _trend_to_v1(v1_trend_direction(snapshot, "primary"))
    strong_primary = (
        primary_trend == "bullish" if direction == "long" else primary_trend == "bearish"
    )

    if not strong_primary:
        return 8, f"HTF neutral, weak primary trend (1.5h: {velocity_short * 100:+.1f}%)"

    if direction == "long":
        if velocity_short > 0.05 or strength == "explosive":
            return 25, f"Explosive rally: {velocity_short * 100:+.1f}% in 1.5h"
        if velocity_short > 0.03 or velocity_medium > 0.045 or strength == "strong":
            return 22, f"Strong rally: {velocity_short * 100:+.1f}% (1.5h), {velocity_medium * 100:+.1f}% (3h)"
    else:
        if velocity_short < -0.05 or strength == "explosive":
            return 25, f"Explosive correction: {velocity_short * 100:+.1f}% in 1.5h"
        if velocity_short < -0.03 or velocity_medium < -0.045 or strength == "strong":
            return 22, f"Strong correction: {velocity_short * 100:+.1f}% (1.5h), {velocity_medium * 100:+.1f}% (3h)"

    if detected:
        return 15, "Moderate rally/correction with strong primary trend"

    return 8, "HTF neutral without clear fast rally/correction"


def _score_trend_htf_alignment(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    htf_trend = _trend_to_v1(v1_trend_direction(snapshot, "htf"))
    price_vs_ema_dist = _price_vs_ema_slow_pct(snapshot, "htf")

    if direction == "long":
        if htf_trend == "bullish":
            points = 25 if price_vs_ema_dist > 0.05 else (18 if price_vs_ema_dist > 0.02 else 12)
            return points, f"Bullish, {price_vs_ema_dist * 100:.1f}% above EMA200"
        if htf_trend == "neutral":
            return _score_fast_rally_from_snapshot(snapshot, direction)
        return 0, f"Opposing HTF trend ({htf_trend})"

    if htf_trend == "bearish":
        points = 25 if price_vs_ema_dist < -0.05 else (18 if price_vs_ema_dist < -0.02 else 12)
        return points, f"Bearish, {abs(price_vs_ema_dist) * 100:.1f}% below EMA200"
    if htf_trend == "neutral":
        return _score_fast_rally_from_snapshot(snapshot, direction)
    return 0, f"Opposing HTF trend ({htf_trend})"


def _score_trend_momentum(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    macd_tail = get_history_values(snapshot, "primary", "macd_hist", tail_size=3)
    hist = macd_tail[-1] if macd_tail else _macd_hist(snapshot, "primary")

    if len(macd_tail) >= 3:
        if direction == "long":
            if macd_tail[-1] > macd_tail[-2] > macd_tail[-3] > 0:
                return 20, "Accelerating momentum"
            if macd_tail[-1] > macd_tail[-2] > 0:
                return 14, "Increasing momentum"
            if macd_tail[-1] > 0:
                return 8, "Positive but weak momentum"
            return 0, "Momentum does not support long"

        if macd_tail[-1] < macd_tail[-2] < macd_tail[-3] < 0:
            return 20, "Accelerating downside momentum"
        if macd_tail[-1] < macd_tail[-2] < 0:
            return 14, "Increasing downside momentum"
        if macd_tail[-1] < 0:
            return 8, "Negative but weak momentum"
        return 0, "Momentum does not support short"

    # Fallback for malformed fixture/snapshot. Normal Feature Factory snapshots
    # include enough candles for the tail calculation.
    slope = _macd_slope(snapshot, "primary")
    if direction == "long":
        if hist > 0 and slope > 0:
            return 14, "Increasing momentum from latest+slope fallback"
        if hist > 0:
            return 8, "Positive but weak momentum"
        return 0, "Momentum does not support long"

    if hist < 0 and slope < 0:
        return 14, "Increasing downside momentum from latest+slope fallback"
    if hist < 0:
        return 8, "Negative but weak momentum"
    return 0, "Momentum does not support short"

def _score_trend_rsi(snapshot: dict[str, Any], direction: str, htf_alignment_points: float) -> tuple[int, str]:
    rsi = _rsi(snapshot, "primary")
    htf_trend = _trend_to_v1(v1_trend_direction(snapshot, "htf"))

    is_bullish_context = htf_trend == "bullish" or (htf_trend == "neutral" and htf_alignment_points > 15)
    is_bearish_context = htf_trend == "bearish" or (htf_trend == "neutral" and htf_alignment_points > 15)

    if direction == "long":
        if is_bullish_context:
            points = 12 if 45 <= rsi <= 70 else (8 if 70 < rsi <= 80 else 4)
        else:
            points = 12 if 30 <= rsi <= 50 else (8 if 50 < rsi <= 60 else 4)
    else:
        if is_bearish_context:
            points = 12 if 30 <= rsi <= 55 else (8 if 20 <= rsi < 30 else 4)
        else:
            points = 12 if 50 <= rsi <= 70 else (8 if 40 <= rsi < 50 else 4)

    ctx = "momentum" if (is_bullish_context or is_bearish_context) else "reversal"
    return points, f"RSI at {rsi:.1f} in {ctx} context"


def _score_trend_entry_location(snapshot: dict[str, Any]) -> tuple[int, str]:
    price = latest_close(snapshot, "entry")
    ema_fast = _ema_fast(snapshot, "entry")
    atr = _atr(snapshot, "primary")

    if price <= 0 or ema_fast <= 0 or atr <= 0:
        return 0, "Missing price/EMA/ATR for entry location"

    dist_from_ema_atr = abs(price - ema_fast) / atr
    points = 20 if dist_from_ema_atr < 0.3 else (14 if dist_from_ema_atr < 0.6 else (8 if dist_from_ema_atr < 1.0 else 3))
    return points, f"{dist_from_ema_atr:.2f} ATR from EMA21"


def _score_trend_bos(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    bos = get_bos_for_direction(snapshot, direction, "primary") or {}
    detected = bool(bos.get("detected", False))
    bars_ago = bos.get("bars_ago")
    quality_points = bos.get("quality_points")
    quality_details = bos.get("quality_details")

    if quality_points is not None:
        return int(clamp(safe_float(quality_points), 0, 15)), str(quality_details or "BOS quality from Feature Factory")

    if not detected:
        return 0, "No break of structure detected"

    bars = int(safe_float(bars_ago, 999))
    if bars <= 2:
        return 15, f"Fresh BOS within {bars} bars"
    if bars <= 5:
        return 10, f"Recent BOS within {bars} bars"
    return 5, f"Older BOS {bars} bars ago"


def _score_trend_volatility(snapshot: dict[str, Any]) -> tuple[int, str]:
    ratio = _atr_ratio(snapshot, "primary")
    if 1.0 <= ratio <= 1.5:
        return 8, f"Ideal volatility ({ratio:.2f}x avg)"
    if 0.8 <= ratio < 1.8:
        return 5, f"Acceptable volatility ({ratio:.2f}x avg)"
    return 0, f"Poor volatility ({ratio:.2f}x avg)"


def score_trend_following(snapshot: dict[str, Any], direction: str, symbol: str = "") -> dict[str, Any]:
    direction = str(direction or "").lower()
    breakdown = _empty_breakdown(TREND_WEIGHTS)
    reasons: list[str] = []

    points, details = _score_trend_htf_alignment(snapshot, direction)
    breakdown["htf_alignment"]["points"] = points
    breakdown["htf_alignment"]["details"] = details
    reasons.append("HTF_ALIGNMENT_SCORED")

    points, details = _score_trend_momentum(snapshot, direction)
    breakdown["momentum"]["points"] = points
    breakdown["momentum"]["details"] = details
    reasons.append("MOMENTUM_SCORED")

    points, details = _score_trend_entry_location(snapshot)
    breakdown["entry_location"]["points"] = points
    breakdown["entry_location"]["details"] = details
    reasons.append("ENTRY_LOCATION_SCORED")

    points, details = _score_trend_bos(snapshot, direction)
    breakdown["break_of_structure"]["points"] = points
    breakdown["break_of_structure"]["details"] = details
    reasons.append("BOS_SCORED")

    points, details = _score_trend_rsi(snapshot, direction, breakdown["htf_alignment"]["points"])
    breakdown["rsi_quality"]["points"] = points
    breakdown["rsi_quality"]["details"] = details
    reasons.append("RSI_QUALITY_SCORED")

    points, details = _score_trend_volatility(snapshot)
    breakdown["volatility"]["points"] = points
    breakdown["volatility"]["details"] = details
    reasons.append("VOLATILITY_SCORED")

    return _score_result(
        symbol=symbol,
        direction=direction,
        strategy_type="trend_following",
        breakdown=breakdown,
        reason_tags=reasons,
        details={
            "weights": TREND_WEIGHTS,
            "history_parity": "uses v1_history_access primary macd_hist tail(3) computed from candles",
            "primary_direction_bias": direction_bias(snapshot, "primary"),
            "htf_direction_bias": direction_bias(snapshot, "htf"),
        },
    )


def _score_mr_range_confirmation(snapshot: dict[str, Any]) -> tuple[int, str]:
    regime = str(get_regime_value(snapshot, "primary", "v1_regime", "unknown") or "unknown")
    if regime == "Sideways":
        return 20, "Confirmed sideways market"
    return 0, f"Market is not sideways ({regime})"


def _score_mr_breakout_safety(snapshot: dict[str, Any]) -> tuple[int, str]:
    range_info = get_mean_reversion_range(snapshot, "primary") or {}
    if range_info.get("valid"):
        return 15, (
            f"Contained range ({safe_float(range_info.get('range_width_atr'), 0.0):.1f} ATR wide, "
            f"ATR {safe_float(range_info.get('atr_ratio'), _atr_ratio(snapshot, 'primary')):.2f}x avg)"
        )
    return 0, str(range_info.get("reason", "Range not safe"))


def _score_mr_reversal_pattern(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    macd_tail = get_history_values(snapshot, "entry", "macd_hist", tail_size=2)
    if len(macd_tail) >= 2:
        if (direction == "long" and macd_tail[-1] > macd_tail[-2]) or (
            direction == "short" and macd_tail[-1] < macd_tail[-2]
        ):
            return 20, "5m MACD confirming reversal"
        return 8, "5m MACD not yet confirming"

    slope = _macd_slope(snapshot, "entry")
    if (direction == "long" and slope > 0) or (direction == "short" and slope < 0):
        return 20, "5m MACD confirming reversal from slope fallback"
    return 8, "5m MACD not yet confirming"

def _score_mr_entry_extremity(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    range_info = get_mean_reversion_range(snapshot, "primary") or {}
    position = range_info.get("position")
    if position is None:
        return 0, "Range position unavailable"

    pos = clamp(safe_float(position, 0.5), 0.0, 1.0)
    if direction == "long":
        edge_score = (0.5 - pos) / 0.5
        details = f"Entry at {pos * 100:.0f}% of local range (0%=support)"
    else:
        edge_score = (pos - 0.5) / 0.5
        details = f"Entry at {pos * 100:.0f}% of local range (100%=resistance)"

    points = int(20 * clamp(edge_score, 0.0, 1.0))
    return points, details


def _score_mr_rsi(snapshot: dict[str, Any], direction: str) -> tuple[int, str]:
    rsi = _rsi(snapshot, "primary")
    if direction == "long":
        points = 15 if rsi < 35 else (10 if rsi < 45 else 5)
        return points, f"RSI at {rsi:.1f} (Oversold)"
    points = 15 if rsi > 65 else (10 if rsi > 55 else 5)
    return points, f"RSI at {rsi:.1f} (Overbought)"


def _score_mr_low_volatility(snapshot: dict[str, Any]) -> tuple[int, str]:
    ratio = _atr_ratio(snapshot, "primary")
    if ratio < 0.9:
        return 10, f"Volatility contracting ({ratio:.2f}x avg)"
    if ratio <= 1.0:
        return 5, f"Volatility stable ({ratio:.2f}x avg)"
    return 0, f"Volatility expanding ({ratio:.2f}x avg)"


def score_mean_reversion(snapshot: dict[str, Any], direction: str, symbol: str = "") -> dict[str, Any]:
    direction = str(direction or "").lower()
    breakdown = _empty_breakdown(MEAN_REVERSION_WEIGHTS)
    reasons: list[str] = []

    points, details = _score_mr_range_confirmation(snapshot)
    breakdown["range_confirmation"]["points"] = points
    breakdown["range_confirmation"]["details"] = details
    reasons.append("RANGE_CONFIRMATION_SCORED")

    points, details = _score_mr_breakout_safety(snapshot)
    breakdown["breakout_safety"]["points"] = points
    breakdown["breakout_safety"]["details"] = details
    reasons.append("BREAKOUT_SAFETY_SCORED")

    points, details = _score_mr_reversal_pattern(snapshot, direction)
    breakdown["reversal_pattern"]["points"] = points
    breakdown["reversal_pattern"]["details"] = details
    reasons.append("REVERSAL_PATTERN_SCORED")

    points, details = _score_mr_entry_extremity(snapshot, direction)
    breakdown["entry_extremity"]["points"] = points
    breakdown["entry_extremity"]["details"] = details
    reasons.append("ENTRY_EXTREMITY_SCORED")

    points, details = _score_mr_rsi(snapshot, direction)
    breakdown["rsi_divergence"]["points"] = points
    breakdown["rsi_divergence"]["details"] = details
    reasons.append("RSI_DIVERGENCE_SCORED")

    points, details = _score_mr_low_volatility(snapshot)
    breakdown["low_volatility"]["points"] = points
    breakdown["low_volatility"]["details"] = details
    reasons.append("LOW_VOLATILITY_SCORED")

    return _score_result(
        symbol=symbol,
        direction=direction,
        strategy_type="mean_reversion",
        breakdown=breakdown,
        reason_tags=reasons,
        details={
            "weights": MEAN_REVERSION_WEIGHTS,
            "history_parity": "uses v1_history_access entry macd_hist latest vs previous computed from candles",
            "range_info": get_mean_reversion_range(snapshot, "primary"),
            "primary_direction_bias": direction_bias(snapshot, "primary"),
            "htf_direction_bias": direction_bias(snapshot, "htf"),
        },
    )


def score_v1_signal(
    snapshot: dict[str, Any],
    direction: str,
    strategy_type: str,
    symbol: str = "",
) -> dict[str, Any]:
    strategy_type = str(strategy_type or "").lower()
    if strategy_type == "trend_following":
        return score_trend_following(snapshot, direction, symbol)
    if strategy_type == "mean_reversion":
        return score_mean_reversion(snapshot, direction, symbol)

    return {
        "ok": False,
        "scorer_version": V1_SIGNAL_SCORER_VERSION,
        "symbol": str(symbol or "").upper(),
        "direction": str(direction or "neutral").lower(),
        "strategy_type": strategy_type or "none",
        "score": 0.0,
        "max_score": 100,
        "breakdown": {},
        "reason_tags": ["INVALID_STRATEGY_TYPE"],
        "details": {"strategy_type": strategy_type},
    }


def build_v1_signal_scorer_contract() -> dict[str, Any]:
    return {
        "scorer_version": V1_SIGNAL_SCORER_VERSION,
        "ported_steps": ["phase4_step6_trend_following_score", "phase4_step7_mean_reversion_score"],
        "trend_weights": TREND_WEIGHTS,
        "mean_reversion_weights": MEAN_REVERSION_WEIGHTS,
        "v1_source": "src/strategy/signal_scorer.py",
        "routes": {
            "trend_following": "score_trend_following",
            "mean_reversion": "score_mean_reversion",
        },
        "does_not_validate_entries": True,
        "does_not_calculate_sltp": True,
        "does_not_size_positions": True,
        "does_not_execute": True,
    }
