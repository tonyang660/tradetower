"""
Phase 6 Step 4 — fee, slippage, spread, and reference-price accounting.

This module centralizes paper-execution pricing math.

It does not decide whether a trade should happen. It only calculates:

- reference price metadata
- side-aware market slippage
- estimated spread metadata
- limit vs market fee
- notional
- complete pricing context for evaluator/debugging
"""

from __future__ import annotations

from typing import Any

EXECUTION_PRICING_VERSION = "phase6_step4_execution_pricing_accounting"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_side(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    return "unknown"


def normalize_order_type(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("limit", "market"):
        return value
    return "limit"


def calculate_fee(*, notional: float, fee_pct: float) -> float:
    return safe_float(notional) * (safe_float(fee_pct) / 100.0)


def calculate_notional(*, fill_price: float, size: float) -> float:
    return safe_float(fill_price) * safe_float(size)


def calculate_spread_bps(*, bid_price: float | None, ask_price: float | None, mid_price: float | None = None) -> float | None:
    if bid_price is None or ask_price is None:
        return None

    bid = safe_float(bid_price)
    ask = safe_float(ask_price)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None

    mid = safe_float(mid_price) if mid_price is not None else (bid + ask) / 2.0
    if mid <= 0:
        return None

    return ((ask - bid) / mid) * 10000.0


def extract_reference_prices(*, ticker_payload: dict[str, Any] | None, fallback_price: float) -> dict[str, Any]:
    ticker = ticker_payload or {}

    mark_price = ticker.get("mark_price")
    last_price = ticker.get("last_price")
    bid_price = ticker.get("bid_price")
    ask_price = ticker.get("ask_price")

    selected_price = None
    reference_source = None

    if mark_price is not None and safe_float(mark_price) > 0:
        selected_price = safe_float(mark_price)
        reference_source = "mark_price"
    elif last_price is not None and safe_float(last_price) > 0:
        selected_price = safe_float(last_price)
        reference_source = "last_price"
    elif fallback_price is not None and safe_float(fallback_price) > 0:
        selected_price = safe_float(fallback_price)
        reference_source = "requested_price_fallback"
    else:
        selected_price = 0.0
        reference_source = "missing_reference_price"

    spread_bps = calculate_spread_bps(
        bid_price=safe_float(bid_price) if bid_price is not None else None,
        ask_price=safe_float(ask_price) if ask_price is not None else None,
        mid_price=selected_price if selected_price > 0 else None,
    )

    return {
        "reference_price": round(selected_price, 8),
        "reference_source": reference_source,
        "mark_price": safe_float(mark_price) if mark_price is not None else None,
        "last_price": safe_float(last_price) if last_price is not None else None,
        "bid_price": safe_float(bid_price) if bid_price is not None else None,
        "ask_price": safe_float(ask_price) if ask_price is not None else None,
        "spread_bps": round(spread_bps, 8) if spread_bps is not None else None,
    }


def apply_market_slippage(*, price: float, side: str, slippage_pct: float) -> float:
    slip = safe_float(slippage_pct) / 100.0
    side = normalize_side(side)

    if side == "long":
        return safe_float(price) * (1.0 + slip)
    if side == "short":
        return safe_float(price) * (1.0 - slip)
    return safe_float(price)


def build_entry_pricing_context(
    *,
    payload: dict[str, Any],
    order_type: str,
    fill_price: float,
    size: float,
    fee_pct: float,
    slippage_bps: float,
    fill_source: str,
    fill_reason: str,
    reference_prices: dict[str, Any] | None = None,
) -> dict[str, Any]:
    order_type = normalize_order_type(order_type)
    fill_price = safe_float(fill_price)
    size = safe_float(size)
    notional = calculate_notional(fill_price=fill_price, size=size)
    fee_paid = calculate_fee(notional=notional, fee_pct=fee_pct)

    return {
        "execution_pricing_version": EXECUTION_PRICING_VERSION,
        "order_type": order_type,
        "position_side": normalize_side(payload.get("position_side")),
        "fill_price": round(fill_price, 8),
        "filled_size": round(size, 8),
        "notional": round(notional, 8),
        "fee_pct": round(safe_float(fee_pct), 8),
        "fee_paid": round(fee_paid, 8),
        "slippage_bps": round(safe_float(slippage_bps), 8),
        "fill_source": fill_source,
        "fill_reason": fill_reason,
        "reference_prices": reference_prices or {},
        "requested_entry_price": safe_float(payload.get("entry_price")),
        "requested_size": safe_float(payload.get("size")),
        "risk_amount": safe_float(payload.get("risk_amount")),
        "leverage": safe_float(payload.get("leverage", 1.0)),
    }


def pricing_contract() -> dict[str, Any]:
    return {
        "execution_pricing_version": EXECUTION_PRICING_VERSION,
        "fee_model": "notional * fee_pct / 100",
        "market_slippage_model": "long pays upward slippage, short pays downward slippage on entry",
        "reference_price_priority": ["mark_price", "last_price", "requested_price_fallback"],
        "spread_model": "optional bid/ask spread metadata only; does not yet alter fill price",
        "does_not_change": [
            "strategy scoring",
            "risk sizing",
            "pending retry count",
            "protective order management",
            "adaptive stop management",
            "partial fills",
        ],
    }
