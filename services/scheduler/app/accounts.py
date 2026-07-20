from __future__ import annotations

import os
from typing import Any

import requests

from config import ACCOUNT_ID

DASHBOARD_API_BASE_URL = os.getenv("DASHBOARD_API_BASE_URL", "http://dashboard-api:8080")
PHASE8_SCHEDULER_ACCOUNTS_VERSION = "phase8b_account_fanout"


def fetch_accounts() -> tuple[list[dict[str, Any]], str | None]:
    try:
        response = requests.get(f"{DASHBOARD_API_BASE_URL}/accounts", timeout=15)
        payload = response.json()
    except Exception as exc:
        return [], f"dashboard_accounts_fetch_failed: {exc}"

    if response.status_code != 200 or not payload.get("ok", False):
        return [], str(payload.get("error", payload))

    accounts = payload.get("accounts", [])
    if not isinstance(accounts, list):
        return [], "dashboard_accounts_invalid_payload"

    return accounts, None


def enabled_accounts() -> tuple[list[dict[str, Any]], str | None]:
    accounts, error = fetch_accounts()
    if error:
        return [], error
    return [account for account in accounts if account.get("enabled") is True], None


def enabled_account_ids(fallback_account_id: int | None = None) -> tuple[list[int], str | None]:
    accounts, error = enabled_accounts()
    fallback = int(fallback_account_id or ACCOUNT_ID)
    if error or not accounts:
        return [fallback], error
    return [int(account["account_id"]) for account in accounts]


def all_account_ids(fallback_account_id: int | None = None) -> tuple[list[int], str | None]:
    accounts, error = fetch_accounts()
    fallback = int(fallback_account_id or ACCOUNT_ID)
    if error or not accounts:
        return [fallback], error
    return [int(account["account_id"]) for account in accounts]


def account_ids_for_entry_work(fallback_account_id: int | None = None) -> tuple[list[int], str | None]:
    # New entries and pending entry retries are skipped for disabled accounts.
    return enabled_account_ids(fallback_account_id or ACCOUNT_ID)


def account_ids_for_exit_and_maintenance(fallback_account_id: int | None = None) -> tuple[list[int], str | None]:
    # Protective exits and maintenance keep running even when an account is disabled.
    return all_account_ids(fallback_account_id or ACCOUNT_ID)
