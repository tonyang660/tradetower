"""
Phase 4 Step 2 — MarketSnapshot v2 adapter for v1-style access.

This module does not score signals and does not change Strategy Engine runtime
behavior yet. It gives later v1-port modules stable helpers for reading the
Feature Factory MarketSnapshot v2 payload using the v1 role model:

    entry   -> 5m
    primary -> 15m
    htf     -> 4h

The adapter intentionally works with dictionaries instead of pandas DataFrames,
because Feature Factory now performs indicator/structure computation and emits
a versioned snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ENTRY_TIMEFRAME = "5m"
PRIMARY_TIMEFRAME = "15m"
HTF_TIMEFRAME = "4h"
OPTIONAL_CONTEXT_TIMEFRAME = "1h"

MARKET_SNAPSHOT_SCHEMA_VERSION = "market_snapshot_v2"
SNAPSHOT_ADAPTER_VERSION = "phase4_step2_market_snapshot_v1_adapter"

ROLE_TO_TIMEFRAME = {
    "entry": ENTRY_TIMEFRAME,
    "primary": PRIMARY_TIMEFRAME,
    "htf": HTF_TIMEFRAME,
    "higher_timeframe": HTF_TIMEFRAME,
    "context": OPTIONAL_CONTEXT_TIMEFRAME,
}

REQUIRED_ROLES = ("entry", "primary", "htf")
REQUIRED_TIMEFRAMES = tuple(ROLE_TO_TIMEFRAME[role] for role in REQUIRED_ROLES)

REQUIRED_TIMEFRAME_BLOCKS = (
    "indicators",
    "structure",
    "volatility",
    "regime_inputs",
)

OPTIONAL_TIMEFRAME_BLOCKS = (
    "price_action",
    "latest",
    "data_quality",
)


class SnapshotAdapterError(ValueError):
    """Raised when a MarketSnapshot cannot be adapted safely."""


@dataclass(frozen=True)
class RoleBlock:
    role: str
    timeframe: str
    block: dict[str, Any]

    @property
    def indicators(self) -> dict[str, Any]:
        return self.block.get("indicators", {}) or {}

    @property
    def structure(self) -> dict[str, Any]:
        return self.block.get("structure", {}) or {}

    @property
    def volatility(self) -> dict[str, Any]:
        return self.block.get("volatility", {}) or {}

    @property
    def regime_inputs(self) -> dict[str, Any]:
        return self.block.get("regime_inputs", {}) or {}

    @property
    def price_action(self) -> dict[str, Any]:
        return self.block.get("price_action", {}) or {}

    @property
    def latest(self) -> dict[str, Any]:
        return self.block.get("latest", {}) or {}

    @property
    def data_quality(self) -> dict[str, Any]:
        return self.block.get("data_quality", {}) or {}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").replace("-", "").upper()


def get_timeframes(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot.get("timeframes", {}) or {}


def get_timeframe(snapshot: dict[str, Any], timeframe: str) -> dict[str, Any]:
    return get_timeframes(snapshot).get(timeframe, {}) or {}


def timeframe_for_role(role: str) -> str:
    try:
        return ROLE_TO_TIMEFRAME[role]
    except KeyError as exc:
        raise SnapshotAdapterError(f"unknown_role:{role}") from exc


def get_role_block(snapshot: dict[str, Any], role: str) -> RoleBlock:
    timeframe = timeframe_for_role(role)
    block = get_timeframe(snapshot, timeframe)
    if not block:
        raise SnapshotAdapterError(f"missing_timeframe:{timeframe}")
    return RoleBlock(role=role, timeframe=timeframe, block=block)


def get_entry(snapshot: dict[str, Any]) -> RoleBlock:
    return get_role_block(snapshot, "entry")


def get_primary(snapshot: dict[str, Any]) -> RoleBlock:
    return get_role_block(snapshot, "primary")


def get_htf(snapshot: dict[str, Any]) -> RoleBlock:
    return get_role_block(snapshot, "htf")


def get_context_1h(snapshot: dict[str, Any]) -> RoleBlock | None:
    block = get_timeframe(snapshot, OPTIONAL_CONTEXT_TIMEFRAME)
    if not block:
        return None
    return RoleBlock(role="context", timeframe=OPTIONAL_CONTEXT_TIMEFRAME, block=block)


def get_indicator(snapshot: dict[str, Any], role: str, name: str, default: Any = None) -> Any:
    return get_role_block(snapshot, role).indicators.get(name, default)


def get_structure_value(snapshot: dict[str, Any], role: str, name: str, default: Any = None) -> Any:
    return get_role_block(snapshot, role).structure.get(name, default)


def get_volatility_value(snapshot: dict[str, Any], role: str, name: str, default: Any = None) -> Any:
    return get_role_block(snapshot, role).volatility.get(name, default)


def get_regime_value(snapshot: dict[str, Any], role: str, name: str, default: Any = None) -> Any:
    return get_role_block(snapshot, role).regime_inputs.get(name, default)


def get_price_action_value(snapshot: dict[str, Any], role: str, name: str, default: Any = None) -> Any:
    return get_role_block(snapshot, role).price_action.get(name, default)


def latest_close(snapshot: dict[str, Any], role: str = "primary") -> float:
    role_block = get_role_block(snapshot, role)
    latest = role_block.latest
    indicators = role_block.indicators

    for key in ("close", "last", "price"):
        if latest.get(key) is not None:
            return safe_float(latest.get(key))

    # Compatibility fallback: some snapshot blocks may expose close directly.
    if role_block.block.get("close") is not None:
        return safe_float(role_block.block.get("close"))

    if indicators.get("close") is not None:
        return safe_float(indicators.get("close"))

    return 0.0


def latest_timestamp(snapshot: dict[str, Any], role: str = "primary") -> str | None:
    role_block = get_role_block(snapshot, role)
    latest = role_block.latest
    quality = role_block.data_quality

    return (
        latest.get("timestamp")
        or latest.get("ts")
        or quality.get("last_timestamp")
        or role_block.block.get("last_timestamp")
    )


def v1_trend_direction(snapshot: dict[str, Any], role: str = "primary") -> str:
    role_block = get_role_block(snapshot, role)
    structure = role_block.structure
    regime = role_block.regime_inputs

    return (
        structure.get("v1_trend_direction")
        or regime.get("trend_direction")
        or structure.get("trend_direction")
        or "neutral"
    )


def direction_bias(snapshot: dict[str, Any], role: str = "primary") -> str:
    trend = v1_trend_direction(snapshot, role)

    if trend in ("bullish", "up", "long"):
        return "long"
    if trend in ("bearish", "down", "short"):
        return "short"
    return "neutral"


def primary_regime(snapshot: dict[str, Any]) -> str:
    return str(get_primary(snapshot).regime_inputs.get("v1_regime") or "unknown")


def primary_regime_strategy(snapshot: dict[str, Any]) -> str:
    return str(get_primary(snapshot).regime_inputs.get("v1_regime_strategy") or "unknown")


def get_mean_reversion_range(snapshot: dict[str, Any], role: str = "primary") -> dict[str, Any]:
    return get_role_block(snapshot, role).structure.get("mean_reversion_range", {}) or {}


def get_break_of_structure(snapshot: dict[str, Any], role: str = "primary") -> dict[str, Any]:
    return get_role_block(snapshot, role).structure.get("break_of_structure", {}) or {}


def get_bos_for_direction(snapshot: dict[str, Any], direction: str, role: str = "primary") -> dict[str, Any]:
    bos = get_break_of_structure(snapshot, role)
    if direction == "long":
        return bos.get("bullish", {}) or {}
    if direction == "short":
        return bos.get("bearish", {}) or {}
    return {}


def get_mtf_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot.get("multi_timeframe_context", {}) or {}


def get_mtf_alignment(snapshot: dict[str, Any]) -> dict[str, Any]:
    return get_mtf_context(snapshot).get("alignment", {}) or {}


def get_btc_macro_policy(snapshot: dict[str, Any]) -> dict[str, Any]:
    return get_mtf_context(snapshot).get("btc_macro_policy", {}) or {}


def get_data_quality(snapshot: dict[str, Any]) -> dict[str, Any]:
    return snapshot.get("data_quality", {}) or {}


def snapshot_is_data_healthy(snapshot: dict[str, Any]) -> bool:
    top_quality = get_data_quality(snapshot)
    if top_quality.get("healthy") is False:
        return False

    for role in REQUIRED_ROLES:
        role_block = get_role_block(snapshot, role)
        if role_block.data_quality.get("healthy") is False:
            return False

    return True


def validate_snapshot_for_strategy(snapshot: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not isinstance(snapshot, dict):
        return False, ["SNAPSHOT_NOT_OBJECT"]

    if snapshot.get("schema_version") != MARKET_SNAPSHOT_SCHEMA_VERSION:
        reasons.append("UNEXPECTED_MARKET_SNAPSHOT_SCHEMA")

    timeframes = get_timeframes(snapshot)
    for tf in REQUIRED_TIMEFRAMES:
        if tf not in timeframes:
            reasons.append(f"MISSING_TIMEFRAME:{tf}")
            continue

        tf_block = timeframes.get(tf, {}) or {}
        for block_name in REQUIRED_TIMEFRAME_BLOCKS:
            if block_name not in tf_block:
                reasons.append(f"MISSING_{tf}_{block_name}".upper())

    top_quality = get_data_quality(snapshot)
    if top_quality.get("healthy") is False:
        reasons.append("MARKET_DATA_UNHEALTHY")

    for role in REQUIRED_ROLES:
        try:
            role_block = get_role_block(snapshot, role)
        except SnapshotAdapterError as exc:
            reasons.append(str(exc).upper())
            continue

        if role_block.data_quality.get("healthy") is False:
            reasons.append(f"{role_block.timeframe}_DATA_UNHEALTHY".upper())

    return len(reasons) == 0, reasons


def build_v1_role_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Return a compact v1-like view of the MarketSnapshot.

    This is useful for debugging and for later modules that need role-level
    access without directly knowing timeframe strings.
    """
    entry = get_entry(snapshot)
    primary = get_primary(snapshot)
    htf = get_htf(snapshot)
    context_1h = get_context_1h(snapshot)

    view = {
        "adapter_version": SNAPSHOT_ADAPTER_VERSION,
        "schema_version": snapshot.get("schema_version"),
        "symbol": normalize_symbol(snapshot.get("symbol")),
        "roles": {
            "entry": {
                "timeframe": entry.timeframe,
                "latest_close": latest_close(snapshot, "entry"),
                "latest_timestamp": latest_timestamp(snapshot, "entry"),
                "trend_direction": v1_trend_direction(snapshot, "entry"),
                "direction_bias": direction_bias(snapshot, "entry"),
                "regime": entry.regime_inputs.get("v1_regime"),
                "regime_strategy": entry.regime_inputs.get("v1_regime_strategy"),
            },
            "primary": {
                "timeframe": primary.timeframe,
                "latest_close": latest_close(snapshot, "primary"),
                "latest_timestamp": latest_timestamp(snapshot, "primary"),
                "trend_direction": v1_trend_direction(snapshot, "primary"),
                "direction_bias": direction_bias(snapshot, "primary"),
                "regime": primary.regime_inputs.get("v1_regime"),
                "regime_strategy": primary.regime_inputs.get("v1_regime_strategy"),
            },
            "htf": {
                "timeframe": htf.timeframe,
                "latest_close": latest_close(snapshot, "htf"),
                "latest_timestamp": latest_timestamp(snapshot, "htf"),
                "trend_direction": v1_trend_direction(snapshot, "htf"),
                "direction_bias": direction_bias(snapshot, "htf"),
                "regime": htf.regime_inputs.get("v1_regime"),
                "regime_strategy": htf.regime_inputs.get("v1_regime_strategy"),
            },
        },
        "multi_timeframe_context": get_mtf_context(snapshot),
        "data_quality": get_data_quality(snapshot),
    }

    if context_1h is not None:
        view["roles"]["context_1h"] = {
            "timeframe": context_1h.timeframe,
            "latest_close": latest_close(snapshot, "context"),
            "latest_timestamp": latest_timestamp(snapshot, "context"),
            "trend_direction": v1_trend_direction(snapshot, "context"),
            "direction_bias": direction_bias(snapshot, "context"),
            "regime": context_1h.regime_inputs.get("v1_regime"),
            "regime_strategy": context_1h.regime_inputs.get("v1_regime_strategy"),
        }

    return view


def build_snapshot_refs(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_version": SNAPSHOT_ADAPTER_VERSION,
        "market_snapshot_schema_version": snapshot.get("schema_version"),
        "market_snapshot_contract_version": snapshot.get("contract_version"),
        "feature_factory_version": (snapshot.get("versions", {}) or {}).get("feature_factory_version"),
        "symbol": normalize_symbol(snapshot.get("symbol")),
        "timeframe_roles": {
            "entry": ENTRY_TIMEFRAME,
            "primary": PRIMARY_TIMEFRAME,
            "htf": HTF_TIMEFRAME,
            "context_1h": OPTIONAL_CONTEXT_TIMEFRAME,
        },
        "data_quality_healthy": snapshot_is_data_healthy(snapshot),
        "primary_regime": primary_regime(snapshot) if get_timeframe(snapshot, PRIMARY_TIMEFRAME) else "unknown",
        "primary_regime_strategy": (
            primary_regime_strategy(snapshot)
            if get_timeframe(snapshot, PRIMARY_TIMEFRAME)
            else "unknown"
        ),
    }
