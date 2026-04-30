from config import (
    MACRO_NEUTRAL_PENALTY,
    MACRO_TRANSITION_PENALTY,
    REGIME_CHOP_CAP,
    REGIME_RANGE_TREND_CAP,
    REGIME_TRANSITION_CAP,
    REGIME_TREND_MEAN_REVERSION_CAP,
)


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
