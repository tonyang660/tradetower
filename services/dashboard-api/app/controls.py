from config import SCHEDULER_BASE_URL, TRADE_GUARDIAN_BASE_URL
from http_client import post_json


def set_scheduler_auto_loop(enabled: bool):
    payload, status_code, error = post_json(
        f"{SCHEDULER_BASE_URL}/controls/auto-loop",
        {"enabled": enabled},
        timeout=15,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return {
        "ok": True,
        "scheduler": payload,
    }, 200


def set_configuration_auto_loop(enabled: bool):
    result, status = set_scheduler_auto_loop(enabled)

    if status != 200:
        return result, status

    return {
        "ok": True,
        "auto_loop_enabled": enabled,
        "scheduler_response": result.get("scheduler"),
    }, 200


def set_manual_halt(account_id: int, enabled: bool):
    reason_code = "MANUAL_HALT" if enabled else "MANUAL_HALT_CLEARED"

    payload, status_code, error = post_json(
        f"{TRADE_GUARDIAN_BASE_URL}/guard/manual-halt",
        {
            "account_id": account_id,
            "enabled": enabled,
            "reason_code": reason_code,
        },
        timeout=15,
    )

    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    if status_code != 200:
        return {
            "ok": False,
            "error": payload,
        }, status_code or 500

    return {
        "ok": True,
        "account_id": account_id,
        "manual_halt": enabled,
        "trade_guardian_response": payload,
    }, 200
