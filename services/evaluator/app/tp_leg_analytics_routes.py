from __future__ import annotations

from urllib.parse import parse_qs

from tp_leg_analytics import (
    TP_LEG_ANALYTICS_VERSION,
    get_tp_leg_analytics,
    get_tp_progression,
)

TP_LEG_ANALYTICS_ROUTES = {
    "/analytics/tp-legs",
    "/analytics/tp-progression",
}


def handle_tp_leg_analytics_get(handler, parsed) -> bool:
    if parsed.path not in TP_LEG_ANALYTICS_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = int(query.get("account_id", ["1"])[0])
    raw_limit = query.get("limit", [None])[0]
    limit = int(raw_limit) if raw_limit is not None else None

    if parsed.path == "/analytics/tp-legs":
        handler._send_json(get_tp_leg_analytics(account_id, limit))
        return True

    if parsed.path == "/analytics/tp-progression":
        handler._send_json(get_tp_progression(account_id, limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_tp_leg_analytics_route",
        "tp_leg_analytics_version": TP_LEG_ANALYTICS_VERSION,
    }, status=404)
    return True
