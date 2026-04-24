from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os

import requests


SERVICE_NAME = "strategy-engine"
PORT = int(os.getenv("PORT", "8080"))

FEATURE_FACTORY_BASE_URL = os.getenv("FEATURE_FACTORY_BASE_URL", "http://feature-factory:8080")
STRICT_SCORE_THRESHOLD = float(os.getenv("STRICT_SCORE_THRESHOLD", "75"))

TRADE_SCORE_THRESHOLD = float(os.getenv("TRADE_SCORE_THRESHOLD", "68"))
OBSERVE_SCORE_THRESHOLD = float(os.getenv("OBSERVE_SCORE_THRESHOLD", "55"))

MACRO_NEUTRAL_PENALTY = float(os.getenv("MACRO_NEUTRAL_PENALTY", "8"))
MACRO_TRANSITION_PENALTY = float(os.getenv("MACRO_TRANSITION_PENALTY", "15"))

REGIME_TRANSITION_CAP = float(os.getenv("REGIME_TRANSITION_CAP", "72"))
REGIME_CHOP_CAP = float(os.getenv("REGIME_CHOP_CAP", "62"))
REGIME_RANGE_TREND_CAP = float(os.getenv("REGIME_RANGE_TREND_CAP", "58"))
REGIME_TREND_MEAN_REVERSION_CAP = float(os.getenv("REGIME_TREND_MEAN_REVERSION_CAP", "52"))


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def fetch_snapshot(symbol: str):
    try:
        r = requests.get(
            f"{FEATURE_FACTORY_BASE_URL}/snapshot",
            params={"symbol": symbol},
            timeout=20
        )
        payload = r.json()
    except Exception as e:
        return None, f"feature_factory_request_failed: {str(e)}"

    if r.status_code != 200:
        return None, payload.get("error", "feature_factory_error")

    if payload.get("schema_version") != "market_snapshot_v2":
        return None, "unexpected_snapshot_schema_version"

    return payload, None


def safe_get_tf(snapshot: dict, tf: str):
    return snapshot.get("timeframes", {}).get(tf, {})

def safe_get_indicators(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("indicators", {})


def safe_get_structure(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("structure", {})


def safe_get_price_action(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("price_action", {})


def safe_get_volatility(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("volatility", {})


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_linear(value: float, low: float, high: float, max_points: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return max_points
    return ((value - low) / (high - low)) * max_points


def score_inverse(value: float, best_low: float, worst_high: float, max_points: float) -> float:
    if value <= best_low:
        return max_points
    if value >= worst_high:
        return 0.0
    return ((worst_high - value) / (worst_high - best_low)) * max_points


def apply_penalty(score: float, penalty: float) -> float:
    return clamp(score - penalty, 0.0, 100.0)


def apply_cap(score: float, cap_value: float | None) -> float:
    if cap_value is None:
        return clamp(score, 0.0, 100.0)
    return clamp(min(score, cap_value), 0.0, 100.0)


def cap_for_strategy(regime: str, strategy_name: str) -> float | None:
    if regime == "transition":
        return REGIME_TRANSITION_CAP
    if regime == "chop":
        return REGIME_CHOP_CAP
    if regime == "range" and strategy_name == "trend_following":
        return REGIME_RANGE_TREND_CAP
    if regime in ("trend_up", "trend_down") and strategy_name == "mean_reversion":
        return REGIME_TREND_MEAN_REVERSION_CAP
    return None


def macro_penalty(macro_bias: str) -> float:
    if macro_bias == "neutral":
        return MACRO_NEUTRAL_PENALTY
    if macro_bias == "transition":
        return MACRO_TRANSITION_PENALTY
    return 0.0


def bos_freshness_multiplier(timeframe: str, bars_ago: int) -> float:
    if timeframe in ("5m", "15m"):
        if bars_ago <= 2:
            return 1.00
        if bars_ago <= 5:
            return 0.70
        if bars_ago <= 10:
            return 0.40
        return 0.15

    if timeframe == "1h":
        if bars_ago <= 1:
            return 1.00
        if bars_ago <= 3:
            return 0.80
        if bars_ago <= 6:
            return 0.55
        return 0.25

    # 4h or fallback
    if bars_ago <= 1:
        return 1.00
    if bars_ago <= 2:
        return 0.80
    if bars_ago <= 4:
        return 0.55
    return 0.25


def bos_quality_points(price_action: dict, expected_direction: str, timeframe: str, max_points: float) -> float:
    bos_direction = price_action.get("recent_bos_direction", "none")
    bos_failed = price_action.get("recent_bos_failed", False)
    bars_ago = int(price_action.get("recent_bos_bars_ago", 999))
    strength = float(price_action.get("recent_bos_strength", 0.0))

    if bos_failed:
        return 0.0
    if bos_direction != expected_direction:
        return 0.0

    freshness = bos_freshness_multiplier(timeframe, bars_ago)
    strength = clamp(strength, 0.0, 1.0)

    return round(max_points * freshness * (0.35 + 0.65 * strength), 2)

def derive_macro_bias(snapshot: dict):
    """
    v2 macro bias:
    bullish / bearish / neutral / transition

    transition = genuinely unstable or conflicting higher timeframe state
    neutral = no strong directional edge, but not broken
    """
    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    i4 = safe_get_indicators(snapshot, "4h")
    i1 = safe_get_indicators(snapshot, "1h")
    pa4 = safe_get_price_action(snapshot, "4h")
    pa1 = safe_get_price_action(snapshot, "1h")

    reasons = []

    structure4 = s4.get("structure_state")
    structure1 = s1.get("structure_state")

    if structure4 in ("transition", "chop") and structure1 in ("transition", "chop"):
        reasons.append("HTF_STRUCTURE_DOUBLE_UNSTABLE")
        return "transition", 52.0, reasons

    swing4 = s4.get("swing_bias", "neutral")
    swing1 = s1.get("swing_bias", "neutral")

    bull = 0.0
    bear = 0.0

    if swing4 == "bullish":
        bull += 18
        reasons.append("4H_SWING_BULLISH")
    elif swing4 == "bearish":
        bear += 18
        reasons.append("4H_SWING_BEARISH")

    if swing1 == "bullish":
        bull += 16
        reasons.append("1H_SWING_BULLISH")
    elif swing1 == "bearish":
        bear += 16
        reasons.append("1H_SWING_BEARISH")

    bull += score_linear(float(s4.get("trend_consistency_score", 0.0)), 50, 90, 14) if swing4 == "bullish" else 0.0
    bear += score_linear(float(s4.get("trend_consistency_score", 0.0)), 50, 90, 14) if swing4 == "bearish" else 0.0

    bull += score_linear(float(s1.get("trend_consistency_score", 0.0)), 45, 90, 14) if swing1 == "bullish" else 0.0
    bear += score_linear(float(s1.get("trend_consistency_score", 0.0)), 45, 90, 14) if swing1 == "bearish" else 0.0

    bull += score_linear(abs(float(i4.get("ema_separation_pct", 0.0))), 0.04, 0.30, 8) if swing4 == "bullish" else 0.0
    bear += score_linear(abs(float(i4.get("ema_separation_pct", 0.0))), 0.04, 0.30, 8) if swing4 == "bearish" else 0.0

    bull += score_linear(abs(float(i1.get("ema_separation_pct", 0.0))), 0.06, 0.60, 8) if swing1 == "bullish" else 0.0
    bear += score_linear(abs(float(i1.get("ema_separation_pct", 0.0))), 0.06, 0.60, 8) if swing1 == "bearish" else 0.0

    bull += bos_quality_points(pa4, "bullish", "4h", 6)
    bear += bos_quality_points(pa4, "bearish", "4h", 6)

    bull += bos_quality_points(pa1, "bullish", "1h", 6)
    bear += bos_quality_points(pa1, "bearish", "1h", 6)

    # softer handling of BOS failure / swing conflict
    if pa1.get("recent_bos_failed", False):
        bull = apply_penalty(bull, 5)
        bear = apply_penalty(bear, 5)
        reasons.append("HTF_BOS_FAILED")

    if swing4 != "neutral" and swing1 != "neutral" and swing4 != swing1:
        reasons.append("HTF_SWING_CONFLICT")
        if max(bull, bear) >= 40:
            return "neutral", 58.0, reasons
        return "transition", 50.0, reasons

    bull = round(clamp(bull, 0.0, 95.0), 2)
    bear = round(clamp(bear, 0.0, 95.0), 2)

    if bull >= bear + 10 and bull >= 42:
        return "bullish", bull, reasons

    if bear >= bull + 10 and bear >= 42:
        return "bearish", bear, reasons

    if max(bull, bear) >= 30:
        reasons.append("MACRO_NEUTRAL")
        return "neutral", round(max(bull, bear), 2), reasons

    reasons.append("MACRO_TRANSITION")
    return "transition", round(max(bull, bear, 25.0), 2), reasons

def detect_regime(snapshot: dict, macro_bias: str):
    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")
    i1 = safe_get_indicators(snapshot, "1h")
    pa15 = safe_get_price_action(snapshot, "15m")
    pa5 = safe_get_price_action(snapshot, "5m")

    reasons = []

    if s15.get("structure_state") == "chop":
        reasons.append("15M_CHOP")
        return "chop", 54.0, reasons

    failed_intraday_bos = pa15.get("recent_bos_failed", False) or pa5.get("recent_bos_failed", False)

    if (
        macro_bias == "bullish"
        and s4.get("swing_bias") == "bullish"
        and s1.get("swing_bias") == "bullish"
        and s1.get("structure_state") in ("clean_trend", "weak_trend")
    ):
        conf = (
            float(s4.get("trend_consistency_score", 0.0)) * 0.45
            + float(s1.get("trend_consistency_score", 0.0)) * 0.55
        )
        if failed_intraday_bos:
            conf = apply_penalty(conf, 8)
            reasons.append("FAILED_INTRADAY_BOS")
        reasons.extend(["BULLISH_MACRO", "HTF_BULLISH_STRUCTURE"])
        return "trend_up", round(clamp(conf, 0.0, 95.0), 2), reasons

    if (
        macro_bias == "bearish"
        and s4.get("swing_bias") == "bearish"
        and s1.get("swing_bias") == "bearish"
        and s1.get("structure_state") in ("clean_trend", "weak_trend")
    ):
        conf = (
            float(s4.get("trend_consistency_score", 0.0)) * 0.45
            + float(s1.get("trend_consistency_score", 0.0)) * 0.55
        )
        if failed_intraday_bos:
            conf = apply_penalty(conf, 8)
            reasons.append("FAILED_INTRADAY_BOS")
        reasons.extend(["BEARISH_MACRO", "HTF_BEARISH_STRUCTURE"])
        return "trend_down", round(clamp(conf, 0.0, 95.0), 2), reasons

    if (
        s1.get("market_type") == "range"
        and s15.get("market_type") in ("range", "transition")
        and abs(float(i1.get("ema_separation_pct", 0.0))) < 0.30
        and float(s1.get("trend_consistency_score", 0.0)) < 60
    ):
        conf = 72.0
        if pa15.get("recent_bos_direction") not in ("none",):
            conf = apply_penalty(conf, 8)
            reasons.append("RANGE_WITH_RECENT_BOS")
        reasons.append("RANGE_BEHAVIOR_CONFIRMED")
        return "range", round(conf, 2), reasons

    if macro_bias == "neutral":
        reasons.append("MACRO_NEUTRAL")
        return "transition", 58.0, reasons

    if macro_bias == "transition":
        reasons.append("MACRO_TRANSITION")
        return "transition", 52.0, reasons

    reasons.append("REGIME_UNCLEAR")
    return "transition", 55.0, reasons

def score_trend_following(snapshot: dict, regime: str, macro_bias: str):
    reasons = []
    score = 0.0

    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")

    i4 = safe_get_indicators(snapshot, "4h")
    i1 = safe_get_indicators(snapshot, "1h")
    i15 = safe_get_indicators(snapshot, "15m")
    i5 = safe_get_indicators(snapshot, "5m")

    pa1 = safe_get_price_action(snapshot, "1h")
    pa15 = safe_get_price_action(snapshot, "15m")
    pa5 = safe_get_price_action(snapshot, "5m")

    v15 = safe_get_volatility(snapshot, "15m")

    directional_bias = "bullish" if macro_bias == "bullish" else "bearish" if macro_bias == "bearish" else "bullish"

    # 1. Macro alignment (0-15)
    macro_alignment_score = 0.0
    if macro_bias in ("bullish", "bearish"):
        macro_alignment_score = 15.0
        reasons.append("MACRO_DIRECTION_PRESENT")
    elif macro_bias == "neutral":
        macro_alignment_score = 8.0
        reasons.append("MACRO_NEUTRAL")
    else:
        macro_alignment_score = 4.0
        reasons.append("MACRO_TRANSITION")
    score += macro_alignment_score

    # 2. HTF structure quality (0-20)
    htf_structure_avg = (
        float(s4.get("structure_quality_score", 0.0)) * 0.45 +
        float(s1.get("structure_quality_score", 0.0)) * 0.55
    )
    htf_structure_score = (htf_structure_avg / 100.0) * 20
    score += htf_structure_score
    if htf_structure_avg >= 70:
        reasons.append("HTF_STRUCTURE_STRONG")
    elif htf_structure_avg >= 55:
        reasons.append("HTF_STRUCTURE_OK")

    # 3. EMA strength (0-15)
    ema_strength_score = 0.0
    ema_strength_score += score_linear(abs(float(i1.get("ema_separation_pct", 0.0))), 0.06, 0.60, 6)
    ema_strength_score += score_linear(abs(float(i4.get("ema_separation_pct", 0.0))), 0.04, 0.30, 4)
    ema_strength_score += score_linear(abs(float(i15.get("price_vs_ema_slow_pct", 0.0))), 0.15, 1.80, 5)
    ema_strength_score = clamp(ema_strength_score, 0.0, 15.0)
    score += ema_strength_score
    if ema_strength_score >= 9:
        reasons.append("EMA_STRENGTH_OK")

    # 4. BOS quality & freshness (0-15)
    bos_score = 0.0
    bos_score += max(
        bos_quality_points(pa15, "bullish", "15m", 10),
        bos_quality_points(pa15, "bearish", "15m", 10),
    )
    bos_score += max(
        bos_quality_points(pa1, "bullish", "1h", 5),
        bos_quality_points(pa1, "bearish", "1h", 5),
    )

    if pa15.get("recent_bos_failed", False) or pa1.get("recent_bos_failed", False):
        bos_score -= 4
        reasons.append("BOS_FAILURE_RISK")

    if (
        pa15.get("recent_bos_direction") not in ("bullish", "bearish", "none")
        or pa1.get("recent_bos_direction") not in ("bullish", "bearish", "none")
    ):
        bos_score -= 2

    bos_score = clamp(bos_score, 0.0, 15.0)
    score += bos_score
    if bos_score >= 8:
        reasons.append("BOS_FRESH_ALIGN")

    # 5. Pullback / continuation quality (0-15)
    pullback_score = 0.0

    pullback_state_15 = pa15.get("pullback_state", "no_pullback")
    pullback_bars_15 = int(pa15.get("pullback_bars_ago", 999))
    pullback_quality_15 = float(pa15.get("pullback_quality_score", 0.0))
    expansion_state_15 = pa15.get("expansion_state", "none")

    if pullback_state_15 in ("shallow_pullback", "active_pullback"):
        pullback_score += (pullback_quality_15 / 100.0) * 10
        if pullback_bars_15 <= 3:
            pullback_score += 3
        reasons.append("PULLBACK_VALID")
    elif pullback_state_15 == "no_pullback":
        pullback_score += 5
        if expansion_state_15 == "healthy_expansion":
            pullback_score += 3
            reasons.append("CONTINUATION_ENTRY")
        else:
            reasons.append("NO_PULLBACK_YET")
    elif pullback_state_15 in ("deep_pullback", "reversal_risk"):
        pullback_score += 1
        reasons.append("PULLBACK_TOO_DEEP")

    pullback_state_5 = pa5.get("pullback_state", "no_pullback")
    pullback_bars_5 = int(pa5.get("pullback_bars_ago", 999))
    if pullback_state_5 in ("shallow_pullback", "active_pullback") and pullback_bars_5 <= 2:
        pullback_score += 2

    pullback_score = clamp(pullback_score, 0.0, 15.0)
    score += pullback_score

    # 6. Momentum quality (0-10)
    momentum_score = 0.0
    momentum_score += score_linear(abs(float(i1.get("macd_histogram_slope", 0.0))), 0.0, 40.0, 4)
    momentum_score += score_linear(abs(float(i15.get("macd_histogram_slope", 0.0))), 0.0, 20.0, 4)

    rsi_state = i15.get("rsi_state")
    if rsi_state not in ("oversold", "overbought"):
        momentum_score += 2

    momentum_score = clamp(momentum_score, 0.0, 10.0)
    score += momentum_score
    if momentum_score >= 6:
        reasons.append("MOMENTUM_CONFIRM")

    # 7. Volatility suitability (0-10)
    vol_state = v15.get("volatility_state", "medium")
    expansion_state = pa15.get("expansion_state", "none")

    volatility_score = 0.0
    if vol_state == "medium":
        volatility_score = 8.0
    elif vol_state == "low":
        volatility_score = 6.0
    else:
        volatility_score = 4.0

    if expansion_state == "healthy_expansion":
        volatility_score += 2.0
    elif expansion_state == "overextended_expansion":
        volatility_score -= 1.0

    volatility_score = clamp(volatility_score, 0.0, 10.0)
    score += volatility_score
    if volatility_score >= 7:
        reasons.append("VOLATILITY_SUITABLE")

    # soft macro penalty
    score = apply_penalty(score, macro_penalty(macro_bias))

    # regime cap
    capped_score = apply_cap(score, cap_for_strategy(regime, "trend_following"))

    breakdown = {
        "macro_alignment": round(macro_alignment_score, 2),
        "htf_structure_quality": round(htf_structure_score, 2),
        "ema_strength": round(ema_strength_score, 2),
        "bos_quality_freshness": round(bos_score, 2),
        "pullback_quality": round(pullback_score, 2),
        "momentum_quality": round(momentum_score, 2),
        "volatility_suitability": round(volatility_score, 2),
        "macro_penalty": round(macro_penalty(macro_bias), 2),
        "score_cap": cap_for_strategy(regime, "trend_following"),
        "raw_score": round(clamp(score, 0.0, 100.0), 2),
        "final_score": round(clamp(capped_score, 0.0, 100.0), 2),
    }

    return round(clamp(capped_score, 0.0, 100.0), 2), reasons, breakdown

def determine_mean_reversion_side(snapshot: dict):
    s15 = safe_get_structure(snapshot, "15m")
    i15 = safe_get_indicators(snapshot, "15m")

    dist_high = float(s15.get("distance_to_range_high_pct", 50.0))
    dist_low = float(s15.get("distance_to_range_low_pct", 50.0))
    rsi = float(i15.get("rsi", 50.0))

    # Prefer the closer range edge first
    if dist_low <= dist_high:
        side = "long"
        if rsi > 60 and dist_high < dist_low:
            side = "short"
    else:
        side = "short"
        if rsi < 40 and dist_low < dist_high:
            side = "long"

    return side

def score_mean_reversion(snapshot: dict, regime: str):
    side = determine_mean_reversion_side(snapshot)
    reasons = []
    score = 0.0

    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")
    i1 = safe_get_indicators(snapshot, "1h")
    i15 = safe_get_indicators(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")
    v15 = safe_get_volatility(snapshot, "15m")

    dist_high = float(s15.get("distance_to_range_high_pct", 50.0))
    dist_low = float(s15.get("distance_to_range_low_pct", 50.0))
    rsi = float(i15.get("rsi", 50.0))

    # 1. Range quality (0-25)
    range_quality = 0.0
    if s1.get("market_type") == "range":
        range_quality += 10
    if s15.get("market_type") == "range":
        range_quality += 12
    if s15.get("market_type") == "transition":
        range_quality += 5

    range_quality -= score_linear(float(s1.get("trend_consistency_score", 0.0)), 50, 80, 6)
    range_quality = clamp(range_quality, 0.0, 25.0)
    score += range_quality
    if range_quality >= 14:
        reasons.append("RANGE_QUALITY_OK")

    # 2. Boundary proximity (0-20)
    if side == "long":
        boundary_score = score_inverse(dist_low, 5, 35, 20)
        if boundary_score >= 10:
            reasons.append("NEAR_RANGE_LOW")
    else:
        boundary_score = score_inverse(dist_high, 5, 35, 20)
        if boundary_score >= 10:
            reasons.append("NEAR_RANGE_HIGH")
    score += boundary_score

    # 3. RSI stretch (0-15)
    if side == "long":
        rsi_score = score_inverse(rsi, 30, 50, 15)
        if rsi_score >= 8:
            reasons.append("RSI_STRETCH_LONG")
    else:
        rsi_score = score_linear(rsi, 50, 70, 15)
        if rsi_score >= 8:
            reasons.append("RSI_STRETCH_SHORT")
    score += rsi_score

    # 4. Trend weakness (0-15)
    trend_weakness = 0.0
    trend_weakness += score_inverse(abs(float(i1.get("ema_separation_pct", 0.0))), 0.10, 0.60, 7)
    trend_weakness += score_inverse(float(s1.get("trend_consistency_score", 0.0)), 30, 70, 8)
    trend_weakness = clamp(trend_weakness, 0.0, 15.0)
    score += trend_weakness
    if trend_weakness >= 8:
        reasons.append("TREND_WEAKNESS_OK")

    # 5. Anti-breakout / BOS filter (0-10)
    bos_score = 0.0
    bos_direction = pa15.get("recent_bos_direction", "none")
    bos_failed = pa15.get("recent_bos_failed", False)
    bos_bars_ago = int(pa15.get("recent_bos_bars_ago", 999))

    if bos_direction == "none":
        bos_score = 10.0
        reasons.append("NO_FRESH_BOS")
    elif bos_failed:
        bos_score = 8.0
        reasons.append("FAILED_BOS_SUPPORTS_REVERT")
    elif bos_bars_ago > 5:
        bos_score = 5.0
        reasons.append("STALE_BOS")
    else:
        bos_score = 2.0
        reasons.append("FRESH_BOS_BREAKS_RANGE")
    score += bos_score

    # 6. Volatility suitability (0-5)
    vol_state = v15.get("volatility_state", "medium")
    if vol_state == "low":
        vol_score = 5.0
    elif vol_state == "medium":
        vol_score = 4.0
    else:
        vol_score = 2.0
    score += vol_score

    # 7. Invalidation clarity (0-10)
    range_high = float(s15.get("range_high", 0.0))
    range_low = float(s15.get("range_low", 0.0))
    atr = float(i15.get("atr", 0.0))
    range_span = range_high - range_low

    invalidation_score = 0.0
    if range_span > 0 and atr > 0:
        invalidation_score = clamp(score_linear(range_span / atr, 1.5, 5.0, 10), 0.0, 10.0)
    score += invalidation_score
    if invalidation_score >= 5:
        reasons.append("CLEAR_INVALIDATION")

    capped_score = apply_cap(score, cap_for_strategy(regime, "mean_reversion"))

    breakdown = {
        "range_quality": round(range_quality, 2),
        "boundary_proximity": round(boundary_score, 2),
        "rsi_stretch": round(rsi_score, 2),
        "trend_weakness": round(trend_weakness, 2),
        "anti_breakout_filter": round(bos_score, 2),
        "volatility_suitability": round(vol_score, 2),
        "invalidation_clarity": round(invalidation_score, 2),
        "score_cap": cap_for_strategy(regime, "mean_reversion"),
        "raw_score": round(clamp(score, 0.0, 100.0), 2),
        "final_score": round(clamp(capped_score, 0.0, 100.0), 2),
    }

    return round(clamp(capped_score, 0.0, 100.0), 2), reasons, side, breakdown

def build_trend_following_proposal(
    symbol: str,
    snapshot: dict,
    regime: str,
    score: float,
    reasons: list[str],
    score_breakdown: dict,
):
    tf_15m = safe_get_tf(snapshot, "15m")
    i15 = tf_15m.get("indicators", {})
    s15 = tf_15m.get("structure", {})
    candles_15m = tf_15m.get("candles", [])

    latest_close = float(candles_15m[-1]["close"]) if candles_15m else float(i15.get("ema_fast", 0.0))
    entry_price = float(i15.get("ema_fast", latest_close))
    atr_15m = float(i15.get("atr", 0.0))

    if regime == "trend_up":
        decision = "long"
        stop_loss = min(
            float(i15.get("ema_slow", entry_price * 0.99)),
            entry_price - (1.2 * atr_15m if atr_15m > 0 else entry_price * 0.01)
        )
        risk_per_unit = max(1.0, entry_price - stop_loss)
        tp1 = max(float(s15.get("range_high", 0.0)), entry_price + risk_per_unit * 1.0)
        tp2 = entry_price + risk_per_unit * 2.0
        tp3 = entry_price + risk_per_unit * 3.5
    else:
        decision = "short"
        stop_loss = max(
            float(i15.get("ema_slow", entry_price * 1.01)),
            entry_price + (1.2 * atr_15m if atr_15m > 0 else entry_price * 0.01)
        )
        risk_per_unit = max(1.0, stop_loss - entry_price)
        tp1 = min(float(s15.get("range_low", entry_price)), entry_price - risk_per_unit * 1.0)
        tp2 = entry_price - risk_per_unit * 2.0
        tp3 = entry_price - risk_per_unit * 3.5

    return {
        "ok": True,
        "symbol": symbol,
        "regime": regime,
        "selected_strategy": "trend_following",
        "best_strategy_candidate": "trend_following",
        "best_strategy_score": round(score, 2),
        "decision": decision,
        "confidence": round(score, 2),  # keep for backward compatibility
        "setup_confidence": round(score, 2),
        "decision_confidence": round(score, 2),
        "entry_order_type": "limit",
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "tp1_price": round(tp1, 8),
        "tp2_price": round(tp2, 8),
        "tp3_price": round(tp3, 8),
        "reason_tags": reasons,
        "score_breakdown": score_breakdown,
       "score_thresholds": {
            "trade_minimum_required": TRADE_SCORE_THRESHOLD,
            "observe_minimum_required": OBSERVE_SCORE_THRESHOLD,
            "trend_following_score": round(score, 2),
            "mean_reversion_score": None,
            "best_strategy_score": round(score, 2),
        },
    }

def build_mean_reversion_proposal(
    symbol: str,
    snapshot: dict,
    score: float,
    reasons: list[str],
    side: str,
    score_breakdown: dict,
):
    tf_15m = safe_get_tf(snapshot, "15m")
    s15 = tf_15m.get("structure", {})
    i15 = tf_15m.get("indicators", {})

    range_high = float(s15.get("range_high", 0.0))
    range_low = float(s15.get("range_low", 0.0))
    mid_range = (range_high + range_low) / 2 if range_high and range_low else float(i15.get("ema_fast", 0.0))
    atr_15m = float(i15.get("atr", 0.0))

    if side == "long":
        entry_price = max(range_low, float(i15.get("ema_fast", range_low)))
        stop_loss = range_low - (0.4 * atr_15m if atr_15m > 0 else range_low * 0.003)
        tp1 = mid_range
        tp2 = range_high
        tp3 = range_high + (0.25 * atr_15m if atr_15m > 0 else range_high * 0.002)
        decision = "long"
    else:
        entry_price = min(range_high, float(i15.get("ema_fast", range_high)))
        stop_loss = range_high + (0.4 * atr_15m if atr_15m > 0 else range_high * 0.003)
        tp1 = mid_range
        tp2 = range_low
        tp3 = range_low - (0.25 * atr_15m if atr_15m > 0 else range_low * 0.002)
        decision = "short"

    return {
        "ok": True,
        "symbol": symbol,
        "regime": "range",
        "selected_strategy": "mean_reversion",
        "best_strategy_candidate": "mean_reversion",
        "best_strategy_score": round(score, 2),
        "decision": decision,
        "confidence": round(score, 2),  # keep for backward compatibility
        "setup_confidence": round(score, 2),
        "decision_confidence": round(score, 2),
        "entry_order_type": "limit",
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "tp1_price": round(tp1, 8),
        "tp2_price": round(tp2, 8),
        "tp3_price": round(tp3, 8),
        "reason_tags": reasons,
        "score_breakdown": score_breakdown,
        "score_thresholds": {
            "trade_minimum_required": TRADE_SCORE_THRESHOLD,
            "observe_minimum_required": OBSERVE_SCORE_THRESHOLD,
            "trend_following_score": None,
            "mean_reversion_score": round(score, 2),
            "best_strategy_score": round(score, 2),
        },
    }

def build_no_trade_payload(
    symbol: str,
    macro_bias: str,
    macro_conf: float,
    regime: str,
    regime_conf: float,
    trend_score: float,
    mean_score: float,
    reason_tags: list[str],
    hard_block: bool = False,
    trend_breakdown: dict | None = None,
    mean_breakdown: dict | None = None,
):
    best_strategy_candidate = "trend_following" if trend_score >= mean_score else "mean_reversion"
    best_strategy_score = round(max(trend_score, mean_score), 2)

    setup_confidence = 0.0 if hard_block else best_strategy_score

    return {
        "ok": True,
        "symbol": symbol,
        "macro_bias": macro_bias,
        "macro_confidence": macro_conf,
        "regime": regime,
        "regime_confidence": regime_conf,
        "strategy_scores": {
            "trend_following": round(trend_score, 2),
            "mean_reversion": round(mean_score, 2)
        },
        "selected_strategy": "none",
        "best_strategy_candidate": best_strategy_candidate,
        "best_strategy_score": best_strategy_score,
        "decision": "no_trade",
        "confidence": 0.0,  # keep old field for compatibility
        "setup_confidence": round(setup_confidence, 2),
        "decision_confidence": 0.0,
        "reason_tags": reason_tags,
        "score_breakdown": {
            "trend_following": trend_breakdown or {},
            "mean_reversion": mean_breakdown or {},
        },
        "score_thresholds": {
            "trade_minimum_required": TRADE_SCORE_THRESHOLD,
            "observe_minimum_required": OBSERVE_SCORE_THRESHOLD,
            "trend_following_score": round(trend_score, 2),
            "mean_reversion_score": round(mean_score, 2),
            "best_strategy_score": best_strategy_score,
        },
    }

def build_observe_payload(
    symbol: str,
    macro_bias: str,
    macro_conf: float,
    regime: str,
    regime_conf: float,
    trend_score: float,
    mean_score: float,
    selected_strategy: str,
    decision_side: str,
    reason_tags: list[str],
    trend_breakdown: dict | None = None,
    mean_breakdown: dict | None = None,
):
    best_strategy_candidate = "trend_following" if trend_score >= mean_score else "mean_reversion"
    best_strategy_score = round(max(trend_score, mean_score), 2)

    return {
        "ok": True,
        "symbol": symbol,
        "macro_bias": macro_bias,
        "macro_confidence": macro_conf,
        "regime": regime,
        "regime_confidence": regime_conf,
        "strategy_scores": {
            "trend_following": round(trend_score, 2),
            "mean_reversion": round(mean_score, 2)
        },
        "selected_strategy": selected_strategy,
        "best_strategy_candidate": best_strategy_candidate,
        "best_strategy_score": best_strategy_score,
        "decision": "observe",
        "observe_side": decision_side,
        "confidence": best_strategy_score,
        "setup_confidence": best_strategy_score,
        "decision_confidence": round(best_strategy_score * 0.85, 2),
        "reason_tags": reason_tags,
        "score_breakdown": {
            "trend_following": trend_breakdown or {},
            "mean_reversion": mean_breakdown or {},
        },
        "score_thresholds": {
            "trade_minimum_required": TRADE_SCORE_THRESHOLD,
            "observe_minimum_required": OBSERVE_SCORE_THRESHOLD,
            "trend_following_score": round(trend_score, 2),
            "mean_reversion_score": round(mean_score, 2),
            "best_strategy_score": best_strategy_score,
        },
    }

def analyze_symbol(symbol: str):
    snapshot_payload, error = fetch_snapshot(symbol)
    if error:
        return {
            "ok": False,
            "error": error,
            "symbol": symbol
        }

    macro_bias, macro_conf, macro_reasons = derive_macro_bias(snapshot_payload)
    regime, regime_conf, regime_reasons = detect_regime(snapshot_payload, macro_bias)

    trend_score, trend_reasons, trend_breakdown = score_trend_following(
        snapshot_payload, regime, macro_bias
    )
    mean_score, mean_reasons, mean_side, mean_breakdown = score_mean_reversion(
        snapshot_payload, regime
    )

    best_strategy = "trend_following" if trend_score >= mean_score else "mean_reversion"
    best_score = max(trend_score, mean_score)

    if best_strategy == "trend_following":
        selected_side = "long" if macro_bias != "bearish" else "short"
        full_reasons = macro_reasons + regime_reasons + trend_reasons
    else:
        selected_side = mean_side
        full_reasons = macro_reasons + regime_reasons + mean_reasons

    if best_score >= TRADE_SCORE_THRESHOLD:
        if best_strategy == "trend_following":
            proposal = build_trend_following_proposal(
                symbol,
                snapshot_payload,
                regime,
                trend_score,
                full_reasons,
                trend_breakdown,
            )
        else:
            proposal = build_mean_reversion_proposal(
                symbol,
                snapshot_payload,
                mean_score,
                full_reasons,
                mean_side,
                mean_breakdown,
            )
    elif best_score >= OBSERVE_SCORE_THRESHOLD:
        return build_observe_payload(
            symbol=symbol,
            macro_bias=macro_bias,
            macro_conf=macro_conf,
            regime=regime,
            regime_conf=regime_conf,
            trend_score=trend_score,
            mean_score=mean_score,
            selected_strategy=best_strategy,
            decision_side=selected_side,
            reason_tags=full_reasons + ["OBSERVE_THRESHOLD_MET"],
            trend_breakdown=trend_breakdown,
            mean_breakdown=mean_breakdown,
        )
    else:
        return build_no_trade_payload(
            symbol=symbol,
            macro_bias=macro_bias,
            macro_conf=macro_conf,
            regime=regime,
            regime_conf=regime_conf,
            trend_score=trend_score,
            mean_score=mean_score,
            reason_tags=full_reasons + ["TRADE_THRESHOLD_NOT_MET"],
            hard_block=False,
            trend_breakdown=trend_breakdown,
            mean_breakdown=mean_breakdown,
        )

    proposal["macro_bias"] = macro_bias
    proposal["macro_confidence"] = macro_conf
    proposal["regime_confidence"] = regime_conf
    proposal["strategy_scores"] = {
        "trend_following": round(trend_score, 2),
        "mean_reversion": round(mean_score, 2)
    }
    proposal["score_thresholds"] = {
        "trade_minimum_required": TRADE_SCORE_THRESHOLD,
        "observe_minimum_required": OBSERVE_SCORE_THRESHOLD,
        "trend_following_score": round(trend_score, 2),
        "mean_reversion_score": round(mean_score, 2),
        "best_strategy_score": round(max(trend_score, mean_score), 2),
    }
    return proposal

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
                "timestamp": iso_now(),
                "strict_score_threshold_legacy": STRICT_SCORE_THRESHOLD,
                "trade_score_threshold": TRADE_SCORE_THRESHOLD,
                "observe_score_threshold": OBSERVE_SCORE_THRESHOLD
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/analyze":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                symbol = payload.get("symbol")
                if not symbol:
                    self._send_json({
                        "ok": False,
                        "error": "missing_symbol"
                    }, status=400)
                    return

                result = analyze_symbol(symbol.upper())
                self._send_json(result, status=200 if result.get("ok") else 400)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
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