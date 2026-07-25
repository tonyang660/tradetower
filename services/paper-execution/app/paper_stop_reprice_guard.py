from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PAPER_STOP_REPRICE_BUFFER_BPS = 10.0
MAX_PAPER_STOP_REPRICE_BUFFER_BPS = 50.0

@dataclass(frozen=True)
class PaperStopRepriceDecision:
    applied: bool
    side: str
    reason: str
    current_price: float | None = None
    original_stop_price: float | None = None
    previous_order_price: float | None = None
    repriced_order_price: float | None = None
    buffer_bps: float | None = None

def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if result > 0 else None
    except Exception:
        return None

def normalize_position_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bull", "1"}:
        return "long"
    if text in {"short", "sell", "bear", "-1"}:
        return "short"
    return text

def stop_breached(side: Any, current_price: Any, stop_price: Any) -> bool:
    side = normalize_position_side(side)
    current = _float(current_price)
    stop = _float(stop_price)
    if current is None or stop is None:
        return False
    if side == "long":
        return current <= stop
    if side == "short":
        return current >= stop
    return False

def protective_exit_price_for_breached_paper_stop(
    *,
    side: Any,
    current_price: Any,
    stop_price: Any,
    previous_order_price: Any = None,
    buffer_bps: float = DEFAULT_PAPER_STOP_REPRICE_BUFFER_BPS,
    max_buffer_bps: float = MAX_PAPER_STOP_REPRICE_BUFFER_BPS,
) -> PaperStopRepriceDecision:
    side = normalize_position_side(side)
    current = _float(current_price)
    stop = _float(stop_price)
    previous = _float(previous_order_price)

    if side not in {"long", "short"}:
        return PaperStopRepriceDecision(False, side, "unsupported_side", current, stop, previous)
    if current is None or stop is None:
        return PaperStopRepriceDecision(False, side, "invalid_price", current, stop, previous)
    if not stop_breached(side, current, stop):
        return PaperStopRepriceDecision(False, side, "stop_not_breached", current, stop, previous)

    buffer = max(0.0, min(float(buffer_bps), float(max_buffer_bps)))
    if side == "long":
        price = current * (1.0 - buffer / 10000.0)
        reason = "paper_long_stop_breach_repriced_below_current"
    else:
        price = current * (1.0 + buffer / 10000.0)
        reason = "paper_short_stop_breach_repriced_above_current"

    return PaperStopRepriceDecision(True, side, reason, current, stop, previous, price, buffer)

def decision_to_dict(decision: PaperStopRepriceDecision) -> dict[str, Any]:
    return {
        "applied": decision.applied,
        "side": decision.side,
        "reason": decision.reason,
        "current_price": decision.current_price,
        "original_stop_price": decision.original_stop_price,
        "previous_order_price": decision.previous_order_price,
        "repriced_order_price": decision.repriced_order_price,
        "buffer_bps": decision.buffer_bps,
    }

def apply_paper_stop_reprice_to_payload(
    payload: dict[str, Any],
    *,
    side_key_candidates=("position_side", "side", "trade_side"),
    current_price_key_candidates=("current_price", "mark_price", "last_price", "price"),
    stop_price_key_candidates=("stop_loss", "stop_loss_price", "stop_price", "original_stop_price"),
    order_price_key_candidates=("limit_price", "order_price", "price"),
    output_price_key: str = "limit_price",
    buffer_bps: float = DEFAULT_PAPER_STOP_REPRICE_BUFFER_BPS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        return payload, {"applied": False, "reason": "payload_not_dict"}

    def first(keys):
        for key in keys:
            if payload.get(key) is not None:
                return payload.get(key)
        return None

    decision = protective_exit_price_for_breached_paper_stop(
        side=first(side_key_candidates),
        current_price=first(current_price_key_candidates),
        stop_price=first(stop_price_key_candidates),
        previous_order_price=first(order_price_key_candidates),
        buffer_bps=buffer_bps,
    )
    meta = decision_to_dict(decision)
    if not decision.applied:
        return payload, meta

    patched = dict(payload)
    patched[output_price_key] = decision.repriced_order_price
    patched["paper_stop_reprice_guard"] = meta
    return patched, meta
