from __future__ import annotations
from typing import Any
from strategies.config_loader import metadata_payload, merge_config_defaults
from strategies.base import StrategyMetadata
from strategies.tradetower_baseline_v1.strategy import TradeTowerBaselineV1Strategy

_STRATEGY_FACTORIES = {"tradetower_baseline_v1": TradeTowerBaselineV1Strategy, "phase14a_baseline": TradeTowerBaselineV1Strategy, "baseline": TradeTowerBaselineV1Strategy}
_CANONICAL_NAMES = {"phase14a_baseline": "tradetower_baseline_v1", "baseline": "tradetower_baseline_v1"}

def canonical_strategy_name(strategy_name: str | None) -> str:
    key = str(strategy_name or "tradetower_baseline_v1").strip()
    return _CANONICAL_NAMES.get(key, key)

def list_strategies(include_details: bool = True) -> list[dict[str, Any]]:
    seen, items = set(), []
    for _, factory in _STRATEGY_FACTORIES.items():
        strategy = factory()
        canonical = strategy.metadata.name
        if canonical in seen:
            continue
        seen.add(canonical)
        item = strategy.metadata.to_dict()
        if include_details:
            item.update(metadata_payload(canonical))
        items.append(item)
    return sorted(items, key=lambda item: item["name"])

def build_strategy(strategy_name: str | None, config: dict[str, Any] | None = None):
    canonical = canonical_strategy_name(strategy_name)
    factory = _STRATEGY_FACTORIES.get(canonical)
    if factory is None:
        raise ValueError(f"unknown_strategy:{strategy_name}")
    return factory(merge_config_defaults(canonical, config or {}))

def get_strategy_metadata(strategy_name: str | None) -> StrategyMetadata:
    return build_strategy(strategy_name).metadata

def get_strategy_detail(strategy_name: str | None) -> dict[str, Any]:
    canonical = canonical_strategy_name(strategy_name)
    strategy = build_strategy(canonical)
    return {**strategy.metadata.to_dict(), **metadata_payload(canonical)}
