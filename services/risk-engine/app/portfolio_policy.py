"""
Phase 5 Step 6 — portfolio exposure and max-position constraints.

This module evaluates account-level exposure before Risk Engine approves a new
entry. Correlation groups are intentionally excluded from this step and are
handled in Phase 5 Step 7.
"""

from __future__ import annotations

from typing import Any

PORTFOLIO_POLICY_VERSION = "phase5_step6_portfolio_exposure_constraints"

DEFAULT_MAX_OPEN_POSITIONS = 5
DEFAULT_MAX_PENDING_ENTRIES = 5
DEFAULT_MAX_TOTAL_ENTRIES = 5
DEFAULT_MAX_DIRECTIONAL_ENTRIES = 4
DEFAULT_MAX_PORTFOLIO_NOTIONAL_MULTIPLE = 10.0
DEFAULT_MAX_MARGIN_USAGE_PCT = 80.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().replace("-", "").replace("/", "")


def normalize_side(value: Any) -> str | None:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    if value == "buy":
        return "long"
    if value == "sell":
        return "short"
    return None


def position_notional(position: dict[str, Any]) -> float:
    for key in ("notional", "current_notional", "entry_notional"):
        if position.get(key) is not None:
            return safe_float(position.get(key))

    size = (
        position.get("remaining_size")
        if position.get("remaining_size") is not None
        else position.get("size")
    )
    price = (
        position.get("mark_price")
        or position.get("entry_price")
        or position.get("average_entry_price")
    )

    return abs(safe_float(size) * safe_float(price))


def position_margin(position: dict[str, Any]) -> float:
    for key in ("margin_used", "margin_required", "initial_margin"):
        if position.get(key) is not None:
            return safe_float(position.get(key))
    return 0.0


def pending_notional(order: dict[str, Any]) -> float:
    price = (
        order.get("requested_price")
        if order.get("requested_price") is not None
        else order.get("entry_price")
    )
    size = (
        order.get("requested_size")
        if order.get("requested_size") is not None
        else order.get("remaining_size")
    )
    return abs(safe_float(price) * safe_float(size))


def summarize_portfolio(
    *,
    open_positions: list[dict[str, Any]] | None,
    pending_entries: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    open_positions = open_positions or []
    pending_entries = pending_entries or []

    open_symbols = sorted({
        normalize_symbol(item.get("symbol"))
        for item in open_positions
        if item.get("symbol")
    })
    pending_symbols = sorted({
        normalize_symbol(item.get("symbol"))
        for item in pending_entries
        if item.get("symbol")
    })

    direction_counts = {
        "long": 0,
        "short": 0,
        "unknown": 0,
    }

    open_notional = 0.0
    pending_notional_total = 0.0
    margin_used = 0.0

    for position in open_positions:
        side = (
            normalize_side(position.get("position_side"))
            or normalize_side(position.get("side"))
        )
        if side in ("long", "short"):
            direction_counts[side] += 1
        else:
            direction_counts["unknown"] += 1

        open_notional += position_notional(position)
        margin_used += position_margin(position)

    for order in pending_entries:
        side = (
            normalize_side(order.get("position_side"))
            or normalize_side(order.get("side"))
        )
        if side in ("long", "short"):
            direction_counts[side] += 1
        else:
            direction_counts["unknown"] += 1

        pending_notional_total += pending_notional(order)

    return {
        "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
        "open_positions_count": len(open_positions),
        "pending_entries_count": len(pending_entries),
        "total_entries_count": len(open_positions) + len(pending_entries),
        "open_symbols": open_symbols,
        "pending_symbols": pending_symbols,
        "all_active_symbols": sorted(set(open_symbols) | set(pending_symbols)),
        "direction_counts": direction_counts,
        "open_notional": round(open_notional, 8),
        "pending_notional": round(pending_notional_total, 8),
        "total_existing_notional": round(open_notional + pending_notional_total, 8),
        "margin_used": round(margin_used, 8),
    }


def evaluate_portfolio_constraints(
    *,
    symbol: str,
    side: str,
    new_notional: float,
    new_margin_required: float,
    equity: float,
    cash_balance: float,
    open_positions: list[dict[str, Any]] | None,
    pending_entries: list[dict[str, Any]] | None,
    max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
    max_pending_entries: int = DEFAULT_MAX_PENDING_ENTRIES,
    max_total_entries: int = DEFAULT_MAX_TOTAL_ENTRIES,
    max_directional_entries: int = DEFAULT_MAX_DIRECTIONAL_ENTRIES,
    max_portfolio_notional_multiple: float = DEFAULT_MAX_PORTFOLIO_NOTIONAL_MULTIPLE,
    max_margin_usage_pct: float = DEFAULT_MAX_MARGIN_USAGE_PCT,
) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    side = normalize_side(side) or "unknown"
    equity = safe_float(equity)
    cash_balance = safe_float(cash_balance)
    new_notional = safe_float(new_notional)
    new_margin_required = safe_float(new_margin_required)

    summary = summarize_portfolio(
        open_positions=open_positions,
        pending_entries=pending_entries,
    )

    reason_codes: list[str] = []

    if symbol in summary["open_symbols"]:
        reason_codes.append("SYMBOL_ALREADY_HAS_OPEN_POSITION")

    if symbol in summary["pending_symbols"]:
        reason_codes.append("SYMBOL_ALREADY_HAS_PENDING_ENTRY")

    if summary["open_positions_count"] >= int(max_open_positions):
        reason_codes.append("MAX_OPEN_POSITIONS_REACHED")

    if summary["pending_entries_count"] >= int(max_pending_entries):
        reason_codes.append("MAX_PENDING_ENTRIES_REACHED")

    if summary["total_entries_count"] >= int(max_total_entries):
        reason_codes.append("MAX_TOTAL_ENTRIES_REACHED")

    projected_direction_count = summary["direction_counts"].get(side, 0) + 1
    if side in ("long", "short") and projected_direction_count > int(max_directional_entries):
        reason_codes.append("MAX_DIRECTIONAL_ENTRIES_REACHED")

    max_notional = equity * safe_float(max_portfolio_notional_multiple)
    projected_notional = summary["total_existing_notional"] + new_notional
    if max_notional > 0 and projected_notional > max_notional:
        reason_codes.append("MAX_PORTFOLIO_NOTIONAL_EXCEEDED")

    projected_margin_used = summary["margin_used"] + new_margin_required
    margin_base = equity if equity > 0 else cash_balance
    projected_margin_usage_pct = (
        (projected_margin_used / margin_base) * 100.0
        if margin_base > 0
        else 999.0
    )
    if projected_margin_usage_pct > safe_float(max_margin_usage_pct):
        reason_codes.append("MAX_MARGIN_USAGE_EXCEEDED")

    return {
        "ok": len(reason_codes) == 0,
        "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
        "reason_codes": reason_codes,
        "summary": summary,
        "limits": {
            "max_open_positions": int(max_open_positions),
            "max_pending_entries": int(max_pending_entries),
            "max_total_entries": int(max_total_entries),
            "max_directional_entries": int(max_directional_entries),
            "max_portfolio_notional_multiple": safe_float(max_portfolio_notional_multiple),
            "max_margin_usage_pct": safe_float(max_margin_usage_pct),
        },
        "new_trade": {
            "symbol": symbol,
            "side": side,
            "notional": round(new_notional, 8),
            "margin_required": round(new_margin_required, 8),
        },
        "projected": {
            "direction_count": projected_direction_count,
            "total_notional": round(projected_notional, 8),
            "max_notional": round(max_notional, 8),
            "margin_used": round(projected_margin_used, 8),
            "margin_usage_pct": round(projected_margin_usage_pct, 6),
        },
    }


def build_portfolio_policy_contract() -> dict[str, Any]:
    return {
        "portfolio_policy_version": PORTFOLIO_POLICY_VERSION,
        "defaults": {
            "max_open_positions": DEFAULT_MAX_OPEN_POSITIONS,
            "max_pending_entries": DEFAULT_MAX_PENDING_ENTRIES,
            "max_total_entries": DEFAULT_MAX_TOTAL_ENTRIES,
            "max_directional_entries": DEFAULT_MAX_DIRECTIONAL_ENTRIES,
            "max_portfolio_notional_multiple": DEFAULT_MAX_PORTFOLIO_NOTIONAL_MULTIPLE,
            "max_margin_usage_pct": DEFAULT_MAX_MARGIN_USAGE_PCT,
        },
        "checks": [
            "symbol already open",
            "symbol already pending",
            "max open positions",
            "max pending entries",
            "max total active entries",
            "max directional active entries",
            "max portfolio notional multiple",
            "max margin usage percent",
        ],
        "does_not_include": [
            "correlation groups",
            "daily loss limit",
            "weekly loss limit",
            "BTC macro adjustment",
        ],
    }
