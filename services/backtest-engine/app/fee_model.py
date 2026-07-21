
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class FeeModel:
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 6.0
    limit_order_fill_ratio: float = 0.80
    override_fee_bps: float | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FeeModel":
        override = config.get("fee_bps_override")
        return cls(
            maker_fee_bps=float(config.get("maker_fee_bps", 2.0)),
            taker_fee_bps=float(config.get("taker_fee_bps", 6.0)),
            limit_order_fill_ratio=float(config.get("limit_order_fill_ratio", 0.80)),
            override_fee_bps=None if override is None else float(override),
        )

    @property
    def effective_fee_bps(self) -> float:
        if self.override_fee_bps is not None:
            return self.override_fee_bps

        maker_ratio = min(max(self.limit_order_fill_ratio, 0.0), 1.0)
        taker_ratio = 1.0 - maker_ratio
        return (maker_ratio * self.maker_fee_bps) + (taker_ratio * self.taker_fee_bps)

    def fee(self, notional: float) -> float:
        return abs(notional) * (self.effective_fee_bps / 10000.0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effective_fee_bps"] = self.effective_fee_bps
        data["effective_fee_pct"] = self.effective_fee_bps / 100.0
        return data
