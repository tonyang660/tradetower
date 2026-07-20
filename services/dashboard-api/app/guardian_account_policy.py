from __future__ import annotations
from config import TRADE_GUARDIAN_BASE_URL
from http_client import get_json, post_json
PHASE9_DASHBOARD_GUARDIAN_ACCOUNT_MANAGER_VERSION = "phase9a_dashboard_guardian_account_manager_proxy"

def fetch_guardian_account_policy(account_id: int):
    payload, status_code, error = get_json(f"{TRADE_GUARDIAN_BASE_URL}/guard/account-policy", params={"account_id": account_id}, timeout=15)
    if error:
        return {"ok": False, "error": error}, 500
    return payload, status_code or 500

def update_guardian_account_policy(account_id: int, payload: dict):
    request_payload = dict(payload or {})
    request_payload["account_id"] = account_id
    result, status_code, error = post_json(f"{TRADE_GUARDIAN_BASE_URL}/guard/account-policy/update", request_payload, timeout=15)
    if error:
        return {"ok": False, "error": error}, 500
    return result, status_code or 500
