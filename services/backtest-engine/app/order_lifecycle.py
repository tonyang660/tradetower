from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PHASE18_ORDER_LIFECYCLE_VERSION = "phase18b_order_lifecycle_foundation"

ORDER_STATUSES = ("created", "submitted", "open", "partially_filled", "filled", "cancelled", "expired", "rejected")
ORDER_ROLES = ("entry", "stop_loss", "sl2", "tp1", "tp2", "tp3", "adaptive_stop", "regime_exit", "volatility_exit", "end_of_backtest")

@dataclass
class OrderLifecycle:
    role: str
    order_type: str
    side: str
    requested_price: float | None
    requested_size: float
    status: str = "created"
    events: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, status: str, *, timestamp=None, details: dict[str, Any] | None = None) -> None:
        if status not in ORDER_STATUSES:
            raise ValueError(f"unsupported_order_status: {status}")
        self.status = status
        self.events.append({"status": status, "timestamp": timestamp, "details": details or {}})

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PHASE18_ORDER_LIFECYCLE_VERSION,
            "role": self.role,
            "order_type": self.order_type,
            "side": self.side,
            "requested_price": self.requested_price,
            "requested_size": self.requested_size,
            "status": self.status,
            "events": self.events,
        }

def build_instant_fill_lifecycle(*, role: str, order_type: str, side: str, requested_price: float | None, requested_size: float, filled_price: float, filled_size: float, timestamp, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    lifecycle = OrderLifecycle(role=role, order_type=order_type, side=side, requested_price=requested_price, requested_size=requested_size)
    lifecycle.transition("created", timestamp=timestamp, details={"reason": reason})
    lifecycle.transition("submitted", timestamp=timestamp, details={"reason": reason})
    lifecycle.transition("filled", timestamp=timestamp, details={"reason": reason, "filled_price": filled_price, "filled_size": filled_size, **(details or {})})
    return lifecycle.to_dict()

def phase18_lifecycle_contract() -> dict[str, Any]:
    return {
        "version": PHASE18_ORDER_LIFECYCLE_VERSION,
        "statuses": list(ORDER_STATUSES),
        "roles": list(ORDER_ROLES),
        "notes": [
            "Phase 18B introduces order lifecycle metadata.",
            "Phase 18C/D will replace instant-fill lifecycle with realistic fill states.",
            "Timeout/stale-trade exits are intentionally excluded.",
        ],
    }
