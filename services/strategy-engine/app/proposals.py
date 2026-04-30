from config import OBSERVE_SCORE_THRESHOLD, TRADE_SCORE_THRESHOLD
from snapshot_accessors import safe_get_tf


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
