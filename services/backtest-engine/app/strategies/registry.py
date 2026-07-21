
from __future__ import annotations

from typing import Any

from strategies.config_loader import metadata_payload, merge_config_defaults
from strategies.base import StrategyMetadata
from strategies.experimental.volatility_breakout_v1.strategy import VolatilityBreakoutV1Strategy
from strategies.mean_reversion_v1.strategy import MeanReversionV1Strategy
from strategies.regime_adaptive_v1.strategy import RegimeAdaptiveV1Strategy
from strategies.tradetower_baseline_v1.strategy import TradeTowerBaselineV1Strategy
from strategies.trend_following_v1.strategy import TrendFollowingV1Strategy


_STRATEGY_FACTORIES = {
    "tradetower_baseline_v1": TradeTowerBaselineV1Strategy,
    "trend_following_v1": TrendFollowingV1Strategy,
    "mean_reversion_v1": MeanReversionV1Strategy,
    "regime_adaptive_v1": RegimeAdaptiveV1Strategy,
    "volatility_breakout_v1": VolatilityBreakoutV1Strategy,

    # Compatibility aliases.
    "phase14a_baseline": TradeTowerBaselineV1Strategy,
    "baseline": TradeTowerBaselineV1Strategy,
}

_CANONICAL_NAMES = {
    "phase14a_baseline": "tradetower_baseline_v1",
    "baseline": "tradetower_baseline_v1",
}


def canonical_strategy_name(strategy_name: str | None) -> str:
    key = str(strategy_name or "tradetower_baseline_v1").strip()
    return _CANONICAL_NAMES.get(key, key)


def list_strategies(include_details: bool = True) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    for name, factory in _STRATEGY_FACTORIES.items():
        strategy = factory()
        canonical = strategy.metadata.name
        if canonical in seen:
            continue
        seen.add(canonical)

        item = strategy.metadata.to_dict()
        if include_details:
            item.update(metadata_payload(canonical))
        items.append(item)

    return sorted(items, key=lambda item: (item["family"], item["name"]))


def build_strategy(strategy_name: str | None, config: dict[str, Any] | None = None):
    canonical = canonical_strategy_name(strategy_name)
    factory = _STRATEGY_FACTORIES.get(canonical)
    if factory is None:
        raise ValueError(f"unknown_strategy:{strategy_name}")

    merged_config = merge_config_defaults(canonical, config or {})
    return factory(merged_config)


def get_strategy_metadata(strategy_name: str | None) -> StrategyMetadata:
    return build_strategy(strategy_name).metadata


def get_strategy_detail(strategy_name: str | None) -> dict[str, Any]:
    canonical = canonical_strategy_name(strategy_name)
    strategy = build_strategy(canonical)
    return {
        **strategy.metadata.to_dict(),
        **metadata_payload(canonical),
    }
