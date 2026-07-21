
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Protocol

from market_snapshot import MarketSnapshot


@dataclass(frozen=True)
class StrategyMetadata:
    name: str
    version: str
    family: str
    description: str
    required_timeframes: list[str]
    required_indicators: list[str]
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyDecision:
    symbol: str
    action: str
    side: str | None
    score: float | None
    confidence: float | None
    regime: str
    macro_bias: str
    selected_strategy: str
    reason: str
    reason_tags: list[str]
    debug: dict[str, Any]


@dataclass(frozen=True)
class StrategyContext:
    account_context: dict[str, Any] = field(default_factory=dict)
    candidate_filter_context: dict[str, Any] = field(default_factory=dict)
    run_config: dict[str, Any] = field(default_factory=dict)


class Strategy(Protocol):
    metadata: StrategyMetadata

    def evaluate_symbol(self, snapshot: MarketSnapshot, symbol: str, context: StrategyContext | None = None) -> StrategyDecision:
        ...

    def build_entry_plan(self, snapshot: MarketSnapshot, decision: StrategyDecision, equity: float, risk_per_trade_pct: float) -> dict[str, Any] | None:
        ...


def smart_round(price: float) -> float:
    if price < 0.01:
        return round(price, 8)
    if price < 0.1:
        return round(price, 6)
    if price < 1:
        return round(price, 5)
    if price < 10:
        return round(price, 4)
    if price < 100:
        return round(price, 3)
    return round(price, 2)


def risk_quantity(entry: float, stop: float, equity: float, risk_per_trade_pct: float) -> float:
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0
    risk_amount = equity * risk_per_trade_pct / 100.0
    return max(0.0, risk_amount / risk_per_unit)
