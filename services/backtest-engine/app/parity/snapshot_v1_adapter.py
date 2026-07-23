from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ENTRY_TIMEFRAME = "5m"
PRIMARY_TIMEFRAME = "15m"
HTF_TIMEFRAME = "4h"
OPTIONAL_CONTEXT_TIMEFRAME = "1h"

MARKET_SNAPSHOT_SCHEMA_VERSION = "market_snapshot_v2"
SNAPSHOT_ADAPTER_VERSION = "phase16f_hf1_backtest_market_snapshot_v1_adapter"

ROLE_TO_TIMEFRAME = {
    "entry": ENTRY_TIMEFRAME,
    "primary": PRIMARY_TIMEFRAME,
    "htf": HTF_TIMEFRAME,
    "higher_timeframe": HTF_TIMEFRAME,
    "context": OPTIONAL_CONTEXT_TIMEFRAME,
}
REQUIRED_ROLES = ("entry", "primary", "htf")
REQUIRED_TIMEFRAMES = tuple(ROLE_TO_TIMEFRAME[role] for role in REQUIRED_ROLES)
REQUIRED_TIMEFRAME_BLOCKS = ("indicators", "structure", "volatility", "regime_inputs")


class SnapshotAdapterError(ValueError):
    pass


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
        return default if value is None else float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return default if value is None else int(value)
    except Exception:
        return default


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").replace("-", "").replace("/", "").upper()


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
    block = get_role_block(snapshot, role)
    for key in ("close", "last", "price"):
        if block.latest.get(key) is not None:
            return safe_float(block.latest.get(key))
    if block.block.get("close") is not None:
        return safe_float(block.block.get("close"))
    if block.indicators.get("close") is not None:
        return safe_float(block.indicators.get("close"))
    return 0.0


def latest_timestamp(snapshot: dict[str, Any], role: str = "primary") -> str | None:
    block = get_role_block(snapshot, role)
    return block.latest.get("timestamp") or block.latest.get("ts") or block.data_quality.get("last_timestamp") or block.block.get("last_timestamp")


def v1_trend_direction(snapshot: dict[str, Any], role: str = "primary") -> str:
    block = get_role_block(snapshot, role)
    return (
        block.structure.get("v1_trend_direction")
        or block.regime_inputs.get("trend_direction")
        or block.structure.get("trend_direction")
        or "neutral"
    )


def direction_bias(snapshot: dict[str, Any], role: str = "primary") -> str:
    trend = str(v1_trend_direction(snapshot, role)).lower()
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
    if get_data_quality(snapshot).get("healthy") is False:
        return False
    for role in REQUIRED_ROLES:
        block = get_role_block(snapshot, role)
        if block.data_quality.get("healthy") is False:
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
        block = timeframes.get(tf, {}) or {}
        for name in REQUIRED_TIMEFRAME_BLOCKS:
            if name not in block:
                reasons.append(f"MISSING_{tf}_{name}".upper())
    if get_data_quality(snapshot).get("healthy") is False:
        reasons.append("MARKET_DATA_UNHEALTHY")
    return len(reasons) == 0, reasons


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
        "primary_regime_strategy": primary_regime_strategy(snapshot) if get_timeframe(snapshot, PRIMARY_TIMEFRAME) else "unknown",
    }
