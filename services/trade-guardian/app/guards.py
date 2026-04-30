from orders import get_open_entry_order
from positions import get_open_position


def compute_entry_guard_check(
    status: dict,
    symbol: str | None = None,
    ignore_pending_order: bool = False,
):
    reason_codes = []

    if not status["is_active"]:
        reason_codes.append("ACCOUNT_INACTIVE")

    if not status["trading_enabled"]:
        reason_codes.append("TRADING_DISABLED")

    if status["manual_halt"]:
        reason_codes.append("MANUAL_HALT")

    if status["daily_kill_switch"]:
        reason_codes.append("DAILY_KILL_SWITCH")

    if status["weekly_kill_switch"]:
        reason_codes.append("WEEKLY_KILL_SWITCH")

    if status["open_positions_count"] >= status["max_concurrent_positions"]:
        reason_codes.append("MAX_CONCURRENT_POSITIONS_REACHED")

    existing_position = None
    existing_pending_order = None

    if symbol:
        symbol = symbol.upper()

        existing_position = get_open_position(status["account_id"], symbol)
        if existing_position is not None:
            reason_codes.append("SYMBOL_ALREADY_HAS_OPEN_POSITION")

        if not ignore_pending_order:
            existing_pending_order = get_open_entry_order(status["account_id"], symbol)
            if existing_pending_order is not None:
                reason_codes.append("SYMBOL_ALREADY_HAS_PENDING_ORDER")

    return {
        "trade_allowed": len(reason_codes) == 0,
        "reason_codes": reason_codes,
        "existing_position": existing_position,
        "existing_pending_order": existing_pending_order if not ignore_pending_order else None,
    }


def compute_maintenance_guard_check(status: dict, symbol: str | None = None):
    reason_codes = []

    if not status["is_active"]:
        reason_codes.append("ACCOUNT_INACTIVE")

    # Important rule:
    # maintenance actions remain allowed even if trading is disabled,
    # manual halt is active, or kill switches are active.
    # We only require that the account exists and that an open position exists if symbol is provided.

    if symbol:
        existing_position = get_open_position(status["account_id"], symbol.upper())
        if existing_position is None:
            reason_codes.append("NO_OPEN_POSITION_FOR_SYMBOL")

    return {
        "maintenance_allowed": len(reason_codes) == 0,
        "reason_codes": reason_codes,
    }
