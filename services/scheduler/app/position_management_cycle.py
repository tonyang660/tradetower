from __future__ import annotations

from typing import Any

from api_clients import fetch_latest_price, fetch_market_snapshot
from position_best_price_state import (
    POSITION_BEST_PRICE_STATE_VERSION,
    prune_best_price_state,
    update_best_price_for_position,
)
from position_management_client import (
    SCHEDULER_POSITION_MANAGEMENT_CLIENT_VERSION,
    manage_trade_guardian_position,
)

SCHEDULER_POSITION_MANAGEMENT_VERSION = "phase7_6c_scheduler_position_management_atr_context"
DEFAULT_ENTRY_ATR_FROM_RISK_MULTIPLIER = 2.5


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        result = float(value)
    except Exception:
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _dig(payload: dict[str, Any] | None, path: list[str], default: Any = None) -> Any:
    current: Any = payload or {}
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _optional_regime_context(position: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    entry_regime = position.get("entry_regime") or position.get("regime_at_entry") or position.get("regime")
    current_regime = (
        position.get("current_regime")
        or position.get("latest_regime")
        or _dig(snapshot, ["multi_timeframe_context", "regime_context", "primary_regime"])
        or _dig(snapshot, ["timeframes", "15m", "regime_inputs", "v1_regime"])
    )

    context: dict[str, Any] = {}
    if entry_regime is not None:
        context["entry_regime"] = entry_regime
    if current_regime is not None:
        context["current_regime"] = current_regime
    return context


def extract_current_atr_from_snapshot(snapshot: dict[str, Any] | None) -> float | None:
    if not isinstance(snapshot, dict):
        return None

    for path in (
        ["timeframes", "15m", "indicators", "atr_14"],
        ["timeframes", "15m", "indicators", "atr"],
        ["timeframes", "15m", "volatility", "atr"],
        ["timeframes", "5m", "indicators", "atr_14"],
        ["timeframes", "5m", "indicators", "atr"],
        ["timeframes", "5m", "volatility", "atr"],
    ):
        value = _safe_float(_dig(snapshot, path), None)
        if value is not None and value > 0:
            return value
    return None


def extract_entry_atr_from_position(position: dict[str, Any]) -> float | None:
    for key in ("entry_atr", "atr_at_entry", "opening_atr", "initial_atr"):
        value = _safe_float(position.get(key), None)
        if value is not None and value > 0:
            return value

    original_size = _safe_float(position.get("original_size") or position.get("size"), None)
    risk_amount = _safe_float(position.get("risk_amount"), None)
    if original_size is not None and original_size > 0 and risk_amount is not None and risk_amount > 0:
        risk_per_unit = risk_amount / original_size
        estimated = risk_per_unit / DEFAULT_ENTRY_ATR_FROM_RISK_MULTIPLIER
        if estimated > 0:
            return round(estimated, 8)

    entry = _safe_float(position.get("entry_price"), None)
    stop = _safe_float(position.get("stop_loss"), None)
    if entry is not None and stop is not None and entry > 0 and stop > 0:
        estimated = abs(entry - stop) / DEFAULT_ENTRY_ATR_FROM_RISK_MULTIPLIER
        if estimated > 0:
            return round(estimated, 8)

    return None


def build_volatility_context(position: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    entry_atr = extract_entry_atr_from_position(position)
    current_atr = extract_current_atr_from_snapshot(snapshot)

    context: dict[str, Any] = {}
    if entry_atr is not None and entry_atr > 0:
        context["entry_atr"] = float(entry_atr)
    if current_atr is not None and current_atr > 0:
        context["current_atr"] = float(current_atr)

    if entry_atr is not None and entry_atr > 0 and current_atr is not None and current_atr > 0:
        context["volatility_context"] = {
            "entry_atr": float(entry_atr),
            "current_atr": float(current_atr),
            "atr_ratio_vs_entry": round(float(current_atr) / float(entry_atr), 8),
            "entry_atr_source": (
                "position_field"
                if any(position.get(key) is not None for key in ("entry_atr", "atr_at_entry", "opening_atr", "initial_atr"))
                else "estimated_from_original_risk_per_unit"
            ),
            "current_atr_source": "feature_factory_snapshot_primary_15m",
            "volatility_spike_multiplier": 1.6,
        }

    return context


def build_position_management_payload(
    *,
    account_id: int,
    position: dict[str, Any],
    current_price: float | None,
    best_price_record: dict[str, Any] | None,
    snapshot: dict[str, Any] | None = None,
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

    payload.update(_optional_regime_context(position, snapshot))
    payload.update(build_volatility_context(position, snapshot))
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
        "atr_context_attached": 0,
        "atr_context_missing": 0,
        "snapshot_errors": 0,
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
            summary["results"].append({"symbol": symbol, "ok": False, "error": price_error, "stage": "fetch_latest_price"})
            continue

        snapshot, snapshot_error = fetch_market_snapshot(symbol)
        if snapshot_error:
            summary["snapshot_errors"] += 1
            snapshot = None

        best_price_record = update_best_price_for_position(account_id=account_id, position=position, current_price=float(current_price))

        payload = build_position_management_payload(
            account_id=account_id,
            position=position,
            current_price=float(current_price),
            best_price_record=best_price_record,
            snapshot=snapshot,
            dry_run=dry_run,
        )

        if payload.get("entry_atr") is not None and payload.get("current_atr") is not None:
            summary["atr_context_attached"] += 1
        else:
            summary["atr_context_missing"] += 1

        result, error = manage_trade_guardian_position(payload)
        summary["checked"] += 1

        if error:
            summary["errors"] += 1
            summary["results"].append({"symbol": symbol, "ok": False, "error": error, "payload": payload, "snapshot_error": snapshot_error, "result": result})
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

        summary["results"].append({"symbol": symbol, "ok": True, "payload": payload, "snapshot_error": snapshot_error, "result": result, "actions": actions})

    return summary
