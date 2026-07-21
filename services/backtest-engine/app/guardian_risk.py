
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class GuardianPolicy:
    trading_enabled: bool = True
    read_only_mode: bool = False
    maintenance_only_mode: bool = False
    max_concurrent_positions: int = 3

    # Percent of the account-level notional cap allowed to be used.
    #
    # Example:
    #   equity = 2000
    #   account_max_notional_multiplier = 10
    #   max_account_exposure_pct = 100
    #   max account notional = 2000 * 10 * 100% = 20000
    #
    # If max_account_exposure_pct = 80:
    #   max account notional = 2000 * 10 * 80% = 16000
    max_account_exposure_pct: float = 80.0

    # Maximum leverage allowed for a single position.
    # Example: $200 margin at 15x = $3000 position notional.
    max_position_leverage: float = 15.0

    # Account-level hard cap for total open notional.
    # Example: $2000 account * 10x = $20000 total open notional cap.
    account_max_notional_multiplier: float = 10.0

    daily_loss_limit_pct: float = 3.0
    weekly_loss_limit_pct: float = 6.0

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "GuardianPolicy":
        return cls(
            trading_enabled=bool(config.get("guardian_trading_enabled", True)),
            read_only_mode=bool(config.get("guardian_read_only_mode", False)),
            maintenance_only_mode=bool(config.get("guardian_maintenance_only_mode", False)),
            max_concurrent_positions=int(config.get("guardian_max_concurrent_positions", 3)),
            max_account_exposure_pct=float(config.get("guardian_max_account_exposure_pct", 100.0)),

            # New names. Old names remain accepted as compatibility aliases.
            max_position_leverage=float(
                config.get(
                    "guardian_max_position_leverage",
                    config.get("guardian_max_leverage", 15.0),
                )
            ),
            account_max_notional_multiplier=float(
                config.get(
                    "guardian_account_max_notional_multiplier",
                    config.get("guardian_account_exposure_multiplier", 10.0),
                )
            ),

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

    max_position_leverage = max(float(policy.max_position_leverage), 1.0)
    account_max_notional_multiplier = max(float(policy.account_max_notional_multiplier), 1.0)
    max_account_exposure_fraction = max(float(policy.max_account_exposure_pct), 0.0) / 100.0

    current_notional = sum(
        abs(p.get("entry", 0.0) * p.get("qty", 0.0))
        for p in open_positions.values()
    )
    notional_after = current_notional + abs(planned_notional)

    # Account-level hard cap:
    #   max_account_notional = equity * account_max_notional_multiplier * exposure_pct
    #
    # Example:
    #   equity 2000, multiplier 10, exposure_pct 100 -> 20000 cap
    #   current 18000 + planned 3000 = 21000 -> reject
    max_account_notional = equity * account_max_notional_multiplier * max_account_exposure_fraction
    account_notional_usage_pct_after = (
        notional_after / max_account_notional * 100.0
    ) if max_account_notional > 0 else 999999.0

    account_notional_multiple_after = (
        notional_after / equity
    ) if equity > 0 else 999999.0

    if notional_after > max_account_notional:
        reasons.append("MAX_ACCOUNT_NOTIONAL_EXPOSURE")

    # Margin estimate only. This guard currently does not receive explicit planned margin.
    # Once Phase 18 has realistic execution and margin modelling, per-position leverage
    # should be checked as:
    #   planned_notional <= planned_margin * max_position_leverage
    implied_planned_margin_at_max_position_leverage = abs(planned_notional) / max_position_leverage
    implied_current_margin_at_max_position_leverage = current_notional / max_position_leverage
    implied_margin_after_at_max_position_leverage = notional_after / max_position_leverage
    implied_margin_usage_pct_after = (
        implied_margin_after_at_max_position_leverage / equity * 100.0
    ) if equity > 0 else 999999.0

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
        "current_notional": current_notional,
        "notional_after": notional_after,

        "equity": equity,
        "account_max_notional_multiplier": account_max_notional_multiplier,
        "max_account_exposure_pct": policy.max_account_exposure_pct,
        "max_account_notional": max_account_notional,
        "account_notional_usage_pct_after": account_notional_usage_pct_after,
        "account_notional_multiple_after": account_notional_multiple_after,

        "max_position_leverage": max_position_leverage,
        "implied_planned_margin_at_max_position_leverage": implied_planned_margin_at_max_position_leverage,
        "implied_current_margin_at_max_position_leverage": implied_current_margin_at_max_position_leverage,
        "implied_margin_after_at_max_position_leverage": implied_margin_after_at_max_position_leverage,
        "implied_margin_usage_pct_after": implied_margin_usage_pct_after,

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
