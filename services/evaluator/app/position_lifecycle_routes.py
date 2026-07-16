from __future__ import annotations

from urllib.parse import parse_qs

from position_lifecycle import (
    POSITION_LIFECYCLE_VERSION,
    build_position_lifecycle,
    build_recent_position_lifecycles,
)

POSITION_LIFECYCLE_ROUTES = {
    "/positions/lifecycle",
    "/positions/lifecycles/recent",
}


def handle_position_lifecycle_get(handler, parsed) -> bool:
    if parsed.path not in POSITION_LIFECYCLE_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = int(query.get("account_id", ["1"])[0])

    if parsed.path == "/positions/lifecycle":
        raw_position_id = query.get("position_id", [None])[0]
        if raw_position_id is None:
            handler._send_json({
                "ok": False,
                "error": "missing_position_id",
                "position_lifecycle_version": POSITION_LIFECYCLE_VERSION,
            }, status=400)
            return True

        payload = build_position_lifecycle(account_id, int(raw_position_id))
        handler._send_json(payload, status=200 if payload.get("ok") else 404)
        return True

    if parsed.path == "/positions/lifecycles/recent":
        limit = int(query.get("limit", ["10"])[0])
        payload = build_recent_position_lifecycles(account_id, limit)
        handler._send_json(payload)
        return True

    return False
