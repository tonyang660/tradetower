"""
Phase 4 Step 3 — v1 regime routing parity.

This module ports the v1 strategy-family routing rule:

    Sideways           -> Mean-Reversion
    Uptrend/Downtrend  -> Trend-Following

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from snapshot_v1_adapter import (
    direction_bias,
    get_mtf_alignment,
    get_primary,
    primary_regime,
    primary_regime_strategy,
    validate_snapshot_for_strategy,
)

REGIME_ROUTER_VERSION = "phase4_step3_regime_routing_parity"

V1_REGIME_TO_STRATEGY = {
    "Uptrend": "trend_following",
    "Downtrend": "trend_following",
    "Sideways": "mean_reversion",
}

V1_REGIME_TO_STRATEGY_LABEL = {
    "Uptrend": "Trend-Following",
    "Downtrend": "Trend-Following",
    "Sideways": "Mean-Reversion",
}

V1_REGIME_TO_DIRECTION_HINT = {
    "Uptrend": "long",
    "Downtrend": "short",
    "Sideways": "neutral",
}


@dataclass(frozen=True)
class RegimeRoute:
    valid: bool
    regime: str
    regime_strategy: str
    selected_strategy: str
    direction_hint: str
    confidence: float
    reason_tags: list[str]
    source: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "router_version": REGIME_ROUTER_VERSION,
            "regime": self.regime,
            "regime_strategy": self.regime_strategy,
            "selected_strategy": self.selected_strategy,
            "direction_hint": self.direction_hint,
            "confidence": self.confidence,
            "reason_tags": self.reason_tags,
            "source": self.source,
            "details": self.details,
        }


def normalize_regime(value: Any) -> str:
    raw = str(value or "").strip()

    aliases = {
        "up": "Uptrend",
        "uptrend": "Uptrend",
        "bullish": "Uptrend",
        "bull": "Uptrend",
        "down": "Downtrend",
        "downtrend": "Downtrend",
        "bearish": "Downtrend",
        "bear": "Downtrend",
        "sideways": "Sideways",
        "range": "Sideways",
        "ranging": "Sideways",
        "chop": "Sideways",
        "choppy": "Sideways",
        "neutral": "Sideways",
    }

    return aliases.get(raw.lower(), raw if raw in V1_REGIME_TO_STRATEGY else "unknown")


def strategy_for_regime(regime: str) -> str:
    return V1_REGIME_TO_STRATEGY.get(normalize_regime(regime), "none")


def strategy_label_for_regime(regime: str) -> str:
    return V1_REGIME_TO_STRATEGY_LABEL.get(normalize_regime(regime), "unknown")


def direction_hint_for_regime(regime: str) -> str:
    return V1_REGIME_TO_DIRECTION_HINT.get(normalize_regime(regime), "neutral")


def _confidence_from_snapshot(snapshot: dict[str, Any], regime: str, selected_strategy: str) -> tuple[float, list[str]]:
    confidence = 0.55
    reasons: list[str] = []

    primary = get_primary(snapshot)
    primary_inputs = primary.regime_inputs
    primary_label = primary_inputs.get("v1_regime_strategy")
    adapter_strategy_label = strategy_label_for_regime(regime)

    if primary_label == adapter_strategy_label:
        confidence += 0.15
        reasons.append("PRIMARY_REGIME_STRATEGY_MATCHES_ROUTE")
    elif primary_label:
        reasons.append("PRIMARY_REGIME_STRATEGY_DIFFERS_FROM_ROUTE")

    mtf_alignment = get_mtf_alignment(snapshot)
    consensus = mtf_alignment.get("consensus")
    direction_hint = direction_hint_for_regime(regime)

    if selected_strategy == "trend_following":
        if consensus == direction_hint and direction_hint in ("long", "short"):
            confidence += 0.15
            reasons.append("MTF_CONSENSUS_SUPPORTS_TREND_ROUTE")
        elif consensus == "mixed":
            confidence -= 0.05
            reasons.append("MTF_CONSENSUS_MIXED")
    elif selected_strategy == "mean_reversion":
        structure = primary.structure
        range_info = structure.get("mean_reversion_range", {}) or {}
        if range_info.get("valid"):
            confidence += 0.15
            reasons.append("VALID_MEAN_REVERSION_RANGE_SUPPORTS_ROUTE")
        if consensus in ("mixed", "neutral", None):
            confidence += 0.05
            reasons.append("MTF_NOT_STRONGLY_TRENDING")

    if primary.data_quality.get("healthy") is False:
        confidence -= 0.25
        reasons.append("PRIMARY_DATA_QUALITY_UNHEALTHY")

    confidence = max(0.0, min(1.0, confidence))
    return round(confidence, 2), reasons


def route_regime(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Route MarketSnapshot v2 to the v1 strategy family.

    Returns a dictionary instead of raising for normal validation failures so the
    analyzer can turn the route into a no-trade signal later.
    """
    valid_snapshot, validation_reasons = validate_snapshot_for_strategy(snapshot)
    if not valid_snapshot:
        return RegimeRoute(
            valid=False,
            regime="unknown",
            regime_strategy="unknown",
            selected_strategy="none",
            direction_hint="neutral",
            confidence=0.0,
            reason_tags=["SNAPSHOT_NOT_READY_FOR_STRATEGY"] + validation_reasons,
            source="market_snapshot_v2_adapter",
            details={
                "validation_reasons": validation_reasons,
            },
        ).to_dict()

    raw_regime = primary_regime(snapshot)
    regime = normalize_regime(raw_regime)
    selected_strategy = strategy_for_regime(regime)
    regime_strategy = strategy_label_for_regime(regime)
    direction_hint = direction_hint_for_regime(regime)

    reason_tags = []
    if regime == "Uptrend":
        reason_tags.append("REGIME_UPTREND")
        reason_tags.append("ROUTE_TREND_FOLLOWING")
    elif regime == "Downtrend":
        reason_tags.append("REGIME_DOWNTREND")
        reason_tags.append("ROUTE_TREND_FOLLOWING")
    elif regime == "Sideways":
        reason_tags.append("REGIME_SIDEWAYS")
        reason_tags.append("ROUTE_MEAN_REVERSION")
    else:
        reason_tags.append("REGIME_UNKNOWN")
        reason_tags.append("ROUTE_NONE")

    if selected_strategy == "none":
        return RegimeRoute(
            valid=False,
            regime=regime,
            regime_strategy="unknown",
            selected_strategy="none",
            direction_hint="neutral",
            confidence=0.0,
            reason_tags=reason_tags + ["NO_VALID_STRATEGY_ROUTE"],
            source="primary_15m_regime_inputs",
            details={
                "raw_regime": raw_regime,
                "primary_regime_strategy": primary_regime_strategy(snapshot),
            },
        ).to_dict()

    confidence, confidence_reasons = _confidence_from_snapshot(
        snapshot,
        regime,
        selected_strategy,
    )

    primary_bias = direction_bias(snapshot, "primary")
    htf_bias = direction_bias(snapshot, "htf")
    mtf_alignment = get_mtf_alignment(snapshot)

    return RegimeRoute(
        valid=True,
        regime=regime,
        regime_strategy=regime_strategy,
        selected_strategy=selected_strategy,
        direction_hint=direction_hint,
        confidence=confidence,
        reason_tags=sorted(set(reason_tags + confidence_reasons)),
        source="primary_15m_regime_inputs",
        details={
            "raw_regime": raw_regime,
            "primary_regime_strategy": primary_regime_strategy(snapshot),
            "primary_direction_bias": primary_bias,
            "htf_direction_bias": htf_bias,
            "mtf_consensus": mtf_alignment.get("consensus"),
            "mtf_alignment_score": mtf_alignment.get("alignment_score"),
            "v1_rule": "Sideways -> mean_reversion; Uptrend/Downtrend -> trend_following",
        },
    ).to_dict()


def build_regime_route_contract() -> dict[str, Any]:
    return {
        "router_version": REGIME_ROUTER_VERSION,
        "v1_rule": {
            "Uptrend": "trend_following",
            "Downtrend": "trend_following",
            "Sideways": "mean_reversion",
        },
        "source": "MarketSnapshot v2 primary 15m regime_inputs.v1_regime",
        "does_not_score": True,
        "does_not_validate_entry": True,
        "does_not_execute": True,
    }
