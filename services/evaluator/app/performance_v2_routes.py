from __future__ import annotations

from urllib.parse import parse_qs

from performance_v2 import (
    PERFORMANCE_V2_VERSION,
    get_performance_v2,
    get_performance_v2_equity,
    get_performance_v2_positions,
    get_performance_v2_summary,
)


PERFORMANCE_V2_ROUTES = {
    "/performance/v2",
    "/performance/v2/summary",
    "/performance/v2/positions",
    "/performance/v2/equity",
}


def handle_performance_v2_get(handler, parsed) -> bool:
    if parsed.path not in PERFORMANCE_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = int(query.get("account_id", ["1"])[0])

    raw_limit = query.get("limit", [None])[0]
    limit = int(raw_limit) if raw_limit is not None else None

    equity_limit = int(query.get("equity_limit", ["1000"])[0])

    if parsed.path == "/performance/v2":
        handler._send_json(get_performance_v2(account_id, limit, equity_limit))
        return True

    if parsed.path == "/performance/v2/summary":
        handler._send_json(get_performance_v2_summary(account_id, limit))
        return True

    if parsed.path == "/performance/v2/positions":
        handler._send_json(get_performance_v2_positions(account_id, limit))
        return True

    if parsed.path == "/performance/v2/equity":
        handler._send_json(get_performance_v2_equity(account_id, equity_limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_performance_v2_route",
        "performance_v2_version": PERFORMANCE_V2_VERSION,
    }, status=404)
    return True
