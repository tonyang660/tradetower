"""
Phase 4 Step 10 — analyzer orchestration replacement.

This replaces the old Strategy Engine analyzer path with the v1 full-port
pipeline assembled in Phase 4 Steps 1-9:

    Feature Factory MarketSnapshot v2
    -> snapshot_v1_adapter
    -> regime_router
    -> v1_entry_logic
    -> v1_signal_scorer
    -> v1_trade_levels
    -> v1_decision_policy
    -> strategy_signal_v2

Compatibility fields are included so the existing Scheduler/Risk flow can keep
working until Step 12 patches downstream consumers explicitly.
"""

from __future__ import annotations

from typing import Any

from http_client import fetch_snapshot
from regime_router import route_regime
from snapshot_v1_adapter import build_snapshot_refs, validate_snapshot_for_strategy
from strategy_signal_contract import build_no_trade_signal
from v1_decision_policy import (
    NO_TRADE_DECISION,
    OBSERVE_DECISION,
    TRADE_DECISION,
    decide_strategy_signal,
)
from v1_entry_logic import check_v1_entry
from v1_signal_scorer import score_v1_signal
from v1_trade_levels import build_proposed_trade

ANALYZER_ORCHESTRATION_VERSION = "phase4_step10_v1_analyzer_orchestration"


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").replace("-", "").upper()


def _legacy_entry_fields(signal: dict[str, Any]) -> dict[str, Any]:
    """
    Preserve the old Scheduler/Risk fields until Step 12 updates downstream
    compatibility explicitly.
    """
    proposed_trade = signal.get("proposed_trade") or {}
    decision = signal.get("decision")
    legacy_decision = signal.get("legacy_decision")

    # Current scheduler looks for decision == "trade". Until Step 12, expose
    # both v2 decision and the legacy decision.
    signal["v2_decision"] = decision
    signal["decision"] = legacy_decision

    signal["position_side"] = signal.get("decision_side")
    signal["confidence"] = signal.get("score", 0.0)
    signal["selected_strategy"] = signal.get("selected_strategy", "none")
    signal["regime"] = signal.get("regime", "unknown")

    if proposed_trade:
        signal["entry_order_type"] = proposed_trade.get("entry_order_type")
        signal["entry_price"] = proposed_trade.get("entry_price")
        signal["stop_loss"] = proposed_trade.get("stop_loss")
        signal["take_profits"] = proposed_trade.get("take_profits")
        signal["risk_per_unit"] = proposed_trade.get("risk_per_unit")
    else:
        signal.setdefault("entry_order_type", None)
        signal.setdefault("entry_price", None)
        signal.setdefault("stop_loss", None)
        signal.setdefault("take_profits", None)
        signal.setdefault("risk_per_unit", None)

    signal["strategy_reason_tags"] = signal.get("reason_tags", [])
    signal["orchestration_version"] = ANALYZER_ORCHESTRATION_VERSION

    return signal


def _base_validation(direction: str, strategy_type: str, reason: str) -> dict[str, Any]:
    return {
        "valid": False,
        "direction": direction,
        "strategy_type": strategy_type,
        "reason": reason,
        "failed_conditions": [reason],
        "passed_conditions": [],
        "details": {},
    }


def _base_score(symbol: str, direction: str, strategy_type: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "symbol": symbol,
        "direction": direction,
        "strategy_type": strategy_type,
        "score": 0.0,
        "max_score": 100,
        "breakdown": {},
        "reason_tags": [reason],
        "details": {},
    }


def _direction_candidates_for_route(route: dict[str, Any]) -> list[str]:
    selected_strategy = route.get("selected_strategy")
    direction_hint = route.get("direction_hint")

    if selected_strategy == "trend_following":
        if direction_hint in ("long", "short"):
            return [direction_hint]
        return []

    if selected_strategy == "mean_reversion":
        # In Sideways regimes v1 can take either edge of the local range.
        # Evaluate both sides and choose the best route after validation/scoring.
        return ["long", "short"]

    return []


def _rank_candidate(candidate: dict[str, Any]) -> tuple[int, float]:
    validation = candidate.get("entry_validation", {})
    score_result = candidate.get("score_result", {})
    valid_rank = 1 if validation.get("valid") else 0
    score = float(score_result.get("score", 0.0) or 0.0)
    return valid_rank, score


def _build_direction_candidate(
    *,
    snapshot: dict[str, Any],
    symbol: str,
    route: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    selected_strategy = route.get("selected_strategy", "none")
    regime = route.get("regime", "unknown")

    entry_validation = check_v1_entry(snapshot, selected_strategy, direction)
    score_result = score_v1_signal(snapshot, direction, selected_strategy, symbol)

    proposed_trade = None
    if entry_validation.get("valid"):
        proposal = build_proposed_trade(
            snapshot,
            symbol=symbol,
            direction=direction,
            selected_strategy=selected_strategy,
            regime=regime,
            score=score_result.get("score"),
            entry_order_type="limit",
        )
        if proposal.get("valid"):
            proposed_trade = proposal

    return {
        "direction": direction,
        "entry_validation": entry_validation,
        "score_result": score_result,
        "proposed_trade": proposed_trade,
    }


def _choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(candidates, key=_rank_candidate, reverse=True)[0]


def analyze_symbol(
    symbol: str,
    *,
    account_context: dict[str, Any] | None = None,
    candidate_filter_context: dict[str, Any] | None = None,
):
    symbol = _normalize_symbol(symbol)

    snapshot_payload, error = fetch_snapshot(symbol)
    if error:
        signal = build_no_trade_signal(
            symbol=symbol,
            reason="SNAPSHOT_FETCH_FAILED",
            reason_tags=["SNAPSHOT_FETCH_FAILED", str(error)],
            snapshot_refs={"orchestration_version": ANALYZER_ORCHESTRATION_VERSION},
        )
        signal["ok"] = False
        signal["error"] = error
        return _legacy_entry_fields(signal)

    snapshot_refs = build_snapshot_refs(snapshot_payload)
    snapshot_refs["orchestration_version"] = ANALYZER_ORCHESTRATION_VERSION

    valid_snapshot, snapshot_reasons = validate_snapshot_for_strategy(snapshot_payload)
    if not valid_snapshot:
        route = {
            "valid": False,
            "regime": "unknown",
            "regime_strategy": "unknown",
            "selected_strategy": "none",
            "direction_hint": "neutral",
            "reason_tags": ["SNAPSHOT_NOT_READY_FOR_STRATEGY"] + snapshot_reasons,
        }
        entry_validation = _base_validation(
            "neutral",
            "none",
            "SNAPSHOT_NOT_READY_FOR_STRATEGY",
        )
        score_result = _base_score(
            symbol,
            "neutral",
            "none",
            "SNAPSHOT_NOT_READY_FOR_STRATEGY",
        )

        signal = decide_strategy_signal(
            symbol=symbol,
            regime_route=route,
            entry_validation=entry_validation,
            score_result=score_result,
            account_context=account_context,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
            proposed_trade=None,
        )
        return _legacy_entry_fields(signal)

    route = route_regime(snapshot_payload)
    direction_candidates = _direction_candidates_for_route(route)

    if not direction_candidates:
        entry_validation = _base_validation(
            "neutral",
            route.get("selected_strategy", "none"),
            "NO_DIRECTION_CANDIDATE",
        )
        score_result = _base_score(
            symbol,
            "neutral",
            route.get("selected_strategy", "none"),
            "NO_DIRECTION_CANDIDATE",
        )
        signal = decide_strategy_signal(
            symbol=symbol,
            regime_route=route,
            entry_validation=entry_validation,
            score_result=score_result,
            account_context=account_context,
            snapshot_refs=snapshot_refs,
            candidate_filter_context=candidate_filter_context,
            proposed_trade=None,
        )
        return _legacy_entry_fields(signal)

    evaluated_candidates = [
        _build_direction_candidate(
            snapshot=snapshot_payload,
            symbol=symbol,
            route=route,
            direction=direction,
        )
        for direction in direction_candidates
    ]

    best = _choose_best_candidate(evaluated_candidates)
    if best is None:
        entry_validation = _base_validation(
            "neutral",
            route.get("selected_strategy", "none"),
            "NO_EVALUATED_CANDIDATE",
        )
        score_result = _base_score(
            symbol,
            "neutral",
            route.get("selected_strategy", "none"),
            "NO_EVALUATED_CANDIDATE",
        )
        proposed_trade = None
    else:
        entry_validation = best["entry_validation"]
        score_result = best["score_result"]
        proposed_trade = best["proposed_trade"]

    signal = decide_strategy_signal(
        symbol=symbol,
        regime_route=route,
        entry_validation=entry_validation,
        score_result=score_result,
        account_context=account_context,
        snapshot_refs=snapshot_refs,
        candidate_filter_context=candidate_filter_context,
        proposed_trade=proposed_trade,
    )

    signal["direction_evaluation"] = {
        "evaluated_directions": [
            {
                "direction": item.get("direction"),
                "entry_valid": item.get("entry_validation", {}).get("valid"),
                "entry_reason": item.get("entry_validation", {}).get("reason"),
                "score": item.get("score_result", {}).get("score"),
                "proposed_trade_valid": bool(item.get("proposed_trade")),
            }
            for item in evaluated_candidates
        ],
        "selected_direction": entry_validation.get("direction"),
    }

    # Helpful top-level score diagnostics for existing evaluator/dashboard consumers.
    signal["strategy_scores"] = {
        route.get("selected_strategy", "none"): round(float(score_result.get("score", 0.0) or 0.0), 2),
    }

    signal["score_breakdown"] = score_result.get("breakdown", {})
    signal["score_details"] = score_result.get("details", {})

    # Restore v2 decision after decision_policy, then compatibility remaps it.
    signal = _legacy_entry_fields(signal)

    return signal


def build_analyzer_orchestration_contract() -> dict[str, Any]:
    return {
        "orchestration_version": ANALYZER_ORCHESTRATION_VERSION,
        "runtime_pipeline": [
            "fetch_snapshot",
            "validate_snapshot_for_strategy",
            "route_regime",
            "check_v1_entry",
            "score_v1_signal",
            "build_proposed_trade",
            "decide_strategy_signal",
        ],
        "output_schema": "strategy_signal_v2",
        "legacy_compatibility": {
            "decision": "mapped to legacy_decision for current Scheduler",
            "v2_decision": "preserves no_trade/observe/trade_candidate",
            "trade_candidate_legacy_value": "trade",
        },
        "uses_old_regime_py": False,
        "uses_old_macro_py": False,
        "uses_old_strategies_py": False,
        "uses_old_proposals_py": False,
    }
