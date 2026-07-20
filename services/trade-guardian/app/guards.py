from orders import get_open_entry_order
from positions import get_open_position

def _validate_execution_mode(status: dict) -> list[str]:
    account_type = status.get("account_type")
    execution_mode = status.get("execution_mode")
    if account_type == "paper" and execution_mode != "paper":
        return ["INVALID_ACCOUNT_EXECUTION_MODE"]
    if account_type == "live" and execution_mode not in ("shadow", "live"):
        return ["INVALID_ACCOUNT_EXECUTION_MODE"]
    return []

def compute_entry_guard_check(status: dict, symbol: str | None = None, ignore_pending_order: bool = False):
    reason_codes = []
    reason_codes.extend(_validate_execution_mode(status))
    reconciliation_gate = status.get("reconciliation_gate") or {}
    reason_codes.extend(reconciliation_gate.get("reason_codes", []))
    if not status.get("enabled", status.get("is_active", True)):
        reason_codes.append("ACCOUNT_DISABLED")
    if not status["is_active"]:
        reason_codes.append("ACCOUNT_INACTIVE")
    if status.get("read_only_mode"):
        reason_codes.append("READ_ONLY_MODE")
    if status.get("maintenance_only_mode"):
        reason_codes.append("MAINTENANCE_ONLY_MODE")
    if not status["trading_enabled"]:
        reason_codes.append("TRADING_DISABLED")
    if status["manual_halt"]:
        reason_codes.append("MANUAL_HALT")
    if status["daily_kill_switch"]:
        reason_codes.append("DAILY_KILL_SWITCH")
    if status["weekly_kill_switch"]:
        reason_codes.append("WEEKLY_KILL_SWITCH")
    if status.get("consecutive_loss_cooldown_until") is not None:
        reason_codes.append("CONSECUTIVE_LOSS_COOLDOWN")
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
        "execution_mode": status.get("execution_mode"),
        "existing_position": existing_position,
        "existing_pending_order": existing_pending_order if not ignore_pending_order else None,
    }

def compute_maintenance_guard_check(status: dict, symbol: str | None = None):
    reason_codes = []
    reason_codes.extend(_validate_execution_mode(status))
    # Disabled/read-only/maintenance-only/manual halt/kill switch states block
    # new exposure, not risk-reduction maintenance.
    if symbol:
        existing_position = get_open_position(status["account_id"], symbol.upper())
        if existing_position is None:
            reason_codes.append("NO_OPEN_POSITION_FOR_SYMBOL")
    return {
        "maintenance_allowed": len(reason_codes) == 0,
        "reason_codes": reason_codes,
        "execution_mode": status.get("execution_mode"),
    }
