from __future__ import annotations

from typing import Any
import requests

from config import TRADE_GUARDIAN_BASE_URL

SCHEDULER_POSITION_MANAGEMENT_CLIENT_VERSION = "phase6_step11_scheduler_position_management_client"


def manage_trade_guardian_position(payload: dict[str, Any]):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/position/manage",
            json=payload,
            timeout=15,
        )
        response = r.json()
    except Exception as e:
        return None, f"trade_guardian_position_manage_failed: {str(e)}"

    if not response.get("ok", False):
        return response, response.get("error", "trade_guardian_position_manage_rejected")

    return response, None


def evaluate_trade_guardian_position(payload: dict[str, Any]):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/position/evaluate-management",
            json=payload,
            timeout=15,
        )
        response = r.json()
    except Exception as e:
        return None, f"trade_guardian_position_evaluate_failed: {str(e)}"

    if not response.get("ok", False):
        return response, response.get("error", "trade_guardian_position_evaluate_rejected")

    return response, None
