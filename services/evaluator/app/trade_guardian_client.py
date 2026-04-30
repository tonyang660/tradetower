import requests

from config import TRADE_GUARDIAN_BASE_URL


def fetch_trade_guardian_status(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/status",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_status_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_status_failed")

    return payload, None


def fetch_trade_guardian_open_positions(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/positions/open",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_open_positions_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_open_positions_failed")

    return payload.get("positions", []), None


def fetch_trade_guardian_open_orders(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/orders/open",
            params={"account_id": account_id},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_open_orders_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_open_orders_failed")

    return payload.get("items", []), None


def refresh_trade_guardian_mark_to_market(account_id: int):
    try:
        r = requests.post(
            f"{TRADE_GUARDIAN_BASE_URL}/mark-to-market/refresh",
            json={"account_id": account_id},
            timeout=15,
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_mark_to_market_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_mark_to_market_failed")

    return payload, None
