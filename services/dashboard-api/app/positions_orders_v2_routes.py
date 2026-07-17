from __future__ import annotations

from urllib.parse import parse_qs

from positions_orders_v2 import (
    POSITIONS_ORDERS_V2_VERSION,
    get_position_lifecycle_v2,
    get_positions_orders_v2,
)


POSITIONS_ORDERS_V2_ROUTES = {
    "/dashboard/v2/positions-orders",
    "/dashboard/v2/positions-orders/lifecycle",
}


def _int_query(query: dict, key: str, default: int) -> int:
    return int(query.get(key, [str(default)])[0])


def handle_positions_orders_v2_get(handler, parsed) -> bool:
    if parsed.path not in POSITIONS_ORDERS_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = _int_query(query, "account_id", 1)

    if parsed.path == "/dashboard/v2/positions-orders":
        recent_limit = _int_query(query, "recent_limit", 20)
        executed_limit = _int_query(query, "executed_limit", 50)
        lifecycle_limit = _int_query(query, "lifecycle_limit", 10)
        handler._send_json(get_positions_orders_v2(account_id, recent_limit, executed_limit, lifecycle_limit))
        return True

    if parsed.path == "/dashboard/v2/positions-orders/lifecycle":
        raw_position_id = query.get("position_id", [None])[0]
        if raw_position_id is None:
            handler._send_json({
                "ok": False,
                "error": "missing_position_id",
                "positions_orders_v2_version": POSITIONS_ORDERS_V2_VERSION,
            }, status=400)
            return True

        payload, status = get_position_lifecycle_v2(account_id, int(raw_position_id))
        handler._send_json(payload, status=status)
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_positions_orders_v2_route",
        "positions_orders_v2_version": POSITIONS_ORDERS_V2_VERSION,
    }, status=404)
    return True
