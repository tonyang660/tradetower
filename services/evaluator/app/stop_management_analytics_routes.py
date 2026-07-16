from __future__ import annotations

from urllib.parse import parse_qs

from stop_management_analytics import (
    STOP_MANAGEMENT_ANALYTICS_VERSION,
    get_stop_management_analytics,
    get_stop_management_summary,
)

STOP_MANAGEMENT_ANALYTICS_ROUTES = {
    "/analytics/stop-management",
    "/analytics/stop-management/summary",
}


def handle_stop_management_analytics_get(handler, parsed) -> bool:
    if parsed.path not in STOP_MANAGEMENT_ANALYTICS_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = int(query.get("account_id", ["1"])[0])
    raw_limit = query.get("limit", [None])[0]
    limit = int(raw_limit) if raw_limit is not None else None

    if parsed.path == "/analytics/stop-management":
        handler._send_json(get_stop_management_analytics(account_id, limit))
        return True

    if parsed.path == "/analytics/stop-management/summary":
        handler._send_json(get_stop_management_summary(account_id, limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_stop_management_analytics_route",
        "stop_management_analytics_version": STOP_MANAGEMENT_ANALYTICS_VERSION,
    }, status=404)
    return True
