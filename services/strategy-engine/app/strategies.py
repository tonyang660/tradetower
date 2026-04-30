from scoring_utils import (
    apply_cap,
    apply_penalty,
    bos_quality_points,
    cap_for_strategy,
    clamp,
    macro_penalty,
    score_inverse,
    score_linear,
)
from snapshot_accessors import safe_get_indicators, safe_get_price_action, safe_get_structure, safe_get_volatility


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
