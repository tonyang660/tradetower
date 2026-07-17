from __future__ import annotations

from urllib.parse import parse_qs

from system_configuration_page_v2 import (
    SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
    get_configuration_page_v2,
    get_system_health_page_v2,
)

SYSTEM_CONFIGURATION_PAGE_V2_ROUTES = {
    "/dashboard/v2/system-health-page",
    "/dashboard/v2/configuration-page",
}


def _int_query(query: dict, key: str, default: int) -> int:
    return int(query.get(key, [str(default)])[0])


def handle_system_configuration_page_v2_get(handler, parsed) -> bool:
    if parsed.path not in SYSTEM_CONFIGURATION_PAGE_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)

    if parsed.path == "/dashboard/v2/system-health-page":
        account_id = _int_query(query, "account_id", 1)
        handler._send_json(get_system_health_page_v2(account_id))
        return True

    if parsed.path == "/dashboard/v2/configuration-page":
        handler._send_json(get_configuration_page_v2())
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_system_configuration_page_v2_route",
        "system_configuration_page_v2_version": SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
    }, status=404)
    return True
