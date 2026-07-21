
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata
from strategies.mean_reversion_v1.strategy import MeanReversionV1Strategy
from strategies.trend_following_v1.strategy import TrendFollowingV1Strategy


class RegimeAdaptiveV1Strategy:
    metadata = StrategyMetadata(
        name="regime_adaptive_v1",
        version="0.1.0",
        family="regime_adaptive",
        description="Standalone regime-adaptive strategy stub that routes between trend and mean-reversion modules.",
        required_timeframes=["15m"],
        required_indicators=["close_history", "momentum_3", "momentum_7", "range_deviation"],
        tags=["phase15d", "stub", "regime_adaptive"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.trend = TrendFollowingV1Strategy(self.config)
        self.mean_reversion = MeanReversionV1Strategy(self.config)
        self.m3_threshold = float(self.config.get("trend_momentum_3_threshold", 0.003))
        self.m7_threshold = float(self.config.get("trend_momentum_7_threshold", 0.001))

    def _route(self, snapshot: MarketSnapshot, symbol: str) -> str:
        history = snapshot.close_history.get(symbol, [])
        if len(history) < 8:
            return "warmup"
        m3 = (history[-1] - history[-4]) / history[-4]
        m7 = (history[-1] - history[-8]) / history[-8]
        if (m3 > self.m3_threshold and m7 > self.m7_threshold) or (m3 < -self.m3_threshold and m7 < -self.m7_threshold):
            return "trend_following"
        return "mean_reversion"

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        route = self._route(snapshot, str(symbol).upper())

        if route == "trend_following":
            decision = self.trend.evaluate_symbol(snapshot, symbol, context)
        elif route == "mean_reversion":
            decision = self.mean_reversion.evaluate_symbol(snapshot, symbol, context)
        else:
            return StrategyDecision(str(symbol).upper(), "skip", None, None, None, "unknown", "neutral", "regime_adaptive", "WARMUP_NOT_READY", ["WARMUP"], {"route": route})

        return StrategyDecision(
            symbol=decision.symbol,
            action=decision.action,
            side=decision.side,
            score=decision.score,
            confidence=decision.confidence,
            regime=decision.regime,
            macro_bias=decision.macro_bias,
            selected_strategy=route,
            reason=decision.reason,
            reason_tags=["REGIME_ADAPTIVE_ROUTE", f"ROUTE_{route.upper()}"] + decision.reason_tags,
            debug={**decision.debug, "regime_adaptive_route": route, "strategy_module": self.metadata.name},
        )

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        if decision.selected_strategy == "trend_following":
            return self.trend.build_entry_plan(snapshot, decision, equity, risk_per_trade_pct)
        if decision.selected_strategy == "mean_reversion":
            return self.mean_reversion.build_entry_plan(snapshot, decision, equity, risk_per_trade_pct)
        return None
