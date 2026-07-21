
from __future__ import annotations

from typing import Any

from strategies.base import StrategyMetadata
from strategies.tradetower_baseline_v1.strategy import TradeTowerBaselineV1Strategy


_STRATEGY_FACTORIES = {
    "tradetower_baseline_v1": TradeTowerBaselineV1Strategy,
    "phase14a_baseline": TradeTowerBaselineV1Strategy,
    "baseline": TradeTowerBaselineV1Strategy,
}


def list_strategies() -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for _, factory in _STRATEGY_FACTORIES.items():
        strategy = factory()
        canonical = strategy.metadata.name
        if canonical in seen:
            continue
        seen.add(canonical)
        items.append(strategy.metadata.to_dict())
    return sorted(items, key=lambda item: item["name"])


def build_strategy(strategy_name: str | None, config: dict[str, Any] | None = None):
    key = str(strategy_name or "tradetower_baseline_v1").strip()
    factory = _STRATEGY_FACTORIES.get(key)
    if factory is None:
        raise ValueError(f"unknown_strategy:{key}")
    return factory(config or {})


def get_strategy_metadata(strategy_name: str | None) -> StrategyMetadata:
    return build_strategy(strategy_name).metadata
