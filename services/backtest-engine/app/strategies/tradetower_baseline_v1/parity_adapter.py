
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from market_snapshot import MarketSnapshot


PARITY_ADAPTER_VERSION = "phase15c_strategy_engine_parity_adapter"

ENTRY_TIMEFRAME = "5m"
PRIMARY_TIMEFRAME = "15m"
CONTEXT_TIMEFRAME = "1h"
HTF_TIMEFRAME = "4h"

ROLE_TO_TIMEFRAME = {
    "entry": ENTRY_TIMEFRAME,
    "primary": PRIMARY_TIMEFRAME,
    "context": CONTEXT_TIMEFRAME,
    "htf": HTF_TIMEFRAME,
}


@dataclass(frozen=True)
class ParityRoute:
    valid: bool
    regime: str
    selected_strategy: str
    direction_hint: str
    macro_bias: str
    reason_tags: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntryValidation:
    valid: bool
    direction: str
    strategy_type: str
    reason: str
    passed_conditions: list[str]
    failed_conditions: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreResult:
    ok: bool
    symbol: str
    direction: str
    strategy_type: str
    score: float
    max_score: float
    breakdown: dict[str, Any]
    reason_tags: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProposedTrade:
    valid: bool
    symbol: str
    direction: str
    selected_strategy: str
    regime: str
    entry_order_type: str
    entry_price: float
    stop_loss: float
    take_profits: list[dict[str, Any]]
    risk_per_unit: float
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot_refs(snapshot: MarketSnapshot) -> dict[str, Any]:
    return {
        "adapter_version": PARITY_ADAPTER_VERSION,
        "schema": "backtest_market_snapshot_v1_compat",
        "timestamp": snapshot.timestamp.isoformat(),
        "cycle_index": snapshot.cycle_index,
        "role_to_timeframe": ROLE_TO_TIMEFRAME,
        "available_symbols": snapshot.symbols,
        "warmup_ready": snapshot.warmup_ready,
        "lookahead_guard": snapshot.lookahead_guard,
    }


def validate_snapshot_for_strategy(snapshot: MarketSnapshot, symbol: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if symbol not in snapshot.closes:
        reasons.append("MISSING_SYMBOL_CLOSE")

    if not snapshot.warmup_ready.get(symbol, False):
        reasons.append("WARMUP_NOT_READY")

    if len(snapshot.close_history.get(symbol, [])) < snapshot.warmup_required_bars:
        reasons.append("INSUFFICIENT_HISTORY")

    return len(reasons) == 0, reasons


def momentum_features(snapshot: MarketSnapshot, symbol: str) -> dict[str, float]:
    history = snapshot.close_history.get(symbol, [])
    latest = history[-1] if history else 0.0
    m3 = (history[-1] - history[-4]) / history[-4] if len(history) >= 4 and history[-4] else 0.0
    m7 = (history[-1] - history[-8]) / history[-8] if len(history) >= 8 and history[-8] else 0.0
    window = history[-20:] if len(history) >= 20 else history
    mean = sum(window) / len(window) if window else latest
    deviation = (latest - mean) / mean if mean else 0.0
    return {
        "latest": latest,
        "momentum_3": m3,
        "momentum_7": m7,
        "range_mean": mean,
        "range_deviation": deviation,
    }


def route_regime(snapshot: MarketSnapshot, symbol: str, config: dict[str, Any]) -> ParityRoute:
    f = momentum_features(snapshot, symbol)
    m3_threshold = float(config.get("trend_momentum_3_threshold", 0.003))
    m7_threshold = float(config.get("trend_momentum_7_threshold", 0.001))

    if f["momentum_3"] > m3_threshold and f["momentum_7"] > m7_threshold:
        return ParityRoute(
            valid=True,
            regime="Uptrend",
            selected_strategy="trend_following",
            direction_hint="long",
            macro_bias="bullish",
            reason_tags=["REGIME_UPTREND", "ROUTE_TREND_FOLLOWING"],
            details=f,
        )

    if f["momentum_3"] < -m3_threshold and f["momentum_7"] < -m7_threshold:
        return ParityRoute(
            valid=True,
            regime="Downtrend",
            selected_strategy="trend_following",
            direction_hint="short",
            macro_bias="bearish",
            reason_tags=["REGIME_DOWNTREND", "ROUTE_TREND_FOLLOWING"],
            details=f,
        )

    return ParityRoute(
        valid=True,
        regime="Sideways",
        selected_strategy="mean_reversion",
        direction_hint="neutral",
        macro_bias="neutral",
        reason_tags=["REGIME_SIDEWAYS", "ROUTE_MEAN_REVERSION"],
        details=f,
    )


def direction_candidates_for_route(route: ParityRoute) -> list[str]:
    if route.selected_strategy == "trend_following":
        return [route.direction_hint] if route.direction_hint in {"long", "short"} else []

    if route.selected_strategy == "mean_reversion":
        return ["long", "short"]

    return []


def check_v1_entry(snapshot: MarketSnapshot, symbol: str, route: ParityRoute, direction: str, config: dict[str, Any]) -> EntryValidation:
    passed: list[str] = []
    failed: list[str] = []
    f = route.details

    if route.selected_strategy == "trend_following":
        if direction == "long" and f["momentum_3"] > 0 and f["momentum_7"] > 0:
            passed.append("TREND_MOMENTUM_ALIGNED_LONG")
        elif direction == "short" and f["momentum_3"] < 0 and f["momentum_7"] < 0:
            passed.append("TREND_MOMENTUM_ALIGNED_SHORT")
        else:
            failed.append("TREND_MOMENTUM_NOT_ALIGNED")

    elif route.selected_strategy == "mean_reversion":
        deviation_threshold = float(config.get("mean_reversion_deviation_threshold", 0.006))
        if direction == "long" and f["range_deviation"] <= -deviation_threshold:
            passed.append("LOW_RANGE_EXTREMITY")
        elif direction == "short" and f["range_deviation"] >= deviation_threshold:
            passed.append("HIGH_RANGE_EXTREMITY")
        else:
            failed.append("NO_MEAN_REVERSION_EXTREMITY")

        if symbol.upper().startswith("BTC"):
            failed.append("BTC_SKIP_CHOPPY_OR_MEAN_REVERSION_REGIME")

    else:
        failed.append("UNKNOWN_STRATEGY_ROUTE")

    valid = len(failed) == 0
    return EntryValidation(
        valid=valid,
        direction=direction,
        strategy_type=route.selected_strategy,
        reason="ENTRY_VALID" if valid else failed[0],
        passed_conditions=passed,
        failed_conditions=failed,
        details={
            "features": f,
            "route": route.to_dict(),
        },
    )


def score_v1_signal(snapshot: MarketSnapshot, symbol: str, route: ParityRoute, direction: str, validation: EntryValidation, config: dict[str, Any]) -> ScoreResult:
    f = route.details
    strategy_type = route.selected_strategy

    if strategy_type == "trend_following":
        momentum_component = min(35.0, abs(f["momentum_3"]) * 5000.0 + abs(f["momentum_7"]) * 2000.0)
        alignment_component = 25.0 if validation.valid else 0.0
        regime_component = 20.0 if route.regime in {"Uptrend", "Downtrend"} else 0.0
        quality_component = 15.0 if snapshot.warmup_ready.get(symbol, False) else 0.0
        breakdown = {
            "momentum": momentum_component,
            "entry_alignment": alignment_component,
            "regime": regime_component,
            "snapshot_quality": quality_component,
        }

    elif strategy_type == "mean_reversion":
        extremity_component = min(40.0, abs(f["range_deviation"]) * 4500.0)
        validation_component = 25.0 if validation.valid else 0.0
        regime_component = 15.0 if route.regime == "Sideways" else 0.0
        quality_component = 10.0 if snapshot.warmup_ready.get(symbol, False) else 0.0
        breakdown = {
            "range_extremity": extremity_component,
            "entry_validation": validation_component,
            "regime": regime_component,
            "snapshot_quality": quality_component,
        }
    else:
        breakdown = {}

    raw_score = sum(float(v) for v in breakdown.values())
    score = max(0.0, min(100.0, raw_score))

    return ScoreResult(
        ok=validation.valid,
        symbol=symbol,
        direction=direction,
        strategy_type=strategy_type,
        score=round(score, 2),
        max_score=100.0,
        breakdown=breakdown,
        reason_tags=[
            "SCORE_V1_PROXY",
            f"STRATEGY_{strategy_type.upper()}",
            f"DIRECTION_{direction.upper()}",
        ],
        details={
            "features": f,
            "validation": validation.to_dict(),
            "parity_note": "Phase 15C uses proxy scoring until Feature Factory indicator snapshots are available.",
        },
    )


def build_proposed_trade(snapshot: MarketSnapshot, symbol: str, direction: str, selected_strategy: str, regime: str, score: float, config: dict[str, Any]) -> ProposedTrade:
    entry = snapshot.closes[symbol]
    stop_distance_pct = float(config.get("stop_distance_pct", 0.015))
    tp1_r = float(config.get("tp1_r", 1.5))
    tp2_r = float(config.get("tp2_r", 2.5))
    tp3_r = float(config.get("tp3_r", 3.5))

    if direction == "long":
        stop = entry * (1.0 - stop_distance_pct)
        risk = entry - stop
        take_profits = [
            {"label": "TP1", "price": entry + risk * tp1_r, "close_percent": float(config.get("tp1_close_percent", 50))},
            {"label": "TP2", "price": entry + risk * tp2_r, "close_percent": float(config.get("tp2_close_percent", 30))},
            {"label": "TP3", "price": entry + risk * tp3_r, "close_percent": float(config.get("tp3_close_percent", 20))},
        ]
    else:
        stop = entry * (1.0 + stop_distance_pct)
        risk = stop - entry
        take_profits = [
            {"label": "TP1", "price": entry - risk * tp1_r, "close_percent": float(config.get("tp1_close_percent", 50))},
            {"label": "TP2", "price": entry - risk * tp2_r, "close_percent": float(config.get("tp2_close_percent", 30))},
            {"label": "TP3", "price": entry - risk * tp3_r, "close_percent": float(config.get("tp3_close_percent", 20))},
        ]

    return ProposedTrade(
        valid=True,
        symbol=symbol,
        direction=direction,
        selected_strategy=selected_strategy,
        regime=regime,
        entry_order_type="limit",
        entry_price=entry,
        stop_loss=stop,
        take_profits=take_profits,
        risk_per_unit=risk,
        details={
            "score": score,
            "stop_distance_pct": stop_distance_pct,
            "target_policy": {
                "tp1_r": tp1_r,
                "tp2_r": tp2_r,
                "tp3_r": tp3_r,
            },
        },
    )


def decide_strategy_signal(
    *,
    symbol: str,
    route: ParityRoute,
    validation: EntryValidation,
    score_result: ScoreResult,
    proposed_trade: ProposedTrade | None,
    config: dict[str, Any],
    candidate_filter_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    threshold = float(config.get("strategy_btc_trade_threshold", 80.0)) if symbol.upper().startswith("BTC") else float(config.get("strategy_trade_threshold", 75.0))
    observe_threshold = float(config.get("strategy_observe_threshold", 50.0))

    if validation.valid and proposed_trade and score_result.score >= threshold:
        decision = "trade_candidate"
        legacy_decision = "trade"
        reason = "TRADE_CANDIDATE"
    elif score_result.score >= observe_threshold:
        decision = "observe"
        legacy_decision = "observe"
        reason = "OBSERVE_ONLY"
    else:
        decision = "no_trade"
        legacy_decision = "no_trade"
        reason = validation.reason if not validation.valid else "SCORE_BELOW_TRADE_THRESHOLD"

    reason_tags = [
        *route.reason_tags,
        *validation.passed_conditions,
        *validation.failed_conditions,
        *score_result.reason_tags,
        reason,
    ]

    return {
        "ok": True,
        "symbol": symbol,
        "decision": decision,
        "legacy_decision": legacy_decision,
        "decision_side": validation.direction if validation.direction in {"long", "short"} else None,
        "regime": route.regime,
        "selected_strategy": route.selected_strategy,
        "macro_bias": route.macro_bias,
        "score": score_result.score,
        "confidence": max(0.0, min(0.95, score_result.score / 100.0)),
        "reason": reason,
        "reason_tags": reason_tags,
        "score_breakdown": score_result.breakdown,
        "score_details": score_result.details,
        "entry_validation": validation.to_dict(),
        "regime_route": route.to_dict(),
        "proposed_trade": proposed_trade.to_dict() if proposed_trade else None,
        "candidate_filter_context": candidate_filter_context or {},
        "parity_adapter_version": PARITY_ADAPTER_VERSION,
    }


def analyze_snapshot_symbol(snapshot: MarketSnapshot, symbol: str, config: dict[str, Any], candidate_filter_context: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = str(symbol).upper()

    valid_snapshot, snapshot_reasons = validate_snapshot_for_strategy(snapshot, symbol)
    if not valid_snapshot:
        route = ParityRoute(
            valid=False,
            regime="unknown",
            selected_strategy="none",
            direction_hint="neutral",
            macro_bias="neutral",
            reason_tags=["SNAPSHOT_NOT_READY_FOR_STRATEGY"] + snapshot_reasons,
            details={"snapshot_refs": snapshot_refs(snapshot)},
        )
        validation = EntryValidation(
            valid=False,
            direction="neutral",
            strategy_type="none",
            reason="SNAPSHOT_NOT_READY_FOR_STRATEGY",
            passed_conditions=[],
            failed_conditions=snapshot_reasons,
            details={},
        )
        score = ScoreResult(
            ok=False,
            symbol=symbol,
            direction="neutral",
            strategy_type="none",
            score=0.0,
            max_score=100.0,
            breakdown={},
            reason_tags=["SNAPSHOT_NOT_READY_FOR_STRATEGY"],
            details={},
        )
        return decide_strategy_signal(
            symbol=symbol,
            route=route,
            validation=validation,
            score_result=score,
            proposed_trade=None,
            config=config,
            candidate_filter_context=candidate_filter_context,
        )

    route = route_regime(snapshot, symbol, config)
    candidates = []
    for direction in direction_candidates_for_route(route):
        validation = check_v1_entry(snapshot, symbol, route, direction, config)
        score = score_v1_signal(snapshot, symbol, route, direction, validation, config)
        proposed = None
        if validation.valid:
            proposed = build_proposed_trade(
                snapshot,
                symbol=symbol,
                direction=direction,
                selected_strategy=route.selected_strategy,
                regime=route.regime,
                score=score.score,
                config=config,
            )
        candidates.append({
            "direction": direction,
            "entry_validation": validation,
            "score_result": score,
            "proposed_trade": proposed,
        })

    if not candidates:
        validation = EntryValidation(False, "neutral", route.selected_strategy, "NO_DIRECTION_CANDIDATE", [], ["NO_DIRECTION_CANDIDATE"], {})
        score = ScoreResult(False, symbol, "neutral", route.selected_strategy, 0.0, 100.0, {}, ["NO_DIRECTION_CANDIDATE"], {})
        proposed = None
    else:
        best = sorted(
            candidates,
            key=lambda item: (1 if item["entry_validation"].valid else 0, item["score_result"].score),
            reverse=True,
        )[0]
        validation = best["entry_validation"]
        score = best["score_result"]
        proposed = best["proposed_trade"]

    signal = decide_strategy_signal(
        symbol=symbol,
        route=route,
        validation=validation,
        score_result=score,
        proposed_trade=proposed,
        config=config,
        candidate_filter_context=candidate_filter_context,
    )

    signal["direction_evaluation"] = {
        "evaluated_directions": [
            {
                "direction": item["direction"],
                "entry_valid": item["entry_validation"].valid,
                "entry_reason": item["entry_validation"].reason,
                "score": item["score_result"].score,
                "proposed_trade_valid": bool(item["proposed_trade"]),
            }
            for item in candidates
        ],
        "selected_direction": validation.direction,
    }

    return signal
