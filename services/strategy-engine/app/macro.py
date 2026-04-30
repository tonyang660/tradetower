from scoring_utils import apply_penalty, bos_quality_points, clamp, score_linear
from snapshot_accessors import safe_get_indicators, safe_get_price_action, safe_get_structure


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
