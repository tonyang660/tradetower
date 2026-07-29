from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class FeeModel:
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 6.0
    limit_order_fill_ratio: float = 1.00
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

    def fee_bps_for_liquidity(self, liquidity: str | None = None) -> float:
        if self.override_fee_bps is not None:
            return self.override_fee_bps

        value = str(liquidity or "").lower()
        if value == "maker":
            return self.maker_fee_bps
        if value == "taker":
            return self.taker_fee_bps

        return self.effective_fee_bps

    def fee(self, notional: float) -> float:
        return abs(notional) * (self.effective_fee_bps / 10000.0)

    def fee_for_liquidity(self, notional: float, liquidity: str | None = None) -> float:
        return abs(notional) * (self.fee_bps_for_liquidity(liquidity) / 10000.0)

    def fee_details(self, notional: float, liquidity: str | None = None) -> dict[str, Any]:
        fee_bps = self.fee_bps_for_liquidity(liquidity)
        fee = abs(notional) * (fee_bps / 10000.0)
        return {
            "liquidity": liquidity or "effective",
            "fee_bps": fee_bps,
            "fee": fee,
            "notional": abs(notional),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effective_fee_bps"] = self.effective_fee_bps
        data["effective_fee_pct"] = self.effective_fee_bps / 100.0
        return data
