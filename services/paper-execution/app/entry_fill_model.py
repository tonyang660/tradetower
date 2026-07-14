"""
Phase 6 Step 2 — Entry fill model cleanup.

This module isolates entry fill decisions from Paper Execution HTTP plumbing.

The model is intentionally conservative:
- market entries fill at latest mark/last price when available, otherwise requested price
- limit entries fill only when candle range touches the requested price
- limit fills include fill-model context describing the candle/touch evidence
- no retry policy changes are made here
"""

from __future__ import annotations

from typing import Any

ENTRY_FILL_MODEL_VERSION = "phase6_step2_entry_fill_model_v2"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def normalize_order_type(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("limit", "market"):
        return value
    return "unsupported"


def normalize_side(value: Any) -> str:
    value = str(value or "").lower()
    if value in ("long", "short"):
        return value
    return "unknown"


def candle_bounds(candle: dict[str, Any]) -> tuple[float, float]:
    return safe_float(candle.get("low")), safe_float(candle.get("high"))


def candle_touches_price(candle: dict[str, Any], price: float) -> bool:
    low, high = candle_bounds(candle)
    return low <= price <= high


def find_limit_touch(candles: list[dict[str, Any]], price: float) -> dict[str, Any] | None:
    for index, candle in enumerate(candles or []):
        if candle_touches_price(candle, price):
            return {
                "index": index,
                "timestamp": candle.get("timestamp") or candle.get("open_time") or candle.get("ts"),
                "low": safe_float(candle.get("low")),
                "high": safe_float(candle.get("high")),
                "open": safe_float(candle.get("open")),
                "close": safe_float(candle.get("close")),
            }
    return None


def apply_market_slippage(
    *,
    price: float,
    side: str,
    slippage_pct: float,
) -> float:
    slip = safe_float(slippage_pct) / 100.0
    side = normalize_side(side)

    if side == "long":
        return price * (1.0 + slip)
    if side == "short":
        return price * (1.0 - slip)
    return price


def select_market_reference_price(
    *,
    requested_price: float,
    latest_price: float | None = None,
) -> tuple[float, str]:
    if latest_price is not None and safe_float(latest_price) > 0:
        return safe_float(latest_price), "latest_price"
    return safe_float(requested_price), "requested_price_fallback"


def evaluate_entry_fill(
    *,
    payload: dict[str, Any],
    candles: list[dict[str, Any]] | None,
    latest_price: float | None = None,
    market_slippage_pct: float = 0.0,
) -> dict[str, Any]:
    order_type = normalize_order_type(payload.get("order_type") or payload.get("entry_order_type"))
    side = normalize_side(payload.get("position_side"))
    requested_price = safe_float(payload.get("entry_price"))
    requested_size = safe_float(payload.get("size"))

    base_context = {
        "entry_fill_model_version": ENTRY_FILL_MODEL_VERSION,
        "order_type": order_type,
        "position_side": side,
        "requested_price": requested_price,
        "requested_size": requested_size,
        "candles_checked": len(candles or []),
    }

    if order_type not in ("limit", "market"):
        return {
            "ok": False,
            "filled": False,
            "reason_codes": ["UNSUPPORTED_ORDER_TYPE"],
            "context": base_context,
        }

    if requested_price <= 0 or requested_size <= 0:
        return {
            "ok": False,
            "filled": False,
            "reason_codes": ["INVALID_ENTRY_PRICE_OR_SIZE"],
            "context": base_context,
        }

    if order_type == "market":
        reference_price, reference_source = select_market_reference_price(
            requested_price=requested_price,
            latest_price=latest_price,
        )
        fill_price = apply_market_slippage(
            price=reference_price,
            side=side,
            slippage_pct=market_slippage_pct,
        )
        return {
            "ok": True,
            "filled": True,
            "fill_method": "market",
            "fill_price": round(fill_price, 8),
            "slippage_bps": round(safe_float(market_slippage_pct) * 100.0, 8),
            "fill_source": reference_source,
            "fill_reason": "MARKET_ORDER_FILLED",
            "reason_codes": [],
            "context": {
                **base_context,
                "reference_price": round(reference_price, 8),
                "reference_source": reference_source,
            },
        }

    touch = find_limit_touch(candles or [], requested_price)
    if touch is None:
        return {
            "ok": True,
            "filled": False,
            "fill_method": "limit",
            "fill_price": None,
            "slippage_bps": 0.0,
            "fill_source": "recent_candles",
            "fill_reason": "LIMIT_NOT_TOUCHED",
            "reason_codes": ["LIMIT_NOT_TOUCHED"],
            "context": base_context,
        }

    return {
        "ok": True,
        "filled": True,
        "fill_method": "limit",
        "fill_price": round(requested_price, 8),
        "slippage_bps": 0.0,
        "fill_source": "recent_candles",
        "fill_reason": "LIMIT_PRICE_TOUCHED",
        "reason_codes": [],
        "context": {
            **base_context,
            "touch": touch,
        },
    }
