
from __future__ import annotations

from typing import Any

from market_snapshot import MarketSnapshot
from strategies.base import StrategyContext, StrategyDecision, StrategyMetadata, risk_quantity, smart_round


class TradeTowerBaselineV1Strategy:
    """Backtest baseline inspired by the current production Strategy Engine.

    It mirrors the production orchestration shape:
      regime route -> direction candidate -> entry validation -> score -> levels

    It is intentionally not a byte-for-byte production port yet because Phase 14
    snapshots do not expose Feature Factory's full indicator payload.
    """

    metadata = StrategyMetadata(
        name="tradetower_baseline_v1",
        version="0.1.0",
        family="regime_adaptive",
        description="Baseline strategy shaped after production strategy-engine v1 pipeline.",
        required_timeframes=["15m"],
        required_indicators=["close_history", "momentum_3", "momentum_7", "range_deviation"],
        tags=["baseline", "phase15", "regime_adaptive", "v1_shape"],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.normal_threshold = float(self.config.get("strategy_trade_threshold", 75.0))
        self.btc_threshold = float(self.config.get("strategy_btc_trade_threshold", 80.0))
        self.observe_threshold = float(self.config.get("strategy_observe_threshold", 50.0))

    def _threshold_for_symbol(self, symbol: str) -> tuple[float, list[str]]:
        if symbol.upper().startswith("BTC"):
            return self.btc_threshold, ["THRESHOLD_BTC"]
        return self.normal_threshold, ["THRESHOLD_NORMAL"]

    def _route_regime(self, history: list[float]) -> dict[str, Any]:
        m3 = (history[-1] - history[-4]) / history[-4]
        m7 = (history[-1] - history[-8]) / history[-8]

        if m3 > 0.003 and m7 > 0.001:
            return {
                "valid": True,
                "regime": "Uptrend",
                "selected_strategy": "trend_following",
                "direction_hint": "long",
                "macro_bias": "bullish",
                "reason_tags": ["REGIME_UPTREND", "ROUTE_TREND_FOLLOWING"],
                "debug": {"m3": m3, "m7": m7},
            }

        if m3 < -0.003 and m7 < -0.001:
            return {
                "valid": True,
                "regime": "Downtrend",
                "selected_strategy": "trend_following",
                "direction_hint": "short",
                "macro_bias": "bearish",
                "reason_tags": ["REGIME_DOWNTREND", "ROUTE_TREND_FOLLOWING"],
                "debug": {"m3": m3, "m7": m7},
            }

        return {
            "valid": True,
            "regime": "Sideways",
            "selected_strategy": "mean_reversion",
            "direction_hint": "neutral",
            "macro_bias": "neutral",
            "reason_tags": ["REGIME_SIDEWAYS", "ROUTE_MEAN_REVERSION"],
            "debug": {"m3": m3, "m7": m7},
        }

    def _evaluate_trend_candidate(self, symbol: str, route: dict[str, Any]) -> StrategyDecision:
        side = route["direction_hint"]
        m3 = route["debug"]["m3"]
        m7 = route["debug"]["m7"]
        threshold, threshold_tags = self._threshold_for_symbol(symbol)

        momentum_strength = abs(m3) * 6000.0 + abs(m7) * 2500.0
        score = max(0.0, min(95.0, 52.0 + momentum_strength))
        confidence = max(0.0, min(0.95, score / 100.0))

        reason_tags = [
            *route["reason_tags"],
            *threshold_tags,
            "TREND_DIRECTION_CANDIDATE",
            "MOMENTUM_VALIDATION",
        ]

        if score < threshold:
            return StrategyDecision(
                symbol=symbol,
                action="skip",
                side=side,
                score=round(score, 2),
                confidence=round(confidence, 4),
                regime=route["regime"],
                macro_bias=route["macro_bias"],
                selected_strategy=route["selected_strategy"],
                reason="SCORE_BELOW_TRADE_THRESHOLD",
                reason_tags=reason_tags + ["SCORE_BELOW_TRADE_THRESHOLD"],
                debug={**route["debug"], "threshold": threshold, "strategy_shape": "production_v1_regime_route_entry_score_levels"},
            )

        return StrategyDecision(
            symbol=symbol,
            action="enter",
            side=side,
            score=round(score, 2),
            confidence=round(confidence, 4),
            regime=route["regime"],
            macro_bias=route["macro_bias"],
            selected_strategy=route["selected_strategy"],
            reason="TRADE_CANDIDATE",
            reason_tags=reason_tags + ["TRADE_CANDIDATE"],
            debug={**route["debug"], "threshold": threshold, "strategy_shape": "production_v1_regime_route_entry_score_levels"},
        )

    def _evaluate_mean_reversion_candidate(self, symbol: str, history: list[float], route: dict[str, Any]) -> StrategyDecision:
        latest = history[-1]
        window = history[-20:] if len(history) >= 20 else history
        mean = sum(window) / len(window)
        deviation = (latest - mean) / mean if mean else 0.0
        side = "short" if deviation > 0.006 else "long" if deviation < -0.006 else None
        threshold, threshold_tags = self._threshold_for_symbol(symbol)

        if side is None:
            return StrategyDecision(
                symbol=symbol,
                action="skip",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=route["regime"],
                macro_bias=route["macro_bias"],
                selected_strategy=route["selected_strategy"],
                reason="NO_MEAN_REVERSION_EXTREMITY",
                reason_tags=route["reason_tags"] + ["NO_MEAN_REVERSION_EXTREMITY"],
                debug={**route["debug"], "mean": mean, "deviation": deviation},
            )

        score = max(0.0, min(90.0, 50.0 + abs(deviation) * 5000.0))
        confidence = max(0.0, min(0.90, score / 100.0))

        if symbol.upper().startswith("BTC"):
            return StrategyDecision(
                symbol=symbol,
                action="skip",
                side=side,
                score=round(score, 2),
                confidence=round(confidence, 4),
                regime=route["regime"],
                macro_bias=route["macro_bias"],
                selected_strategy=route["selected_strategy"],
                reason="BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME",
                reason_tags=route["reason_tags"] + threshold_tags + ["BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME"],
                debug={**route["debug"], "mean": mean, "deviation": deviation, "threshold": threshold},
            )

        if score < threshold:
            return StrategyDecision(
                symbol=symbol,
                action="skip",
                side=side,
                score=round(score, 2),
                confidence=round(confidence, 4),
                regime=route["regime"],
                macro_bias=route["macro_bias"],
                selected_strategy=route["selected_strategy"],
                reason="SCORE_BELOW_TRADE_THRESHOLD",
                reason_tags=route["reason_tags"] + threshold_tags + ["SCORE_BELOW_TRADE_THRESHOLD"],
                debug={**route["debug"], "mean": mean, "deviation": deviation, "threshold": threshold},
            )

        return StrategyDecision(
            symbol=symbol,
            action="enter",
            side=side,
            score=round(score, 2),
            confidence=round(confidence, 4),
            regime=route["regime"],
            macro_bias=route["macro_bias"],
            selected_strategy=route["selected_strategy"],
            reason="TRADE_CANDIDATE",
            reason_tags=route["reason_tags"] + threshold_tags + ["MEAN_REVERSION_EXTREMITY", "TRADE_CANDIDATE"],
            debug={**route["debug"], "mean": mean, "deviation": deviation, "threshold": threshold},
        )

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        symbol = str(symbol).upper()
        history = snapshot.close_history.get(symbol, [])

        if not snapshot.warmup_ready.get(symbol, False) or len(history) < 8:
            return StrategyDecision(
                symbol=symbol,
                action="skip",
                side=None,
                score=None,
                confidence=None,
                regime="unknown",
                macro_bias="neutral",
                selected_strategy="none",
                reason="WARMUP_NOT_READY",
                reason_tags=["WARMUP"],
                debug={"history_bars": len(history), "required_bars": snapshot.warmup_required_bars},
            )

        route = self._route_regime(history)

        if route["selected_strategy"] == "trend_following":
            return self._evaluate_trend_candidate(symbol, route)

        if route["selected_strategy"] == "mean_reversion":
            return self._evaluate_mean_reversion_candidate(symbol, history, route)

        return StrategyDecision(
            symbol=symbol,
            action="skip",
            side=None,
            score=0.0,
            confidence=0.0,
            regime=route["regime"],
            macro_bias=route["macro_bias"],
            selected_strategy="none",
            reason="NO_VALID_STRATEGY_ROUTE",
            reason_tags=route["reason_tags"] + ["NO_VALID_STRATEGY_ROUTE"],
            debug=route["debug"],
        )

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        if decision.action != "enter" or decision.side not in {"long", "short"}:
            return None

        symbol = decision.symbol
        if symbol not in snapshot.closes:
            return None

        entry = snapshot.closes[symbol]
        side = decision.side
        stop = entry * (0.985 if side == "long" else 1.015)
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)

        if qty <= 0:
            return None

        risk = abs(entry - stop)

        if side == "long":
            tp1 = entry + risk * 1.5
            tp2 = entry + risk * 2.5
            tp3 = entry + risk * 3.5
        else:
            tp1 = entry - risk * 1.5
            tp2 = entry - risk * 2.5
            tp3 = entry - risk * 3.5

        return {
            "symbol": symbol,
            "side": side,
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
                "lookahead_guard": snapshot.lookahead_guard,
                "target_policy": {
                    "tp1_r": 1.5,
                    "tp2_r": 2.5,
                    "tp3_r": 3.5,
                    "tp1_close_percent": 50,
                    "tp2_close_percent": 30,
                    "tp3_close_percent": 20,
                },
            },
        }
