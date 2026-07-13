"""
Phase 4 Step 8 — v1 threshold and decision policy parity.

This module turns entry validation + v1 score into the Strategy Signal v2
decision family:

    no_trade
    observe
    trade_candidate

It does not validate entries, calculate scores, calculate SL/TP, size
positions, or execute trades.
"""

from __future__ import annotations

from typing import Any

from strategy_signal_contract import (
    STRATEGY_ENGINE_CONTRACT_VERSION,
    STRATEGY_ENGINE_VERSION,
    STRATEGY_SIGNAL_SCHEMA_VERSION,
    V1_PARITY_MODE,
)

DECISION_POLICY_VERSION = "phase4_step8_v1_threshold_decision_policy"

SIGNAL_THRESHOLD_NORMAL = 70
SIGNAL_THRESHOLD_DRAWDOWN = 85
SIGNAL_THRESHOLD_HOT_STREAK = 65
BTC_SCORE_THRESHOLD = 80
OBSERVE_THRESHOLD_DEFAULT = 50
BTC_SKIP_CHOPPY_REGIMES = True

TRADE_DECISION = "trade_candidate"
OBSERVE_DECISION = "observe"
NO_TRADE_DECISION = "no_trade"

LEGACY_DECISION_MAP = {
    TRADE_DECISION: "trade",
    OBSERVE_DECISION: "observe",
    NO_TRADE_DECISION: "no_trade",
}


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").replace("-", "").upper()


def is_btc_symbol(symbol: str) -> bool:
    return normalize_symbol(symbol).startswith("BTC")


def normalize_regime(regime: Any) -> str:
    value = str(regime or "").strip()
    aliases = {
        "trend_up": "Uptrend",
        "uptrend": "Uptrend",
        "bullish": "Uptrend",
        "trend_down": "Downtrend",
        "downtrend": "Downtrend",
        "bearish": "Downtrend",
        "range": "Sideways",
        "sideways": "Sideways",
        "chop": "Sideways",
        "choppy": "Sideways",
        "transition": "unknown",
        "neutral": "unknown",
    }
    return aliases.get(value.lower(), value if value in ("Uptrend", "Downtrend", "Sideways") else "unknown")


def normalize_decision_side(direction: Any) -> str:
    value = str(direction or "").lower()
    if value in ("long", "short"):
        return value
    return "neutral"


def bool_from_context(context: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if bool(context.get(key, False)):
            return True
    return False


def determine_trade_threshold(
    symbol: str,
    account_context: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    """
    Determine the v1 trade threshold.

    Priority is intentionally conservative:
    drawdown > BTC > hot streak > normal

    Drawdown overrides hot streak because v1 used drawdown mode to demand
    higher-quality signals.
    """
    context = account_context or {}
    reasons: list[str] = []

    if bool_from_context(context, "in_drawdown", "drawdown_mode", "daily_drawdown_active"):
        reasons.append("THRESHOLD_DRAWDOWN_MODE")
        return SIGNAL_THRESHOLD_DRAWDOWN, reasons

    if is_btc_symbol(symbol):
        reasons.append("THRESHOLD_BTC")
        return BTC_SCORE_THRESHOLD, reasons

    if bool_from_context(context, "hot_streak", "hot_streak_mode"):
        reasons.append("THRESHOLD_HOT_STREAK")
        return SIGNAL_THRESHOLD_HOT_STREAK, reasons

    reasons.append("THRESHOLD_NORMAL")
    return SIGNAL_THRESHOLD_NORMAL, reasons


def build_score_thresholds(
    symbol: str,
    account_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trade_threshold, reasons = determine_trade_threshold(symbol, account_context)

    return {
        "policy_version": DECISION_POLICY_VERSION,
        "trade_minimum_required": trade_threshold,
        "observe_minimum_required": OBSERVE_THRESHOLD_DEFAULT,
        "normal_trade_threshold": SIGNAL_THRESHOLD_NORMAL,
        "drawdown_trade_threshold": SIGNAL_THRESHOLD_DRAWDOWN,
        "hot_streak_trade_threshold": SIGNAL_THRESHOLD_HOT_STREAK,
        "btc_trade_threshold": BTC_SCORE_THRESHOLD,
        "threshold_reason_tags": reasons,
    }


def should_skip_btc_regime(symbol: str, regime: str, selected_strategy: str) -> tuple[bool, str | None]:
    if not BTC_SKIP_CHOPPY_REGIMES:
        return False, None

    if not is_btc_symbol(symbol):
        return False, None

    normalized_regime = normalize_regime(regime)
    if normalized_regime == "Sideways" or selected_strategy == "mean_reversion":
        return True, "BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME"

    return False, None


def legacy_decision_for(decision: str) -> str:
    return LEGACY_DECISION_MAP.get(decision, "no_trade")


def build_decision_payload(
    *,
    symbol: str,
    decision: str,
    decision_side: str,
    selected_strategy: str,
    regime: str,
    regime_strategy: str,
    score: float,
    score_thresholds: dict[str, Any],
    entry_validation: dict[str, Any],
    score_breakdown: dict[str, Any],
    reason_tags: list[str],
    proposed_trade: dict[str, Any] | None = None,
    snapshot_refs: dict[str, Any] | None = None,
    candidate_filter_context: dict[str, Any] | None = None,
    ok: bool = True,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "schema_version": STRATEGY_SIGNAL_SCHEMA_VERSION,
        "strategy_engine_version": STRATEGY_ENGINE_VERSION,
        "contract_version": STRATEGY_ENGINE_CONTRACT_VERSION,
        "decision_policy_version": DECISION_POLICY_VERSION,
        "v1_parity_mode": V1_PARITY_MODE,
        "symbol": normalize_symbol(symbol),
        "decision": decision,
        "legacy_decision": legacy_decision_for(decision),
        "decision_side": normalize_decision_side(decision_side),
        "selected_strategy": selected_strategy or "none",
        "regime": normalize_regime(regime),
        "regime_strategy": regime_strategy or "unknown",
        "score": round(float(score or 0.0), 2),
        "score_thresholds": score_thresholds,
        "entry_validation": entry_validation,
        "score_breakdown": score_breakdown,
        "reason_tags": sorted(set(reason_tags)),
        "proposed_trade": proposed_trade,
        "snapshot_refs": snapshot_refs or {},
        "candidate_filter_context": candidate_filter_context,
    }


def decide_strategy_signal(
    *,
    symbol: str,
    regime_route: dict[str, Any],
    entry_validation: dict[str, Any],
    score_result: dict[str, Any],
    account_context: dict[str, Any] | None = None,
    snapshot_refs: dict[str, Any] | None = None,
    candidate_filter_context: dict[str, Any] | None = None,
    proposed_trade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Convert route + validation + score into Strategy Signal v2 decision.

    This function should be called by analyzer orchestration in Step 10 after:
    1. regime routing
    2. entry validation
    3. v1 score calculation
    4. proposed trade levels from Step 9
    """
    symbol_norm = normalize_symbol(symbol)
    route = regime_route or {}
    validation = entry_validation or {}
    score_payload = score_result or {}

    selected_strategy = route.get("selected_strategy", "none")
    regime = normalize_regime(route.get("regime"))
    regime_strategy = route.get("regime_strategy", "unknown")
    direction = normalize_decision_side(validation.get("direction") or route.get("direction_hint"))
    score = float(score_payload.get("score", 0.0) or 0.0)

    thresholds = build_score_thresholds(symbol_norm, account_context)

    reason_tags: list[str] = []
    reason_tags.extend(route.get("reason_tags", []) or [])
    reason_tags.extend(validation.get("failed_conditions", []) or [])
    reason_tags.extend(validation.get("passed_conditions", []) or [])
    reason_tags.extend(score_payload.get("reason_tags", []) or [])
    reason_tags.extend(thresholds.get("threshold_reason_tags", []) or [])

    if not route.get("valid", False):
        reason_tags.append("ROUTE_INVALID")
        return build_decision_payload(
            symbol=symbol_norm,
            decision=NO_TRADE_DECISION,
            decision_side="neutral",
            selected_strategy="none",
            regime=regime,
            regime_strategy=regime_strategy,
            score=score,
            score_thresholds=thresholds,
            entry_validation=validation,
            score_breakdown=score_payload.get("breakdown", {}),
            reason_tags=reason_tags,
            proposed_trade=None,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
        )

    if not validation.get("valid", False):
        reason_tags.append("ENTRY_VALIDATION_FAILED")
        return build_decision_payload(
            symbol=symbol_norm,
            decision=NO_TRADE_DECISION,
            decision_side=direction,
            selected_strategy=selected_strategy,
            regime=regime,
            regime_strategy=regime_strategy,
            score=score,
            score_thresholds=thresholds,
            entry_validation=validation,
            score_breakdown=score_payload.get("breakdown", {}),
            reason_tags=reason_tags,
            proposed_trade=None,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
        )

    skip_btc, skip_reason = should_skip_btc_regime(symbol_norm, regime, selected_strategy)
    if skip_btc:
        reason_tags.append(skip_reason or "BTC_REGIME_SKIPPED")
        return build_decision_payload(
            symbol=symbol_norm,
            decision=NO_TRADE_DECISION,
            decision_side=direction,
            selected_strategy=selected_strategy,
            regime=regime,
            regime_strategy=regime_strategy,
            score=score,
            score_thresholds=thresholds,
            entry_validation=validation,
            score_breakdown=score_payload.get("breakdown", {}),
            reason_tags=reason_tags,
            proposed_trade=None,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
        )

    trade_threshold = float(thresholds["trade_minimum_required"])
    observe_threshold = float(thresholds["observe_minimum_required"])

    if score >= trade_threshold:
        reason_tags.append("SCORE_MEETS_TRADE_THRESHOLD")
        return build_decision_payload(
            symbol=symbol_norm,
            decision=TRADE_DECISION,
            decision_side=direction,
            selected_strategy=selected_strategy,
            regime=regime,
            regime_strategy=regime_strategy,
            score=score,
            score_thresholds=thresholds,
            entry_validation=validation,
            score_breakdown=score_payload.get("breakdown", {}),
            reason_tags=reason_tags,
            proposed_trade=proposed_trade,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
        )

    if score >= observe_threshold:
        reason_tags.append("SCORE_MEETS_OBSERVE_THRESHOLD")
        reason_tags.append("SCORE_BELOW_TRADE_THRESHOLD")
        return build_decision_payload(
            symbol=symbol_norm,
            decision=OBSERVE_DECISION,
            decision_side=direction,
            selected_strategy=selected_strategy,
            regime=regime,
            regime_strategy=regime_strategy,
            score=score,
            score_thresholds=thresholds,
            entry_validation=validation,
            score_breakdown=score_payload.get("breakdown", {}),
            reason_tags=reason_tags,
            proposed_trade=None,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
        )

    reason_tags.append("SCORE_BELOW_OBSERVE_THRESHOLD")
    return build_decision_payload(
        symbol=symbol_norm,
        decision=NO_TRADE_DECISION,
        decision_side=direction,
        selected_strategy=selected_strategy,
        regime=regime,
        regime_strategy=regime_strategy,
        score=score,
        score_thresholds=thresholds,
        entry_validation=validation,
        score_breakdown=score_payload.get("breakdown", {}),
        reason_tags=reason_tags,
        proposed_trade=None,
        snapshot_refs=snapshot_refs,
        candidate_filter_context=candidate_filter_context,
    )


def build_decision_policy_contract() -> dict[str, Any]:
    return {
        "decision_policy_version": DECISION_POLICY_VERSION,
        "decisions": [NO_TRADE_DECISION, OBSERVE_DECISION, TRADE_DECISION],
        "legacy_decision_map": LEGACY_DECISION_MAP,
        "thresholds": {
            "normal_trade_threshold": SIGNAL_THRESHOLD_NORMAL,
            "drawdown_trade_threshold": SIGNAL_THRESHOLD_DRAWDOWN,
            "hot_streak_trade_threshold": SIGNAL_THRESHOLD_HOT_STREAK,
            "btc_trade_threshold": BTC_SCORE_THRESHOLD,
            "observe_threshold_default": OBSERVE_THRESHOLD_DEFAULT,
        },
        "threshold_priority": ["drawdown", "btc", "hot_streak", "normal"],
        "btc_skip_choppy_regimes": BTC_SKIP_CHOPPY_REGIMES,
        "does_not_validate_entries": True,
        "does_not_score": True,
        "does_not_calculate_sltp": True,
        "does_not_size_positions": True,
        "does_not_execute": True,
    }
