"""
Phase 6 Step 10 — route adapter for Trade Guardian main.py.

This keeps main.py edits small:

    from position_management_api import (
        position_management_health_payload,
        handle_position_management_post,
    )

In /health:
    **position_management_health_payload()

At the start of do_POST, after reading no body yet:
    if handle_position_management_post(self, self.path):
        return

The handler object must expose:
    self.headers
    self.rfile
    self._send_json(payload, status=...)
"""

from __future__ import annotations

import json

from adaptive_stop_manager import (
    apply_adaptive_stop_for_position,
    evaluate_adaptive_stop_for_position,
)
from near_tp_reversal_manager import (
    apply_near_tp_reversal_for_position,
    evaluate_near_tp_reversal_for_position,
)
from regime_change_stop_manager import (
    apply_regime_change_stop_for_position,
    evaluate_regime_change_stop_for_position,
)
from volatility_spike_stop_manager import (
    apply_volatility_spike_stop_for_position,
    evaluate_volatility_spike_stop_for_position,
)
from position_management_orchestrator import (
    apply_position_management,
    build_payload_kwargs,
    build_position_management_health_payload,
    evaluate_position_management,
)


POSITION_MANAGEMENT_POST_PATHS = {
    "/position/evaluate-adaptive-stop",
    "/position/manage-adaptive-stop",
    "/position/evaluate-near-tp-reversal",
    "/position/manage-near-tp-reversal",
    "/position/evaluate-regime-change-stop",
    "/position/manage-regime-change-stop",
    "/position/evaluate-volatility-spike-stop",
    "/position/manage-volatility-spike-stop",
    "/position/evaluate-management",
    "/position/manage",
}


def position_management_health_payload() -> dict:
    return build_position_management_health_payload()


def _read_json_payload(handler) -> dict:
    content_length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(content_length)
    return json.loads(raw.decode("utf-8")) if raw else {}


def _require_symbol(handler, payload: dict) -> str | None:
    symbol = payload.get("symbol")
    if not symbol:
        handler._send_json({
            "ok": False,
            "error": "missing_parameters",
            "required": ["symbol"],
        }, status=400)
        return None
    return str(symbol).upper()


def _require_fields(handler, payload: dict, fields: list[str]) -> bool:
    missing = [field for field in fields if payload.get(field) is None]
    if missing:
        handler._send_json({
            "ok": False,
            "error": "missing_parameters",
            "required": missing,
        }, status=400)
        return False
    return True


def _status_for(result: dict) -> int:
    return 200 if result.get("ok") else 400


def handle_position_management_post(handler, path: str) -> bool:
    if path not in POSITION_MANAGEMENT_POST_PATHS:
        return False

    try:
        payload = _read_json_payload(handler)
        account_id = int(payload.get("account_id", 1))
        symbol = _require_symbol(handler, payload)
        if symbol is None:
            return True

        if path == "/position/evaluate-adaptive-stop":
            result = evaluate_adaptive_stop_for_position(
                account_id=account_id,
                symbol=symbol,
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/manage-adaptive-stop":
            result = apply_adaptive_stop_for_position(
                account_id=account_id,
                symbol=symbol,
                dry_run=bool(payload.get("dry_run", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/evaluate-near-tp-reversal":
            if not _require_fields(handler, payload, ["current_price"]):
                return True

            result = evaluate_near_tp_reversal_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                previous_best_price=(
                    float(payload["previous_best_price"])
                    if payload.get("previous_best_price") is not None
                    else None
                ),
                near_tp_progress_threshold=float(payload.get("near_tp_progress_threshold", 0.92)),
                pullback_threshold_pct=float(payload.get("pullback_threshold_pct", 0.005)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/manage-near-tp-reversal":
            if not _require_fields(handler, payload, ["current_price"]):
                return True

            result = apply_near_tp_reversal_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                previous_best_price=(
                    float(payload["previous_best_price"])
                    if payload.get("previous_best_price") is not None
                    else None
                ),
                near_tp_progress_threshold=float(payload.get("near_tp_progress_threshold", 0.92)),
                pullback_threshold_pct=float(payload.get("pullback_threshold_pct", 0.005)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/evaluate-regime-change-stop":
            if not _require_fields(handler, payload, ["current_price", "entry_regime", "current_regime"]):
                return True

            result = evaluate_regime_change_stop_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                entry_regime=str(payload["entry_regime"]),
                current_regime=str(payload["current_regime"]),
                min_profit_r=float(payload.get("min_profit_r", 0.4)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0015)),
                already_triggered=bool(payload.get("already_triggered", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/manage-regime-change-stop":
            if not _require_fields(handler, payload, ["current_price", "entry_regime", "current_regime"]):
                return True

            result = apply_regime_change_stop_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                entry_regime=str(payload["entry_regime"]),
                current_regime=str(payload["current_regime"]),
                min_profit_r=float(payload.get("min_profit_r", 0.4)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0015)),
                already_triggered=bool(payload.get("already_triggered", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/evaluate-volatility-spike-stop":
            if not _require_fields(handler, payload, ["current_price", "entry_atr", "current_atr"]):
                return True

            result = evaluate_volatility_spike_stop_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                entry_atr=float(payload["entry_atr"]),
                current_atr=float(payload["current_atr"]),
                min_profit_r=float(payload.get("min_profit_r", 0.4)),
                spike_multiplier=float(payload.get("spike_multiplier", 1.6)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0015)),
                already_triggered=bool(payload.get("already_triggered", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/manage-volatility-spike-stop":
            if not _require_fields(handler, payload, ["current_price", "entry_atr", "current_atr"]):
                return True

            result = apply_volatility_spike_stop_for_position(
                account_id=account_id,
                symbol=symbol,
                current_price=float(payload["current_price"]),
                entry_atr=float(payload["entry_atr"]),
                current_atr=float(payload["current_atr"]),
                min_profit_r=float(payload.get("min_profit_r", 0.4)),
                spike_multiplier=float(payload.get("spike_multiplier", 1.6)),
                breakeven_buffer_pct=float(payload.get("breakeven_buffer_pct", 0.0015)),
                already_triggered=bool(payload.get("already_triggered", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/evaluate-management":
            kwargs = build_payload_kwargs(payload)
            result = evaluate_position_management(**kwargs)
            handler._send_json(result, status=_status_for(result))
            return True

        if path == "/position/manage":
            kwargs = build_payload_kwargs(payload)
            result = apply_position_management(
                **kwargs,
                dry_run=bool(payload.get("dry_run", False)),
            )
            handler._send_json(result, status=_status_for(result))
            return True

        return False

    except Exception as e:
        handler._send_json({
            "ok": False,
            "error": "position_management_request_failed",
            "details": str(e),
        }, status=400)
        return True
