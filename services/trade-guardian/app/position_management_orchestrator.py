"""
Phase 6 Step 10 — Trade Guardian position-management orchestrator.

This module centralizes Step 7-9 position-management calls:

1. Adaptive stop manager
   - after TP1: half-risk stop
   - after TP2: breakeven stop

2. Near-TP reversal manager
   - when current price and best favorable price are available

3. Regime-change stop manager
   - when current price, entry regime, and current regime are available

It is safe for automatic cycles because every stop manager only reprices when the
proposed stop improves protection.
"""

from __future__ import annotations

from typing import Any

from adaptive_stop_manager import (
    ADAPTIVE_STOP_MANAGER_VERSION,
    apply_adaptive_stop_for_position,
    build_adaptive_stop_manager_contract,
    evaluate_adaptive_stop_for_position,
)
from near_tp_reversal_manager import (
    build_near_tp_reversal_manager_contract,
    evaluate_near_tp_reversal_for_position,
    apply_near_tp_reversal_for_position,
)
from regime_change_stop_manager import (
    build_regime_change_stop_manager_contract,
    evaluate_regime_change_stop_for_position,
    apply_regime_change_stop_for_position,
)
from volatility_spike_stop_manager import (
    build_volatility_spike_stop_manager_contract,
    evaluate_volatility_spike_stop_for_position,
    apply_volatility_spike_stop_for_position,
)
from position_management_idempotency import (
    build_position_management_idempotency_contract,
    summarize_management_result,
)

POSITION_MANAGEMENT_ORCHESTRATOR_VERSION = "phase6_step10_position_management_integration"


def _has_value(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is not None


def build_position_management_health_payload() -> dict[str, Any]:
    return {
        "position_management_orchestrator_version": POSITION_MANAGEMENT_ORCHESTRATOR_VERSION,
        "adaptive_stop_manager_version": ADAPTIVE_STOP_MANAGER_VERSION,
        "adaptive_stop_manager": build_adaptive_stop_manager_contract(),
        "near_tp_reversal": build_near_tp_reversal_manager_contract(),
        "regime_change_stop": build_regime_change_stop_manager_contract(),
        "volatility_spike_stop": build_volatility_spike_stop_manager_contract(),
        "position_management_idempotency": build_position_management_idempotency_contract(),
    }


def evaluate_position_management(
    *,
    account_id: int,
    symbol: str,
    current_price: float | None = None,
    previous_best_price: float | None = None,
    entry_regime: str | None = None,
    current_regime: str | None = None,
    near_tp_progress_threshold: float = 0.92,
    pullback_threshold_pct: float = 0.005,
    near_tp_breakeven_buffer_pct: float = 0.0,
    regime_min_profit_r: float = 0.4,
    regime_breakeven_buffer_pct: float = 0.0015,
    regime_already_triggered: bool = False,
    entry_atr: float | None = None,
    current_atr: float | None = None,
    volatility_min_profit_r: float = 0.4,
    volatility_spike_multiplier: float = 1.6,
    volatility_breakeven_buffer_pct: float = 0.0015,
    volatility_already_triggered: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    adaptive = evaluate_adaptive_stop_for_position(
        account_id=account_id,
        symbol=symbol,
    )
    results.append(summarize_management_result(
        account_id=account_id,
        symbol=symbol,
        module="adaptive_stop",
        result=adaptive,
    ))

    if current_price is not None:
        near_tp = evaluate_near_tp_reversal_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            previous_best_price=previous_best_price,
            near_tp_progress_threshold=near_tp_progress_threshold,
            pullback_threshold_pct=pullback_threshold_pct,
            breakeven_buffer_pct=near_tp_breakeven_buffer_pct,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="near_tp_reversal",
            result=near_tp,
        ))

    if current_price is not None and entry_regime is not None and current_regime is not None:
        regime = evaluate_regime_change_stop_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            entry_regime=str(entry_regime),
            current_regime=str(current_regime),
            min_profit_r=regime_min_profit_r,
            breakeven_buffer_pct=regime_breakeven_buffer_pct,
            already_triggered=regime_already_triggered,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="regime_change_stop",
            result=regime,
        ))

    if current_price is not None and entry_atr is not None and current_atr is not None:
        volatility = evaluate_volatility_spike_stop_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            entry_atr=float(entry_atr),
            current_atr=float(current_atr),
            min_profit_r=volatility_min_profit_r,
            spike_multiplier=volatility_spike_multiplier,
            breakeven_buffer_pct=volatility_breakeven_buffer_pct,
            already_triggered=volatility_already_triggered,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="volatility_spike_stop",
            result=volatility,
        ))

    return {
        "ok": all(item.get("ok", False) for item in results),
        "position_management_orchestrator_version": POSITION_MANAGEMENT_ORCHESTRATOR_VERSION,
        "mode": "evaluate",
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "count": len(results),
        "results": results,
    }


def apply_position_management(
    *,
    account_id: int,
    symbol: str,
    current_price: float | None = None,
    previous_best_price: float | None = None,
    entry_regime: str | None = None,
    current_regime: str | None = None,
    near_tp_progress_threshold: float = 0.92,
    pullback_threshold_pct: float = 0.005,
    near_tp_breakeven_buffer_pct: float = 0.0,
    regime_min_profit_r: float = 0.4,
    regime_breakeven_buffer_pct: float = 0.0015,
    regime_already_triggered: bool = False,
    entry_atr: float | None = None,
    current_atr: float | None = None,
    volatility_min_profit_r: float = 0.4,
    volatility_spike_multiplier: float = 1.6,
    volatility_breakeven_buffer_pct: float = 0.0015,
    volatility_already_triggered: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    adaptive = apply_adaptive_stop_for_position(
        account_id=account_id,
        symbol=symbol,
        dry_run=dry_run,
    )
    results.append(summarize_management_result(
        account_id=account_id,
        symbol=symbol,
        module="adaptive_stop",
        result=adaptive,
    ))

    if current_price is not None:
        near_tp = apply_near_tp_reversal_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            previous_best_price=previous_best_price,
            near_tp_progress_threshold=near_tp_progress_threshold,
            pullback_threshold_pct=pullback_threshold_pct,
            breakeven_buffer_pct=near_tp_breakeven_buffer_pct,
            dry_run=dry_run,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="near_tp_reversal",
            result=near_tp,
        ))

    if current_price is not None and entry_regime is not None and current_regime is not None:
        regime = apply_regime_change_stop_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            entry_regime=str(entry_regime),
            current_regime=str(current_regime),
            min_profit_r=regime_min_profit_r,
            breakeven_buffer_pct=regime_breakeven_buffer_pct,
            already_triggered=regime_already_triggered,
            dry_run=dry_run,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="regime_change_stop",
            result=regime,
        ))

    if current_price is not None and entry_atr is not None and current_atr is not None:
        volatility = apply_volatility_spike_stop_for_position(
            account_id=account_id,
            symbol=symbol,
            current_price=float(current_price),
            entry_atr=float(entry_atr),
            current_atr=float(current_atr),
            min_profit_r=volatility_min_profit_r,
            spike_multiplier=volatility_spike_multiplier,
            breakeven_buffer_pct=volatility_breakeven_buffer_pct,
            already_triggered=volatility_already_triggered,
            dry_run=dry_run,
        )
        results.append(summarize_management_result(
            account_id=account_id,
            symbol=symbol,
            module="volatility_spike_stop",
            result=volatility,
        ))

    hard_failures = [
        item for item in results
        if not item.get("ok", False)
        and item.get("raw_result", {}).get("error") not in ("open_position_not_found",)
    ]

    return {
        "ok": len(hard_failures) == 0,
        "position_management_orchestrator_version": POSITION_MANAGEMENT_ORCHESTRATOR_VERSION,
        "mode": "apply",
        "dry_run": bool(dry_run),
        "account_id": int(account_id),
        "symbol": str(symbol).upper(),
        "count": len(results),
        "hard_failure_count": len(hard_failures),
        "results": results,
    }


def build_payload_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": int(payload.get("account_id", 1)),
        "symbol": str(payload["symbol"]).upper(),
        "current_price": (
            float(payload["current_price"])
            if payload.get("current_price") is not None
            else None
        ),
        "previous_best_price": (
            float(payload["previous_best_price"])
            if payload.get("previous_best_price") is not None
            else None
        ),
        "entry_regime": payload.get("entry_regime"),
        "current_regime": payload.get("current_regime"),
        "near_tp_progress_threshold": float(payload.get("near_tp_progress_threshold", 0.92)),
        "pullback_threshold_pct": float(payload.get("pullback_threshold_pct", 0.005)),
        "near_tp_breakeven_buffer_pct": float(payload.get("near_tp_breakeven_buffer_pct", 0.0)),
        "regime_min_profit_r": float(payload.get("regime_min_profit_r", payload.get("min_profit_r", 0.4))),
        "regime_breakeven_buffer_pct": float(payload.get("regime_breakeven_buffer_pct", payload.get("breakeven_buffer_pct", 0.0015))),
        "regime_already_triggered": bool(payload.get("regime_already_triggered", payload.get("already_triggered", False))),
        "entry_atr": (
            float(payload["entry_atr"])
            if payload.get("entry_atr") is not None
            else None
        ),
        "current_atr": (
            float(payload["current_atr"])
            if payload.get("current_atr") is not None
            else None
        ),
        "volatility_min_profit_r": float(payload.get("volatility_min_profit_r", payload.get("min_profit_r", 0.4))),
        "volatility_spike_multiplier": float(payload.get("volatility_spike_multiplier", payload.get("spike_multiplier", 1.6))),
        "volatility_breakeven_buffer_pct": float(payload.get("volatility_breakeven_buffer_pct", payload.get("breakeven_buffer_pct", 0.0015))),
        "volatility_already_triggered": bool(payload.get("volatility_already_triggered", payload.get("already_triggered", False))),
    }
