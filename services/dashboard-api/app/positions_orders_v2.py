from __future__ import annotations

from typing import Any

from config import EVALUATOR_BASE_URL
from http_client import get_json
from time_utils import iso_now

POSITIONS_ORDERS_V2_VERSION = "phase7_step11_positions_orders_v2"


def _safe_get(
    source: str,
    path: str,
    params: dict[str, Any] | None = None,
    timeout: int = 20,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    payload, status_code, error = get_json(
        f"{EVALUATOR_BASE_URL}{path}",
        params=params or {},
        timeout=timeout,
    )

    if error:
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": error,
        }

    if status_code != 200:
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": payload,
        }

    if not isinstance(payload, dict):
        return None, {
            "source": source,
            "path": path,
            "status_code": status_code,
            "error": "non_dict_payload",
        }

    return payload, None


def _items(payload: dict[str, Any] | None, primary: str = "items", alternate: str | None = None) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    value = payload.get(primary)
    if isinstance(value, list):
        return value
    if alternate:
        value = payload.get(alternate)
        if isinstance(value, list):
            return value
    return []


def _service_block(payload: dict[str, Any] | None, error: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "data": payload if error is None else None,
        "error": error,
    }


def get_positions_orders_v2(account_id: int, recent_limit: int = 20, executed_limit: int = 50, lifecycle_limit: int = 10) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    open_payload, open_error = _safe_get(
        "open_positions",
        "/positions/open",
        {
            "account_id": account_id,
            "refresh": "true",
        },
        timeout=30,
    )
    if open_error:
        errors.append(open_error)

    recent_payload, recent_error = _safe_get(
        "recent_positions",
        "/positions/recent",
        {
            "account_id": account_id,
            "limit": recent_limit,
        },
        timeout=30,
    )
    if recent_error:
        errors.append(recent_error)

    open_orders_payload, open_orders_error = _safe_get(
        "open_orders",
        "/orders/open",
        {"account_id": account_id},
        timeout=20,
    )
    if open_orders_error:
        errors.append(open_orders_error)

    executed_payload, executed_error = _safe_get(
        "executed_orders",
        "/orders/executed",
        {
            "account_id": account_id,
            "limit": executed_limit,
        },
        timeout=30,
    )
    if executed_error:
        errors.append(executed_error)

    lifecycles_payload, lifecycles_error = _safe_get(
        "recent_position_lifecycles",
        "/positions/lifecycles/recent",
        {
            "account_id": account_id,
            "limit": lifecycle_limit,
        },
        timeout=30,
    )
    if lifecycles_error:
        # Lifecycle is additive. Do not make the whole page fail because this
        # route is unavailable before the evaluator Step 3 patch is applied.
        errors.append(lifecycles_error)

    open_positions = _items(open_payload, "positions", "items")
    recent_positions = _items(recent_payload)
    open_orders = _items(open_orders_payload)
    executed_orders = _items(executed_payload)
    recent_lifecycles = _items(lifecycles_payload)

    return {
        "ok": len(errors) == 0,
        "partial": len(errors) > 0,
        "positions_orders_v2_version": POSITIONS_ORDERS_V2_VERSION,
        "account_id": account_id,
        "generated_at": iso_now(),
        "open_positions": open_positions,
        "recent_closed_positions": recent_positions,
        "open_orders": open_orders,
        "executed_orders": executed_orders,
        "recent_position_lifecycles": recent_lifecycles,
        "counts": {
            "open_positions": len(open_positions),
            "recent_closed_positions": len(recent_positions),
            "open_orders": len(open_orders),
            "executed_orders": len(executed_orders),
            "recent_position_lifecycles": len(recent_lifecycles),
        },
        "raw": {
            "open_positions": open_payload,
            "recent_positions": recent_payload,
            "open_orders": open_orders_payload,
            "executed_orders": executed_payload,
            "recent_position_lifecycles": lifecycles_payload,
        },
        "services": {
            "open_positions": _service_block(open_payload, open_error),
            "recent_positions": _service_block(recent_payload, recent_error),
            "open_orders": _service_block(open_orders_payload, open_orders_error),
            "executed_orders": _service_block(executed_payload, executed_error),
            "recent_position_lifecycles": _service_block(lifecycles_payload, lifecycles_error),
        },
        "errors": errors,
    }


def get_position_lifecycle_v2(account_id: int, position_id: int) -> tuple[dict[str, Any], int]:
    payload, error = _safe_get(
        "position_lifecycle",
        "/positions/lifecycle",
        {
            "account_id": account_id,
            "position_id": position_id,
        },
        timeout=30,
    )

    if error:
        return {
            "ok": False,
            "positions_orders_v2_version": POSITIONS_ORDERS_V2_VERSION,
            "account_id": account_id,
            "position_id": position_id,
            "generated_at": iso_now(),
            "error": error,
        }, int(error.get("status_code") or 500)

    return {
        "ok": True,
        "positions_orders_v2_version": POSITIONS_ORDERS_V2_VERSION,
        "account_id": account_id,
        "position_id": position_id,
        "generated_at": iso_now(),
        "lifecycle": payload,
    }, 200
