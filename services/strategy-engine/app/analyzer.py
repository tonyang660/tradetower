from config import OBSERVE_SCORE_THRESHOLD, TRADE_SCORE_THRESHOLD
from http_client import fetch_snapshot
from macro import derive_macro_bias
from proposals import (
    build_mean_reversion_proposal,
    build_no_trade_payload,
    build_observe_payload,
    build_trend_following_proposal,
)
from regime import detect_regime
from strategies import score_mean_reversion, score_trend_following


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
