
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata, risk_quantity, smart_round


class TrendFollowingV1Strategy:
    metadata = StrategyMetadata(
        name="trend_following_v1",
        version="0.1.0",
        family="trend_following",
        description="Standalone trend-following strategy stub for Phase 15D experiments.",
        required_timeframes=["15m"],
        required_indicators=["close_history", "momentum_3", "momentum_7"],
        tags=["phase15d", "stub", "trend_following"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.m3_threshold = float(self.config.get("trend_momentum_3_threshold", 0.003))
        self.m7_threshold = float(self.config.get("trend_momentum_7_threshold", 0.001))
        self.trade_threshold = float(self.config.get("strategy_trade_threshold", 65.0))

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        symbol = str(symbol).upper()
        history = snapshot.close_history.get(symbol, [])

        if not snapshot.warmup_ready.get(symbol, False) or len(history) < 8:
            return StrategyDecision(symbol, "skip", None, None, None, "unknown", "neutral", "trend_following", "WARMUP_NOT_READY", ["WARMUP"], {"history_bars": len(history)})

        m3 = (history[-1] - history[-4]) / history[-4]
        m7 = (history[-1] - history[-8]) / history[-8]

        side = None
        if m3 > self.m3_threshold and m7 > self.m7_threshold:
            side = "long"
        elif m3 < -self.m3_threshold and m7 < -self.m7_threshold:
            side = "short"

        if side is None:
            return StrategyDecision(symbol, "skip", None, 0.0, 0.0, "Sideways", "neutral", "trend_following", "NO_TREND_SIGNAL", ["NO_TREND_SIGNAL"], {"m3": m3, "m7": m7})

        score = min(95.0, 55.0 + abs(m3) * 6000.0 + abs(m7) * 2500.0)
        confidence = min(0.95, score / 100.0)

        if score < self.trade_threshold:
            return StrategyDecision(symbol, "skip", side, round(score, 2), round(confidence, 4), "Trend", "bullish" if side == "long" else "bearish", "trend_following", "SCORE_BELOW_TRADE_THRESHOLD", ["TREND_SIGNAL", "SCORE_BELOW_TRADE_THRESHOLD"], {"m3": m3, "m7": m7, "threshold": self.trade_threshold})

        return StrategyDecision(symbol, "enter", side, round(score, 2), round(confidence, 4), "Trend", "bullish" if side == "long" else "bearish", "trend_following", "TRADE_CANDIDATE", ["TREND_SIGNAL", "TRADE_CANDIDATE"], {"m3": m3, "m7": m7, "threshold": self.trade_threshold})

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        if decision.action != "enter" or decision.side not in {"long", "short"}:
            return None

        entry = snapshot.closes[decision.symbol]
        stop_distance_pct = float(self.config.get("stop_distance_pct", 0.015))
        stop = entry * (1.0 - stop_distance_pct if decision.side == "long" else 1.0 + stop_distance_pct)
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)
        if qty <= 0:
            return None

        risk = abs(entry - stop)
        if decision.side == "long":
            tp1, tp2, tp3 = entry + risk * 1.5, entry + risk * 2.5, entry + risk * 3.5
        else:
            tp1, tp2, tp3 = entry - risk * 1.5, entry - risk * 2.5, entry - risk * 3.5

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
            "debug": {**decision.debug, "strategy_module": self.metadata.name, "cycle_index": snapshot.cycle_index, "timestamp": snapshot.timestamp.isoformat(), "lookahead_guard": snapshot.lookahead_guard},
        }
