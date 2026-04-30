import requests

from config import FEATURE_FACTORY_BASE_URL


def fetch_snapshot(symbol: str):
    try:
        r = requests.get(
            f"{FEATURE_FACTORY_BASE_URL}/snapshot",
            params={"symbol": symbol},
            timeout=20
        )
        payload = r.json()
    except Exception as e:
        return None, f"feature_factory_request_failed: {str(e)}"

    if r.status_code != 200:
        return None, payload.get("error", "feature_factory_error")

    if payload.get("schema_version") != "market_snapshot_v2":
        return None, "unexpected_snapshot_schema_version"

    return payload, None
