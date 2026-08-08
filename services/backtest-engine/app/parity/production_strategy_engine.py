from __future__ import annotations

from typing import Any

from production_runtime import load_production_module


BACKTEST_STRATEGY_ADAPTER_VERSION = "backtest_production_strategy_engine_adapter_v1"


def analyze_market_snapshot_v2(
    symbol: str,
    snapshot: dict[str, Any],
    *,
    account_context: dict[str, Any] | None = None,
    candidate_filter_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = load_production_module("strategy_engine", "snapshot_v1_adapter")
    router = load_production_module("strategy_engine", "regime_router")
    entry_logic = load_production_module("strategy_engine", "v1_entry_logic")
    scorer = load_production_module("strategy_engine", "v1_signal_scorer")
    trade_levels = load_production_module("strategy_engine", "v1_trade_levels")
    decisions = load_production_module("strategy_engine", "v1_decision_policy")
    symbol = str(symbol).upper().replace("-", "")
    refs = adapter.build_snapshot_refs(snapshot)
    refs["orchestration_version"] = "phase4_step10_v1_analyzer_orchestration"

    valid, reasons = adapter.validate_snapshot_for_strategy(snapshot)
    if not valid:
        route = {"valid": False, "regime": "unknown", "regime_strategy": "unknown", "selected_strategy": "none", "direction_hint": "neutral", "reason_tags": ["SNAPSHOT_NOT_READY_FOR_STRATEGY", *reasons]}
        validation = {"valid": False, "direction": "neutral", "strategy_type": "none", "reason": "SNAPSHOT_NOT_READY_FOR_STRATEGY", "failed_conditions": reasons, "passed_conditions": [], "details": {}}
        score = {"ok": False, "score": 0.0, "breakdown": {}, "reason_tags": ["SNAPSHOT_NOT_READY_FOR_STRATEGY"]}
        result = decisions.decide_strategy_signal(symbol=symbol, regime_route=route, entry_validation=validation, score_result=score, account_context=account_context or {}, snapshot_refs=refs, candidate_filter_context=candidate_filter_context, proposed_trade=None)
    else:
        route = router.route_regime(snapshot)
        if route.get("selected_strategy") == "trend_following":
            directions = [route.get("direction_hint")] if route.get("direction_hint") in ("long", "short") else []
        elif route.get("selected_strategy") == "mean_reversion":
            directions = ["long", "short"]
        else:
            directions = []
        evaluated = []
        for direction in directions:
            validation = entry_logic.check_v1_entry(snapshot, route.get("selected_strategy"), direction)
            score = scorer.score_v1_signal(snapshot, direction, route.get("selected_strategy"), symbol)
            proposal = None
            if validation.get("valid"):
                candidate = trade_levels.build_proposed_trade(snapshot, symbol=symbol, direction=direction, selected_strategy=route.get("selected_strategy"), regime=route.get("regime"), score=score.get("score"), entry_order_type="limit")
                if candidate.get("valid"):
                    proposal = candidate
            evaluated.append({"direction": direction, "entry_validation": validation, "score_result": score, "proposed_trade": proposal})
        best = sorted(evaluated, key=lambda item: (1 if item["entry_validation"].get("valid") else 0, float(item["score_result"].get("score", 0.0) or 0.0)), reverse=True)[0] if evaluated else None
        if best:
            validation, score, proposal = best["entry_validation"], best["score_result"], best["proposed_trade"]
        else:
            validation = {"valid": False, "direction": "neutral", "strategy_type": route.get("selected_strategy", "none"), "reason": "NO_DIRECTION_CANDIDATE", "failed_conditions": ["NO_DIRECTION_CANDIDATE"], "passed_conditions": [], "details": {}}
            score = {"ok": False, "score": 0.0, "breakdown": {}, "reason_tags": ["NO_DIRECTION_CANDIDATE"]}
            proposal = None
        result = decisions.decide_strategy_signal(symbol=symbol, regime_route=route, entry_validation=validation, score_result=score, account_context=account_context or {}, snapshot_refs=refs, candidate_filter_context=candidate_filter_context, proposed_trade=proposal)
        result["direction_evaluation"] = [{"direction": item["direction"], "entry_valid": item["entry_validation"].get("valid"), "entry_reason": item["entry_validation"].get("reason"), "score": item["score_result"].get("score"), "proposed_trade_valid": bool(item.get("proposed_trade"))} for item in evaluated]

    result["v2_decision"] = result.get("decision")
    result["legacy_decision"] = result.get("legacy_decision")
    result["backtest_adapter_version"] = BACKTEST_STRATEGY_ADAPTER_VERSION
    result["production_analyzer_version"] = "phase4_step10_v1_analyzer_orchestration"
    return result
