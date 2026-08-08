
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class GuardianPolicy:
    account_enabled: bool = True
    account_active: bool = True
    trading_enabled: bool = True
    manual_halt: bool = False
    read_only_mode: bool = False
    maintenance_only_mode: bool = False
    max_concurrent_positions: int = 5

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
    max_consecutive_losses: int = 3
    consecutive_loss_cooldown_hours: int = 4

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "GuardianPolicy":
        return cls(
            account_enabled=bool(config.get("guardian_account_enabled", True)),
            account_active=bool(config.get("guardian_account_active", True)),
            trading_enabled=bool(config.get("guardian_trading_enabled", True)),
            manual_halt=bool(config.get("guardian_manual_halt", False)),
            read_only_mode=bool(config.get("guardian_read_only_mode", False)),
            maintenance_only_mode=bool(config.get("guardian_maintenance_only_mode", False)),
            max_concurrent_positions=int(config.get("guardian_max_concurrent_positions", 5)),
            max_account_exposure_pct=float(config.get("guardian_max_account_exposure_pct", 80.0)),

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
            max_consecutive_losses=int(config.get("guardian_max_consecutive_losses", 3)),
            consecutive_loss_cooldown_hours=int(config.get("guardian_consecutive_loss_cooldown_hours", 4)),
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


@dataclass
class HistoricalGuardianState:
    daily_basis_date: str | None = None
    daily_basis_equity: float = 0.0
    weekly_basis_start: str | None = None
    weekly_basis_equity: float = 0.0
    daily_kill_switch: bool = False
    weekly_kill_switch: bool = False
    weekly_kill_switch_expires_at: datetime | None = None
    daily_realized_pnl: float = 0.0
    weekly_realized_pnl: float = 0.0
    consecutive_losses: int = 0
    consecutive_loss_cooldown_until: datetime | None = None

    @staticmethod
    def _utc(timestamp) -> datetime:
        value = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def refresh(self, *, timestamp, equity: float, policy: GuardianPolicy) -> None:
        now = self._utc(timestamp)
        day = now.date().isoformat()
        week_start = (now.date() - timedelta(days=now.weekday())).isoformat()
        if self.daily_basis_date != day:
            self.daily_basis_date = day
            self.daily_basis_equity = float(equity)
            self.daily_realized_pnl = 0.0
            self.daily_kill_switch = False
        if self.weekly_basis_start != week_start:
            self.weekly_basis_start = week_start
            self.weekly_basis_equity = float(equity)
            self.weekly_realized_pnl = 0.0
            self.weekly_kill_switch = False
            self.weekly_kill_switch_expires_at = None
        if self.weekly_kill_switch_expires_at and now >= self.weekly_kill_switch_expires_at:
            self.weekly_kill_switch = False
            self.weekly_kill_switch_expires_at = None
        if self.consecutive_loss_cooldown_until and now >= self.consecutive_loss_cooldown_until:
            self.consecutive_losses = 0
            self.consecutive_loss_cooldown_until = None
        if self.daily_basis_equity - equity >= self.daily_basis_equity * policy.daily_loss_limit_pct / 100.0:
            self.daily_kill_switch = True
        if self.weekly_basis_equity - equity >= self.weekly_basis_equity * policy.weekly_loss_limit_pct / 100.0:
            self.weekly_kill_switch = True
            sunday_end = now + timedelta(days=6 - now.weekday())
            sunday_end = sunday_end.replace(hour=23, minute=59, second=59, microsecond=999999)
            self.weekly_kill_switch_expires_at = min(now + timedelta(hours=48), sunday_end)

    def record_completed_trade(self, *, timestamp, realized_pnl: float, policy: GuardianPolicy) -> None:
        now = self._utc(timestamp)
        self.daily_realized_pnl += float(realized_pnl)
        self.weekly_realized_pnl += float(realized_pnl)
        if realized_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= policy.max_consecutive_losses:
                self.consecutive_loss_cooldown_until = now + timedelta(hours=policy.consecutive_loss_cooldown_hours)
        else:
            self.consecutive_losses = 0
            self.consecutive_loss_cooldown_until = None

    def to_dict(self, *, equity: float) -> dict[str, Any]:
        return {
            **asdict(self),
            "equity": float(equity),
            "weekly_pnl": self.weekly_realized_pnl,
            "daily_pnl": self.daily_realized_pnl,
            "daily_drawdown_active": self.daily_kill_switch,
            "in_drawdown": self.daily_kill_switch or self.weekly_kill_switch,
        }


def evaluate_entry_guard(
    *,
    policy: GuardianPolicy,
    symbol: str,
    planned_notional: float,
    equity: float,
    starting_capital: float,
    realized_pnl: float,
    open_positions: dict[str, dict[str, Any]],
    pending_entries: dict[str, dict[str, Any]] | None = None,
    state: HistoricalGuardianState | None = None,
) -> GuardianDecision:
    reasons: list[str] = []

    if not policy.account_enabled:
        reasons.append("ACCOUNT_DISABLED")

    if not policy.account_active:
        reasons.append("ACCOUNT_INACTIVE")

    if not policy.trading_enabled:
        reasons.append("TRADING_DISABLED")

    if policy.manual_halt:
        reasons.append("MANUAL_HALT")

    if policy.read_only_mode:
        reasons.append("READ_ONLY_MODE")

    if policy.maintenance_only_mode:
        reasons.append("MAINTENANCE_ONLY_MODE")

    if symbol in open_positions:
        reasons.append("DUPLICATE_SYMBOL_POSITION")

    if len(open_positions) >= policy.max_concurrent_positions:
        reasons.append("MAX_CONCURRENT_POSITIONS")

    if symbol in (pending_entries or {}):
        reasons.append("SYMBOL_ALREADY_HAS_PENDING_ORDER")

    if state is not None:
        if state.daily_kill_switch:
            reasons.append("DAILY_KILL_SWITCH")
        if state.weekly_kill_switch:
            reasons.append("WEEKLY_KILL_SWITCH")
        if state.consecutive_loss_cooldown_until is not None:
            reasons.append("CONSECUTIVE_LOSS_COOLDOWN")

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
        "pending_entry_count": len(pending_entries or {}),
        "historical_guardian_state": state.to_dict(equity=equity) if state is not None else None,
        "policy": policy.to_dict(),
    }

    return GuardianDecision(
        allowed=len(reasons) == 0,
        reason_codes=reasons,
        message="ENTRY_ALLOWED" if not reasons else "ENTRY_REJECTED",
        details=details,
    )
