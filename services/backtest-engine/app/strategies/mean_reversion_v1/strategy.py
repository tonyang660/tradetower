
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata, risk_quantity, smart_round


class MeanReversionV1Strategy:
    metadata = StrategyMetadata(
        name="mean_reversion_v1",
        version="0.1.0",
        family="mean_reversion",
        description="Standalone mean-reversion strategy stub for Phase 15D experiments.",
        required_timeframes=["15m"],
        required_indicators=["close_history", "range_deviation"],
        tags=["phase15d", "stub", "mean_reversion"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.deviation_threshold = float(self.config.get("mean_reversion_deviation_threshold", 0.006))
        self.trade_threshold = float(self.config.get("strategy_trade_threshold", 65.0))

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        symbol = str(symbol).upper()
        history = snapshot.close_history.get(symbol, [])

        if not snapshot.warmup_ready.get(symbol, False) or len(history) < 20:
            return StrategyDecision(symbol, "skip", None, None, None, "unknown", "neutral", "mean_reversion", "WARMUP_NOT_READY", ["WARMUP"], {"history_bars": len(history), "required_bars": 20})

        latest = history[-1]
        window = history[-20:]
        mean = sum(window) / len(window)
        deviation = (latest - mean) / mean if mean else 0.0

        side = None
        if deviation <= -self.deviation_threshold:
            side = "long"
        elif deviation >= self.deviation_threshold:
            side = "short"

        if side is None:
            return StrategyDecision(symbol, "skip", None, 0.0, 0.0, "Sideways", "neutral", "mean_reversion", "NO_MEAN_REVERSION_EXTREMITY", ["NO_MEAN_REVERSION_EXTREMITY"], {"mean": mean, "deviation": deviation})

        score = min(90.0, 50.0 + abs(deviation) * 5000.0)
        confidence = min(0.90, score / 100.0)

        if score < self.trade_threshold:
            return StrategyDecision(symbol, "skip", side, round(score, 2), round(confidence, 4), "Sideways", "neutral", "mean_reversion", "SCORE_BELOW_TRADE_THRESHOLD", ["MEAN_REVERSION_EXTREMITY", "SCORE_BELOW_TRADE_THRESHOLD"], {"mean": mean, "deviation": deviation, "threshold": self.trade_threshold})

        return StrategyDecision(symbol, "enter", side, round(score, 2), round(confidence, 4), "Sideways", "neutral", "mean_reversion", "TRADE_CANDIDATE", ["MEAN_REVERSION_EXTREMITY", "TRADE_CANDIDATE"], {"mean": mean, "deviation": deviation, "threshold": self.trade_threshold})

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        if decision.action != "enter" or decision.side not in {"long", "short"}:
            return None

        entry = snapshot.closes[decision.symbol]
        stop_distance_pct = float(self.config.get("stop_distance_pct", 0.012))
        stop = entry * (1.0 - stop_distance_pct if decision.side == "long" else 1.0 + stop_distance_pct)
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)
        if qty <= 0:
            return None

        risk = abs(entry - stop)
        if decision.side == "long":
            tp1, tp2, tp3 = entry + risk * 1.2, entry + risk * 1.8, entry + risk * 2.4
        else:
            tp1, tp2, tp3 = entry - risk * 1.2, entry - risk * 1.8, entry - risk * 2.4

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
