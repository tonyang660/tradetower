from __future__ import annotations

from urllib.parse import parse_qs

from dashboard_aggregation_v2 import (
    DASHBOARD_AGGREGATION_V2_VERSION,
    get_dashboard_v2_live,
    get_dashboard_v2_overview,
    get_dashboard_v2_performance,
    get_dashboard_v2_snapshot,
    get_dashboard_v2_strategy,
)


DASHBOARD_AGGREGATION_V2_ROUTES = {
    "/dashboard/v2",
    "/dashboard/v2/overview",
    "/dashboard/v2/performance",
    "/dashboard/v2/strategy",
    "/dashboard/v2/live",
}


def _int_query(query: dict, key: str, default: int) -> int:
    return int(query.get(key, [str(default)])[0])


def handle_dashboard_aggregation_v2_get(handler, parsed) -> bool:
    if parsed.path not in DASHBOARD_AGGREGATION_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = _int_query(query, "account_id", 1)
    limit = _int_query(query, "limit", 500)
    cycle_limit = _int_query(query, "cycle_limit", 100)
    equity_limit = _int_query(query, "equity_limit", 10000)

    if parsed.path == "/dashboard/v2":
        handler._send_json(get_dashboard_v2_snapshot(account_id, limit, cycle_limit, equity_limit))
        return True

    if parsed.path == "/dashboard/v2/overview":
        handler._send_json(get_dashboard_v2_overview(account_id, limit, cycle_limit, equity_limit))
        return True

    if parsed.path == "/dashboard/v2/performance":
        handler._send_json(get_dashboard_v2_performance(account_id, limit, equity_limit))
        return True

    if parsed.path == "/dashboard/v2/strategy":
        handler._send_json(get_dashboard_v2_strategy(account_id, limit, cycle_limit))
        return True

    if parsed.path == "/dashboard/v2/live":
        handler._send_json(get_dashboard_v2_live(account_id, limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_dashboard_aggregation_v2_route",
        "dashboard_aggregation_v2_version": DASHBOARD_AGGREGATION_V2_VERSION,
    }, status=404)
    return True
