from api_clients import (
    run_maintenance,
    submit_entry_to_paper_execution,
)


SUPPORTED_EXECUTION_MODES = {
    "paper",
    "shadow",
    "live",
    "close_only",
}


def execute_entry(execution_mode: str, payload: dict):
    mode = str(execution_mode or "").lower()

    if mode not in SUPPORTED_EXECUTION_MODES:
        return None, f"unsupported_execution_mode:{mode or 'missing'}"

    if mode == "paper":
        return submit_entry_to_paper_execution(payload)

    if mode == "close_only":
        return None, "entry_blocked_execution_mode_close_only"

    # Shadow and live routing are intentionally fail-closed until their
    # execution services are implemented.
    if mode == "shadow":
        return None, "shadow_execution_not_implemented"

    if mode == "live":
        return None, "live_execution_not_implemented"

    return None, f"unsupported_execution_mode:{mode}"


def execute_maintenance(
    execution_mode: str,
    account_id: int,
    symbol: str,
    force_market_stop_loss: bool = False,
):
    mode = str(execution_mode or "").lower()

    if mode not in SUPPORTED_EXECUTION_MODES:
        return None, f"unsupported_execution_mode:{mode or 'missing'}"

    if mode == "paper":
        return run_maintenance(
            account_id=account_id,
            symbol=symbol,
            force_market_stop_loss=force_market_stop_loss,
        )

    # Future live/close-only maintenance is event-driven from BloFin private
    # WebSocket plus REST reconciliation. The scheduler must not silently use
    # the paper simulator for a live account.
    if mode in ("shadow", "live", "close_only"):
        return {
            "ok": True,
            "action": "NO_SCHEDULER_MAINTENANCE",
            "execution_mode": mode,
        }, None

    return None, f"unsupported_execution_mode:{mode}"
