from __future__ import annotations

from typing import Any

from api_clients import fetch_latest_price
from position_best_price_state import (
    POSITION_BEST_PRICE_STATE_VERSION,
    prune_best_price_state,
    update_best_price_for_position,
)
from position_management_client import (
    SCHEDULER_POSITION_MANAGEMENT_CLIENT_VERSION,
    manage_trade_guardian_position,
)

SCHEDULER_POSITION_MANAGEMENT_VERSION = "phase6_step11_scheduler_position_management"


def _optional_regime_context(position: dict[str, Any]) -> dict[str, Any]:
    entry_regime = (
        position.get("entry_regime")
        or position.get("regime_at_entry")
        or position.get("regime")
    )
    current_regime = position.get("current_regime") or position.get("latest_regime")

    context: dict[str, Any] = {}
    if entry_regime is not None:
        context["entry_regime"] = entry_regime
    if current_regime is not None:
        context["current_regime"] = current_regime

    return context


def build_position_management_payload(
    *,
    account_id: int,
    position: dict[str, Any],
    current_price: float | None,
    best_price_record: dict[str, Any] | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = {
        "account_id": int(account_id),
        "symbol": str(position["symbol"]).upper(),
        "dry_run": bool(dry_run),
        "source": "scheduler_auto_cycle",
        "scheduler_position_management_version": SCHEDULER_POSITION_MANAGEMENT_VERSION,
    }

    if current_price is not None:
        payload["current_price"] = float(current_price)

    if best_price_record is not None:
        payload["previous_best_price"] = best_price_record.get("best_price")
        payload["best_price_context"] = best_price_record

    payload.update(_optional_regime_context(position))
    return payload


def run_position_management_for_open_positions(
    *,
    account_id: int,
    open_positions: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    summary = {
        "ok": True,
        "scheduler_position_management_version": SCHEDULER_POSITION_MANAGEMENT_VERSION,
        "scheduler_position_management_client_version": SCHEDULER_POSITION_MANAGEMENT_CLIENT_VERSION,
        "position_best_price_state_version": POSITION_BEST_PRICE_STATE_VERSION,
        "checked": 0,
        "actions_triggered": 0,
        "no_action": 0,
        "errors": 0,
        "skipped": 0,
        "results": [],
    }

    prune_best_price_state(open_positions, account_id)

    for position in open_positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            summary["skipped"] += 1
            continue

        current_price, price_error = fetch_latest_price(symbol)
        if price_error:
            summary["errors"] += 1
            summary["ok"] = False
            summary["results"].append({
                "symbol": symbol,
                "ok": False,
                "error": price_error,
                "stage": "fetch_latest_price",
            })
            continue

        best_price_record = update_best_price_for_position(
            account_id=account_id,
            position=position,
            current_price=float(current_price),
        )

        payload = build_position_management_payload(
            account_id=account_id,
            position=position,
            current_price=float(current_price),
            best_price_record=best_price_record,
            dry_run=dry_run,
        )

        result, error = manage_trade_guardian_position(payload)
        summary["checked"] += 1

        if error:
            summary["errors"] += 1
            summary["results"].append({
                "symbol": symbol,
                "ok": False,
                "error": error,
                "payload": payload,
                "result": result,
            })
            continue

        actions = [
            item.get("action")
            for item in result.get("results", [])
            if item.get("action") not in (None, "NO_ACTION", "NO_STOP_REPRICE")
        ]

        if actions:
            summary["actions_triggered"] += len(actions)
        else:
            summary["no_action"] += 1

        summary["results"].append({
            "symbol": symbol,
            "ok": True,
            "payload": payload,
            "result": result,
            "actions": actions,
        })

    return summary
