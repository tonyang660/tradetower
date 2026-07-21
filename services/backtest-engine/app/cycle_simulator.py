from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from market_snapshot import MarketSnapshot


@dataclass(frozen=True)
class CycleDecision:
    symbol: str
    action: str
    side: str | None
    score: float | None
    confidence: float | None
    reason: str
    reason_tags: list[str]
    debug: dict[str, Any]


class Phase14BaselineDecisionEngine:
    """Temporary placeholder until Phase 15 strategy registry exists."""

    name = "phase14a_baseline"
    version = "0.1.0"
    warmup_required_bars = 8

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str) -> CycleDecision:
        if not snapshot.warmup_ready.get(symbol, False):
            return CycleDecision(
                symbol=symbol,
                action="skip",
                side=None,
                score=None,
                confidence=None,
                reason="WARMUP_NOT_READY",
                reason_tags=["WARMUP"],
                debug={
                    "history_bars": len(snapshot.close_history.get(symbol, [])),
                    "required_bars": snapshot.warmup_required_bars,
                },
            )

        history = snapshot.close_history[symbol]
        m3 = (history[-1] - history[-4]) / history[-4]
        m7 = (history[-1] - history[-8]) / history[-8]

        if m3 > 0.003 and m7 > 0.001:
            return CycleDecision(symbol, "enter", "long", 70.0, 0.70, "MOMENTUM_LONG",
                                 ["PHASE14A_BASELINE", "EVENT_DRIVEN_TEST", "MOMENTUM_LONG"],
                                 {"m3": m3, "m7": m7})

        if m3 < -0.003 and m7 < -0.001:
            return CycleDecision(symbol, "enter", "short", 70.0, 0.70, "MOMENTUM_SHORT",
                                 ["PHASE14A_BASELINE", "EVENT_DRIVEN_TEST", "MOMENTUM_SHORT"],
                                 {"m3": m3, "m7": m7})

        return CycleDecision(symbol, "skip", None, None, None, "NO_SIGNAL", ["NO_SIGNAL"], {"m3": m3, "m7": m7})


def build_entry_plan(snapshot: MarketSnapshot, decision: CycleDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
    if decision.action != "enter" or decision.side not in {"long", "short"}:
        return None

    symbol = decision.symbol
    if symbol not in snapshot.closes:
        return None

    entry = snapshot.closes[symbol]
    side = decision.side
    stop = entry * (0.985 if side == "long" else 1.015)
    risk = equity * risk_per_trade_pct / 100.0
    qty = risk / abs(entry - stop) if abs(entry - stop) > 0 else 0.0
    if qty <= 0:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp1": entry * (1.012 if side == "long" else 0.988),
        "tp2": entry * (1.020 if side == "long" else 0.980),
        "tp3": entry * (1.032 if side == "long" else 0.968),
        "qty": qty,
        "regime": "sample_trend" if side == "long" else "sample_downtrend",
        "score": decision.score or 0.0,
        "confidence": decision.confidence or 0.0,
        "reason_tags": decision.reason_tags,
        "debug": {
            **decision.debug,
            "cycle_index": snapshot.cycle_index,
            "timestamp": snapshot.timestamp.isoformat(),
            "lookahead_guard": snapshot.lookahead_guard,
        },
    }
