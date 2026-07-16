from __future__ import annotations

from typing import Any

EVALUATOR_EVENT_MODEL_VERSION = "phase7_step1_evaluator_event_model_v2"

EVENT_FAMILIES = {
    "cycle": ["cycle_started", "cycle_completed", "position_management_completed"],
    "signal": ["strategy_signal_generated", "strategy_trade_candidate", "strategy_observe_candidate"],
    "risk": ["risk_approved", "risk_rejected", "risk_adjusted"],
    "order": ["entry_order_created", "entry_order_pending", "protective_order_created", "protective_order_repriced"],
    "execution": ["entry_filled", "entry_pending", "tp1_filled", "tp2_filled", "tp3_filled", "stop_loss_filled"],
    "position": ["position_opened", "position_partially_closed", "position_closed", "tp_leg_closed"],
    "position_management": [
        "adaptive_stop_evaluated",
        "adaptive_stop_repriced",
        "near_tp_reversal_evaluated",
        "near_tp_stop_repriced",
        "regime_change_stop_evaluated",
        "regime_change_stop_repriced",
        "position_management_noop",
        "position_management_error",
    ],
    "trade": ["trade_finalized", "trade_summary_updated"],
    "account": ["equity_snapshot", "drawdown_updated", "risk_state_updated"],
}

CANONICAL_EVENT_FIELDS = [
    "event_version",
    "event_family",
    "event_type",
    "event_time",
    "ingested_at",
    "account_id",
    "symbol",
    "position_id",
    "order_id",
    "cycle_id",
    "source_service",
    "source_version",
    "strategy_name",
    "strategy_side",
    "regime",
    "execution_mode",
    "payload",
]

TP_LEG_EVENT_FIELDS = [
    "tp_level",
    "tp_ratio",
    "close_percent",
    "close_size",
    "remaining_size_before",
    "remaining_size_after",
    "fill_price",
    "realized_pnl",
    "fee_paid",
    "slippage_bps",
]

POSITION_MANAGEMENT_EVENT_FIELDS = [
    "module",
    "action",
    "reason_code",
    "old_stop",
    "new_stop",
    "proposed_stop",
    "is_noop",
    "management_key",
    "raw_result",
]

V1_TP_POLICY_MAP = {
    "base_ratios": {"tp1": 1.5, "tp2": 2.5, "tp3": 3.5},
    "close_percents": {"tp1": 50, "tp2": 30, "tp3": 20},
    "regime_ratio_multipliers": {
        "trending": 1.0,
        "strong_trend": 1.0,
        "Uptrend": 1.0,
        "Downtrend": 1.0,
        "high_volatility": 0.8,
        "choppy": 0.6,
        "low_volatility": 0.6,
        "mean_reversion_style": 0.6,
    },
    "effective_ratios": {
        "trend_following": {"tp1": 1.5, "tp2": 2.5, "tp3": 3.5},
        "high_volatility": {"tp1": 1.2, "tp2": 2.0, "tp3": 2.8},
        "mean_reversion_style": {"tp1": 0.9, "tp2": 1.5, "tp3": 2.1},
    },
    "note": (
        "v1 TP ratios are selected by regime. Mean-reversion is normally selected "
        "in choppy/low-volatility regimes, so it receives the 0.6 multiplier."
    ),
}

SOURCE_TO_CANONICAL_MAP = {
    "scheduler_cycle_summary": ["cycle_completed", "position_management_completed"],
    "paper_execution_report": ["entry_filled", "entry_pending", "tp1_filled", "tp2_filled", "tp3_filled", "stop_loss_filled"],
    "trade_guardian_position_events": ["position_opened", "position_partially_closed", "position_closed", "tp_leg_closed"],
    "position_management_summary": [
        "adaptive_stop_repriced",
        "near_tp_stop_repriced",
        "regime_change_stop_repriced",
        "position_management_noop",
        "position_management_error",
    ],
    "equity_snapshot": ["equity_snapshot", "drawdown_updated"],
}


def build_event_contract(*, event_family: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "event_version": EVALUATOR_EVENT_MODEL_VERSION,
        "event_family": event_family,
        "event_type": event_type,
        "required_fields": CANONICAL_EVENT_FIELDS,
        "payload": payload or {},
    }


def build_evaluator_event_model_contract() -> dict[str, Any]:
    return {
        "evaluator_event_model_version": EVALUATOR_EVENT_MODEL_VERSION,
        "event_families": EVENT_FAMILIES,
        "canonical_event_fields": CANONICAL_EVENT_FIELDS,
        "tp_leg_event_fields": TP_LEG_EVENT_FIELDS,
        "position_management_event_fields": POSITION_MANAGEMENT_EVENT_FIELDS,
        "v1_tp_policy_map": V1_TP_POLICY_MAP,
        "source_to_canonical_map": SOURCE_TO_CANONICAL_MAP,
        "does_not_change_runtime_ingestion_yet": True,
        "next_step": "Phase 7 Step 2 — Cycle summary ingestion V2",
    }
