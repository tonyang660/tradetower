"""
Phase 5 Step 7 — correlation group exposure checks.

This module ports the v1 idea of limiting correlated active signals. The known
v1 rule is max correlated signals = 2. Symbol/group mapping is now represented
in symbol_universe.json so it can later be edited from the dashboard.
"""

from __future__ import annotations

from typing import Any

CORRELATION_POLICY_VERSION = "phase5_step7_correlation_group_exposure"

DEFAULT_MAX_CORRELATED_ENTRIES = 2

DEFAULT_SYMBOL_CORRELATION_GROUPS = {
    # Majors
    "BTCUSDT": "btc_followers",
    "ETHUSDT": "major_alts",
    "BNBUSDT": "major_alts",
    "XRPUSDT": "major_alts",
    "SOLUSDT": "layer1",
    "ADAUSDT": "layer1",
    "DOTUSDT": "layer1",
    "SUIUSDT": "layer1",
    "SEIUSDT": "layer1",
    "AVAXUSDT": "layer1",
    "ATOMUSDT": "layer1",
    "NEARUSDT": "layer1",
    "APTUSDT": "layer1",

    # Infrastructure / DeFi
    "LINKUSDT": "defi",
    "ARBUSDT": "defi",
    "OPUSDT": "defi",
    "UNIUSDT": "defi",
    "AAVEUSDT": "defi",
    "HBARUSDT": "independent",
    "XLMUSDT": "major_alts",

    # Meme / high beta
    "DOGEUSDT": "meme",
    "SHIBUSDT": "meme",
    "PEPEUSDT": "meme",
    "WIFUSDT": "meme",
    "BONKUSDT": "meme",

    # Privacy
    "ZECUSDT": "privacy",
    "XMRUSDT": "privacy",

    # AI / data
    "TAOUSDT": "ai_sector",
    "FETUSDT": "ai_sector",
    "RNDRUSDT": "ai_sector",

    # Gaming/RWA/other
    "IMXUSDT": "gaming_rwa",
    "HYPEUSDT": "independent",
    "LTCUSDT": "btc_followers",
}


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().replace("-", "").replace("/", "")


def normalize_group(group: Any) -> str:
    value = str(group or "").strip().lower()
    if not value:
        return "independent"
    return value


def normalize_side(value: Any) -> str | None:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    if value == "buy":
        return "long"
    if value == "sell":
        return "short"
    return None


def correlation_group_for_symbol(
    symbol: str,
    symbol_metadata: dict[str, Any] | None = None,
    default_groups: dict[str, str] | None = None,
) -> str:
    symbol = normalize_symbol(symbol)
    metadata = symbol_metadata or {}

    group = (
        metadata.get("correlation_group")
        or metadata.get("correlationGroup")
        or metadata.get("group")
    )
    if group:
        return normalize_group(group)

    groups = default_groups or DEFAULT_SYMBOL_CORRELATION_GROUPS
    return normalize_group(groups.get(symbol, "independent"))


def extract_symbol_metadata_from_universe(symbol_universe: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in symbol_universe or []:
        symbol = normalize_symbol(item.get("symbol"))
        if not symbol:
            continue
        result[symbol] = dict(item)
    return result


def active_item_group(
    item: dict[str, Any],
    symbol_metadata_map: dict[str, dict[str, Any]] | None = None,
) -> str:
    symbol = normalize_symbol(item.get("symbol"))
    metadata = dict(symbol_metadata_map.get(symbol, {})) if symbol_metadata_map else {}

    # Runtime execution context can override if present.
    context = item.get("execution_context") or {}
    if isinstance(context, dict):
        if context.get("correlation_group"):
            metadata["correlation_group"] = context.get("correlation_group")

    if item.get("correlation_group"):
        metadata["correlation_group"] = item.get("correlation_group")

    return correlation_group_for_symbol(symbol, metadata)


def summarize_correlation_exposure(
    *,
    open_positions: list[dict[str, Any]] | None,
    pending_entries: list[dict[str, Any]] | None,
    symbol_universe: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    open_positions = open_positions or []
    pending_entries = pending_entries or []
    symbol_metadata_map = extract_symbol_metadata_from_universe(symbol_universe)

    groups: dict[str, dict[str, Any]] = {}

    def ensure_group(group: str):
        if group not in groups:
            groups[group] = {
                "group": group,
                "open_positions_count": 0,
                "pending_entries_count": 0,
                "total_active_count": 0,
                "symbols": [],
                "direction_counts": {"long": 0, "short": 0, "unknown": 0},
            }
        return groups[group]

    for item in open_positions:
        symbol = normalize_symbol(item.get("symbol"))
        group = active_item_group(item, symbol_metadata_map)
        side = normalize_side(item.get("position_side")) or normalize_side(item.get("side")) or "unknown"
        entry = ensure_group(group)
        entry["open_positions_count"] += 1
        entry["total_active_count"] += 1
        if symbol:
            entry["symbols"].append(symbol)
        entry["direction_counts"][side] = entry["direction_counts"].get(side, 0) + 1

    for item in pending_entries:
        symbol = normalize_symbol(item.get("symbol"))
        group = active_item_group(item, symbol_metadata_map)
        side = normalize_side(item.get("position_side")) or normalize_side(item.get("side")) or "unknown"
        entry = ensure_group(group)
        entry["pending_entries_count"] += 1
        entry["total_active_count"] += 1
        if symbol:
            entry["symbols"].append(symbol)
        entry["direction_counts"][side] = entry["direction_counts"].get(side, 0) + 1

    for entry in groups.values():
        entry["symbols"] = sorted(set(entry["symbols"]))

    return {
        "correlation_policy_version": CORRELATION_POLICY_VERSION,
        "groups": dict(sorted(groups.items())),
    }


def evaluate_correlation_constraints(
    *,
    symbol: str,
    side: str,
    open_positions: list[dict[str, Any]] | None,
    pending_entries: list[dict[str, Any]] | None,
    symbol_universe: list[dict[str, Any]] | None = None,
    max_correlated_entries: int = DEFAULT_MAX_CORRELATED_ENTRIES,
) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    side = normalize_side(side) or "unknown"

    symbol_metadata_map = extract_symbol_metadata_from_universe(symbol_universe)
    new_group = correlation_group_for_symbol(
        symbol,
        symbol_metadata_map.get(symbol, {}),
    )

    summary = summarize_correlation_exposure(
        open_positions=open_positions,
        pending_entries=pending_entries,
        symbol_universe=symbol_universe,
    )

    current_group = summary["groups"].get(new_group, {
        "group": new_group,
        "open_positions_count": 0,
        "pending_entries_count": 0,
        "total_active_count": 0,
        "symbols": [],
        "direction_counts": {"long": 0, "short": 0, "unknown": 0},
    })

    projected_group_count = int(current_group.get("total_active_count", 0)) + 1
    reason_codes: list[str] = []

    if projected_group_count > int(max_correlated_entries):
        reason_codes.append("CORRELATION_GROUP_LIMIT_REACHED")

    return {
        "ok": len(reason_codes) == 0,
        "correlation_policy_version": CORRELATION_POLICY_VERSION,
        "reason_codes": reason_codes,
        "new_trade": {
            "symbol": symbol,
            "side": side,
            "correlation_group": new_group,
        },
        "limits": {
            "max_correlated_entries": int(max_correlated_entries),
        },
        "current_group": current_group,
        "projected": {
            "group": new_group,
            "total_active_count": projected_group_count,
        },
        "summary": summary,
    }


def build_correlation_policy_contract() -> dict[str, Any]:
    return {
        "correlation_policy_version": CORRELATION_POLICY_VERSION,
        "default_max_correlated_entries": DEFAULT_MAX_CORRELATED_ENTRIES,
        "default_symbol_correlation_groups": DEFAULT_SYMBOL_CORRELATION_GROUPS,
        "symbol_universe_field": "correlation_group",
        "editable_in_dashboard": True,
        "rejection_reasons": [
            "CORRELATION_GROUP_LIMIT_REACHED",
        ],
    }
