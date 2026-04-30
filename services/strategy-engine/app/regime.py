from scoring_utils import apply_penalty, clamp
from snapshot_accessors import safe_get_indicators, safe_get_price_action, safe_get_structure


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
