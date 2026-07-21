
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata, risk_quantity, smart_round


class VolatilityBreakoutV1Strategy:
    metadata = StrategyMetadata(
        name="volatility_breakout_v1",
        version="0.1.0",
        family="experimental",
        description="Experimental volatility breakout stub. Not production-ready.",
        required_timeframes=["15m"],
        required_indicators=["close_history", "rolling_range"],
        tags=["phase15d", "experimental", "volatility_breakout"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.breakout_window = int(self.config.get("breakout_window", 20))
        self.breakout_buffer_pct = float(self.config.get("breakout_buffer_pct", 0.0015))
        self.trade_threshold = float(self.config.get("strategy_trade_threshold", 65.0))

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        symbol = str(symbol).upper()
        history = snapshot.close_history.get(symbol, [])
        if len(history) < self.breakout_window + 1:
            return StrategyDecision(symbol, "skip", None, None, None, "unknown", "neutral", "volatility_breakout", "WARMUP_NOT_READY", ["WARMUP"], {"history_bars": len(history), "required_bars": self.breakout_window + 1})

        latest = history[-1]
        previous = history[-self.breakout_window - 1:-1]
        high = max(previous)
        low = min(previous)

        side = None
        if latest > high * (1 + self.breakout_buffer_pct):
            side = "long"
        elif latest < low * (1 - self.breakout_buffer_pct):
            side = "short"

        if side is None:
            return StrategyDecision(symbol, "skip", None, 0.0, 0.0, "BreakoutWatch", "neutral", "volatility_breakout", "NO_BREAKOUT", ["NO_BREAKOUT"], {"rolling_high": high, "rolling_low": low, "latest": latest})

        breakout_strength = abs(latest - (high if side == "long" else low)) / latest
        score = min(90.0, 55.0 + breakout_strength * 10000.0)
        confidence = min(0.90, score / 100.0)

        if score < self.trade_threshold:
            return StrategyDecision(symbol, "skip", side, round(score, 2), round(confidence, 4), "Breakout", "bullish" if side == "long" else "bearish", "volatility_breakout", "SCORE_BELOW_TRADE_THRESHOLD", ["BREAKOUT", "SCORE_BELOW_TRADE_THRESHOLD"], {"rolling_high": high, "rolling_low": low, "latest": latest, "breakout_strength": breakout_strength})

        return StrategyDecision(symbol, "enter", side, round(score, 2), round(confidence, 4), "Breakout", "bullish" if side == "long" else "bearish", "volatility_breakout", "TRADE_CANDIDATE", ["BREAKOUT", "EXPERIMENTAL", "TRADE_CANDIDATE"], {"rolling_high": high, "rolling_low": low, "latest": latest, "breakout_strength": breakout_strength})

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        if decision.action != "enter" or decision.side not in {"long", "short"}:
            return None

        entry = snapshot.closes[decision.symbol]
        stop_distance_pct = float(self.config.get("stop_distance_pct", 0.018))
        stop = entry * (1.0 - stop_distance_pct if decision.side == "long" else 1.0 + stop_distance_pct)
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)
        if qty <= 0:
            return None

        risk = abs(entry - stop)
        if decision.side == "long":
            tp1, tp2, tp3 = entry + risk * 1.3, entry + risk * 2.2, entry + risk * 3.2
        else:
            tp1, tp2, tp3 = entry - risk * 1.3, entry - risk * 2.2, entry - risk * 3.2

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
