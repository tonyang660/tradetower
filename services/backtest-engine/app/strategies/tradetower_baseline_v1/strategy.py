
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata, risk_quantity, smart_round
from strategies.tradetower_baseline_v1.parity_adapter import analyze_snapshot_symbol


class TradeTowerBaselineV1Strategy:
    metadata = StrategyMetadata(
        name="tradetower_baseline_v1",
        version="0.1.1",
        family="regime_adaptive",
        description="Baseline strategy using Phase 15C Strategy Engine parity adapter shape.",
        required_timeframes=["5m", "15m", "4h"],
        required_indicators=[
            "snapshot_refs",
            "regime_route",
            "entry_validation",
            "score_breakdown",
            "proposed_trade",
        ],
        tags=["baseline", "phase15c", "strategy_engine_parity_adapter", "regime_adaptive"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def evaluate_symbol(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
        context: StrategyContext | None = None,
    ) -> StrategyDecision:
        candidate_filter_context = context.candidate_filter_context if context else None
        signal = analyze_snapshot_symbol(
            snapshot,
            symbol,
            self.config,
            candidate_filter_context=candidate_filter_context,
        )

        side = signal.get("decision_side")
        action = "enter" if signal.get("decision") == "trade_candidate" and side in {"long", "short"} else "skip"

        return StrategyDecision(
            symbol=symbol,
            action=action,
            side=side,
            score=signal.get("score"),
            confidence=signal.get("confidence"),
            regime=signal.get("regime", "unknown"),
            macro_bias=signal.get("macro_bias", "neutral"),
            selected_strategy=signal.get("selected_strategy", "none"),
            reason=signal.get("reason", "UNKNOWN"),
            reason_tags=signal.get("reason_tags", []),
            debug={
                "strategy_signal": signal,
                "parity_adapter_version": signal.get("parity_adapter_version"),
                "score_breakdown": signal.get("score_breakdown"),
                "direction_evaluation": signal.get("direction_evaluation"),
                "entry_validation": signal.get("entry_validation"),
            },
        )

    def build_entry_plan(
        self,
        snapshot: MarketSnapshot,
        decision: StrategyDecision,
        equity: float,
        risk_per_trade_pct: float,
    ) -> dict[str, Any] | None:
        if decision.action != "enter" or decision.side not in {"long", "short"}:
            return None

        signal = decision.debug.get("strategy_signal", {})
        proposed_trade = signal.get("proposed_trade") or {}

        if not proposed_trade.get("valid"):
            return None

        entry = float(proposed_trade["entry_price"])
        stop = float(proposed_trade["stop_loss"])
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)
        if qty <= 0:
            return None

        take_profits = proposed_trade.get("take_profits") or []
        tp1 = float(take_profits[0]["price"]) if len(take_profits) > 0 else entry
        tp2 = float(take_profits[1]["price"]) if len(take_profits) > 1 else tp1
        tp3 = float(take_profits[2]["price"]) if len(take_profits) > 2 else tp2

        return {
            "symbol": decision.symbol,
            "side": decision.side,
            "entry": smart_round(entry),
            "stop": smart_round(stop),
            "tp1": smart_round(tp1),
            "tp2": smart_round(tp2),
            "tp3": smart_round(tp3),
            "qty": qty,
            "regime": decision.regime,
            "score": decision.score or 0.0,
            "confidence": decision.confidence or 0.0,
            "reason_tags": decision.reason_tags,
            "debug": {
                **decision.debug,
                "cycle_index": snapshot.cycle_index,
                "timestamp": snapshot.timestamp.isoformat(),
                "selected_strategy": decision.selected_strategy,
                "macro_bias": decision.macro_bias,
                "entry_order_type": proposed_trade.get("entry_order_type", "limit"),
                "proposed_trade": proposed_trade,
                "lookahead_guard": snapshot.lookahead_guard,
            },
        }
