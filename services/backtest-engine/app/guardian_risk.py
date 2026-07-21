
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class GuardianPolicy:
    trading_enabled: bool = True
    read_only_mode: bool = False
    maintenance_only_mode: bool = False
    max_concurrent_positions: int = 3
    max_account_exposure_pct: float = 50.0
    daily_loss_limit_pct: float = 3.0
    weekly_loss_limit_pct: float = 6.0

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "GuardianPolicy":
        return cls(
            trading_enabled=bool(config.get("guardian_trading_enabled", True)),
            read_only_mode=bool(config.get("guardian_read_only_mode", False)),
            maintenance_only_mode=bool(config.get("guardian_maintenance_only_mode", False)),
            max_concurrent_positions=int(config.get("guardian_max_concurrent_positions", 3)),
            max_account_exposure_pct=float(config.get("guardian_max_account_exposure_pct", 50.0)),
            daily_loss_limit_pct=float(config.get("guardian_daily_loss_limit_pct", 3.0)),
            weekly_loss_limit_pct=float(config.get("guardian_weekly_loss_limit_pct", 6.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardianDecision:
    allowed: bool
    reason_codes: list[str]
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_entry_guard(
    *,
    policy: GuardianPolicy,
    symbol: str,
    planned_notional: float,
    equity: float,
    starting_capital: float,
    realized_pnl: float,
    open_positions: dict[str, dict[str, Any]],
) -> GuardianDecision:
    reasons: list[str] = []

    if not policy.trading_enabled:
        reasons.append("TRADING_DISABLED")

    if policy.read_only_mode:
        reasons.append("READ_ONLY_MODE")

    if policy.maintenance_only_mode:
        reasons.append("MAINTENANCE_ONLY_MODE")

    if symbol in open_positions:
        reasons.append("DUPLICATE_SYMBOL_POSITION")

    if len(open_positions) >= policy.max_concurrent_positions:
        reasons.append("MAX_CONCURRENT_POSITIONS")

    if planned_notional <= 0:
        reasons.append("INVALID_NOTIONAL")

    current_exposure = sum(abs(p.get("entry", 0.0) * p.get("qty", 0.0)) for p in open_positions.values())
    exposure_after = current_exposure + abs(planned_notional)
    exposure_pct_after = (exposure_after / equity * 100.0) if equity > 0 else 999999.0

    if exposure_pct_after > policy.max_account_exposure_pct:
        reasons.append("MAX_ACCOUNT_EXPOSURE")

    realized_loss_pct = max(0.0, -realized_pnl / starting_capital * 100.0) if starting_capital > 0 else 0.0

    # Phase 14D does not yet segment calendar days/weeks. It uses cumulative
    # run-to-date realized loss as a conservative first guardian simulation.
    if realized_loss_pct >= policy.daily_loss_limit_pct:
        reasons.append("DAILY_LOSS_LIMIT")

    if realized_loss_pct >= policy.weekly_loss_limit_pct:
        reasons.append("WEEKLY_LOSS_LIMIT")

    details = {
        "symbol": symbol,
        "planned_notional": planned_notional,
        "current_exposure": current_exposure,
        "exposure_after": exposure_after,
        "exposure_pct_after": exposure_pct_after,
        "equity": equity,
        "realized_pnl": realized_pnl,
        "realized_loss_pct": realized_loss_pct,
        "open_position_count": len(open_positions),
        "policy": policy.to_dict(),
    }

    return GuardianDecision(
        allowed=len(reasons) == 0,
        reason_codes=reasons,
        message="ENTRY_ALLOWED" if not reasons else "ENTRY_REJECTED",
        details=details,
    )
