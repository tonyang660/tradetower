import os
from typing import Any
import requests

DASHBOARD_API_BASE_URL = os.getenv("DASHBOARD_API_BASE_URL", "http://dashboard-api:8080")
PHASE8_SCHEDULER_ACCOUNTS_VERSION = "phase8a_enabled_account_discovery"

def fetch_enabled_accounts() -> tuple[list[dict[str, Any]], str | None]:
    try:
        response = requests.get(f"{DASHBOARD_API_BASE_URL}/accounts", timeout=15)
        payload = response.json()
    except Exception as exc:
        return [], f"dashboard_accounts_fetch_failed: {exc}"
    if response.status_code != 200 or not payload.get("ok", False):
        return [], str(payload.get("error", payload))
    return [a for a in payload.get("accounts", []) if a.get("enabled") is True], None

def enabled_account_ids(fallback_account_id: int) -> tuple[list[int], str | None]:
    accounts, error = fetch_enabled_accounts()
    if error or not accounts:
        return [int(fallback_account_id)], error
    return [int(a["account_id"]) for a in accounts]
