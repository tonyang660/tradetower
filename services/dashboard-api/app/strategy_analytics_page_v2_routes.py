from __future__ import annotations

from urllib.parse import parse_qs

from strategy_analytics_page_v2 import (
    STRATEGY_ANALYTICS_PAGE_V2_VERSION,
    get_strategy_analytics_page_v2,
)

STRATEGY_ANALYTICS_PAGE_V2_ROUTES = {
    "/dashboard/v2/strategy-analytics-page",
}


def _int_query(query: dict, key: str, default: int) -> int:
    return int(query.get(key, [str(default)])[0])


def handle_strategy_analytics_page_v2_get(handler, parsed) -> bool:
    if parsed.path not in STRATEGY_ANALYTICS_PAGE_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = _int_query(query, "account_id", 1)
    limit = _int_query(query, "limit", 500)
    cycle_limit = _int_query(query, "cycle_limit", 100)

    if parsed.path == "/dashboard/v2/strategy-analytics-page":
        handler._send_json(get_strategy_analytics_page_v2(account_id, limit, cycle_limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_strategy_analytics_page_v2_route",
        "strategy_analytics_page_v2_version": STRATEGY_ANALYTICS_PAGE_V2_VERSION,
    }, status=404)
    return True
