from __future__ import annotations

from urllib.parse import parse_qs

from performance_page_v2 import PERFORMANCE_PAGE_V2_VERSION, get_performance_page_v2

PERFORMANCE_PAGE_V2_ROUTES = {
    "/dashboard/v2/performance-page",
}


def _int_query(query: dict, key: str, default: int) -> int:
    return int(query.get(key, [str(default)])[0])


def handle_performance_page_v2_get(handler, parsed) -> bool:
    if parsed.path not in PERFORMANCE_PAGE_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = _int_query(query, "account_id", 1)
    limit = _int_query(query, "limit", 500)
    equity_limit = _int_query(query, "equity_limit", 10000)

    if parsed.path == "/dashboard/v2/performance-page":
        handler._send_json(get_performance_page_v2(account_id, limit, equity_limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_performance_page_v2_route",
        "performance_page_v2_version": PERFORMANCE_PAGE_V2_VERSION,
    }, status=404)
    return True
