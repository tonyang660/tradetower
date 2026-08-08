from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DEFAULT_MAX_CYCLES, DEFAULT_RISK_PER_TRADE_PCT, DEFAULT_SLIPPAGE_BPS, DEFAULT_STARTING_CAPITAL
from strategies.registry import build_strategy
from strategies.base import StrategyContext
from strategies.validation import validate_strategy_run_config
from db import get_conn
from historical_feed import build_historical_feed, parse_time
from market_snapshot import MarketSnapshotBuilder
from execution_timeline import normalize_execution_timeline_config, ensure_timeframes_for_timeline, virtual_execution_slots
from order_lifecycle import build_instant_fill_lifecycle, phase18_lifecycle_contract
from execution_fill_model import simulate_market_entry_fill, simulate_market_exit_fill, fill_model_contract
from entry_order_simulator import build_pending_limit_entry_order, evaluate_pending_entry_order, entry_order_model_contract
from protective_order_simulator import reprice_levels_to_actual_entry, build_protective_orders_for_position, protective_order_model_contract
from partial_tp_simulator import next_triggered_tp, partial_tp_size, realized_gross_for_exit, partial_tp_model_contract
from stop_loss_simulator import evaluate_stop_loss_order, stop_loss_model_contract
from secondary_stop_simulator import initialize_sl2_state, build_sl2_order_payload, mark_sl2_activated, sl2_touched, sl2_model_contract
from adaptive_stop_simulator import build_adaptive_stop_update, adaptive_stop_model_contract
from regime_change_exit_simulator import evaluate_regime_change_exit, regime_change_model_contract
from volatility_spike_exit_simulator import atr_from_rows, evaluate_volatility_spike_exit, volatility_spike_model_contract
from position_lifecycle_ledger import ensure_position_lifecycle_table, lifecycle_ledger_contract, record_position_event
from near_tp_reversal_simulator import evaluate_near_tp_reversal

from fee_model import FeeModel
from guardian_risk import GuardianPolicy, HistoricalGuardianState, evaluate_entry_guard
from production_risk import dynamic_risk_pct, evaluate_production_risk


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _compact_cycle_decision_debug(debug: dict[str, Any] | None) -> dict[str, Any]:
    """Keep routine cycle logs useful without persisting full candle snapshots."""
    debug = debug or {}
    signal = debug.get("strategy_signal", {}) or {}
    candidate = debug.get("candidate_filter_context", {}) or {}
    market_snapshot = debug.get("market_snapshot_v2", {}) or {}
    snapshot_meta = market_snapshot.get("snapshot_meta", {}) or {}
    data_quality = market_snapshot.get("data_quality", {}) or {}
    return {
        "production_parity_version": debug.get("production_parity_version"),
        "snapshot": {
            "schema_version": market_snapshot.get("schema_version"),
            "timestamp": market_snapshot.get("snapshot_timestamp"),
            "feature_factory_version": snapshot_meta.get("feature_factory_version"),
            "adapter_version": snapshot_meta.get("backtest_adapter_version"),
            "data_quality_healthy": data_quality.get("healthy"),
        },
        "candidate": {
            "selected": bool(candidate),
            "score": candidate.get("candidate_score"),
            "tier": candidate.get("candidate_tier"),
            "bias": candidate.get("candidate_bias"),
            "reason_tags": candidate.get("reason_tags", []),
        },
        "strategy_signal": {
            "decision": signal.get("v2_decision", signal.get("decision")),
            "side": signal.get("decision_side"),
            "score": signal.get("score"),
            "confidence": signal.get("confidence"),
            "regime": signal.get("regime"),
            "selected_strategy": signal.get("selected_strategy"),
            "reason": signal.get("reason"),
            "reason_tags": signal.get("reason_tags", []),
            "adapter_version": signal.get("backtest_adapter_version"),
        },
    }



def _normalize_backtest_timeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Force production-parity backtest clocking.

    Strategy roles remain:
      entry   = 5m
      primary = 15m
      context = 1h
      htf     = 4h

    The main backtest decision/cycle clock must be 5m, while the order
    lifecycle uses logical 1m slots on top of 5m execution data.
    """
    normalized = dict(payload or {})
    normalized["cycle_timeframe"] = "5m"
    normalized["decision_timeframe"] = "5m"
    normalized["execution_timeframe"] = "1m"
    normalized["execution_data_timeframe"] = "5m"

    requested_timeframes = normalized.get("timeframes") or ["5m", "15m", "1h", "4h"]
    if isinstance(requested_timeframes, str):
        requested_timeframes = [requested_timeframes]

    required_timeframes = ["5m", "15m", "1h", "4h"]
    ordered: list[str] = []
    for timeframe in required_timeframes + [str(tf) for tf in requested_timeframes]:
        if timeframe not in ordered:
            ordered.append(timeframe)
    normalized["timeframes"] = ordered
    return normalized


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_backtest_timeline_payload(payload)
    symbols = payload.get("symbols") or ["BTCUSDT", "ETHUSDT"]
    if isinstance(symbols, str):
        symbols = [symbols]

    cycle_timeframe = str(payload.get("cycle_timeframe") or payload.get("decision_timeframe") or "5m")
    timeframes = payload.get("timeframes") or [cycle_timeframe, "15m", "1h", "4h"]
    if isinstance(timeframes, str):
        timeframes = [timeframes]

    timeline = normalize_execution_timeline_config(
        payload,
        existing_timeframes=[str(t) for t in timeframes],
        cycle_timeframe=cycle_timeframe,
    )
    timeframes = ensure_timeframes_for_timeline([str(t) for t in timeframes], timeline)

    return {
        "strategy_name": payload.get("strategy_name", "tradetower_baseline_v1"),
        "strategy_version": payload.get("strategy_version", "1.0.0" if payload.get("strategy_name", "tradetower_baseline_v1") == "tradetower_baseline_v1" else "0.1.0"),
        "symbols": [str(s).upper().replace("/", "").replace("-", "") for s in symbols],
        "timeframes": [str(t) for t in timeframes],
        "cycle_timeframe": timeline.decision_timeframe,
        "decision_timeframe": timeline.decision_timeframe,
        "execution_timeframe": timeline.execution_timeframe,
        "execution_data_timeframe": timeline.execution_data_timeframe,
        "feature_timeframes": timeline.feature_timeframes,
        "virtual_execution": timeline.virtual_execution,
        "virtual_execution_steps_per_decision": timeline.virtual_execution_steps_per_decision,
        "execution_timeline": timeline.to_dict(),
        "timeout_exits_enabled": False,
        "start_time": parse_time(payload.get("start_time"), datetime(2024, 1, 1, tzinfo=timezone.utc)),
        "end_time": parse_time(payload.get("end_time"), None) if payload.get("end_time") else None,
        "starting_capital": float(payload.get("starting_capital", DEFAULT_STARTING_CAPITAL)),
        "max_cycles": int(payload.get("max_cycles", DEFAULT_MAX_CYCLES)),
        "risk_per_trade_pct": float(payload.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT)),
        "fee_bps_override": float(payload["fee_bps"]) if "fee_bps" in payload else None,
        "maker_fee_bps": float(payload.get("maker_fee_bps", 2.0)),
        "taker_fee_bps": float(payload.get("taker_fee_bps", 6.0)),
        "limit_order_fill_ratio": 1.0,
        "slippage_bps": float(payload.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)),
        "spread_bps": float(payload.get("spread_bps", 0.0)),
        "entry_slippage_bps": float(payload.get("entry_slippage_bps", payload.get("slippage_bps", DEFAULT_SLIPPAGE_BPS))),
        "exit_slippage_bps": float(payload.get("exit_slippage_bps", payload.get("slippage_bps", DEFAULT_SLIPPAGE_BPS))),
        "market_fill_ratio": float(payload.get("market_fill_ratio", 1.0)),
        "partial_fill_enabled": False,
        "entry_order_preference": str(payload.get("entry_order_preference", "limit")),
        "entry_limit_max_wait_attempts": int(payload.get("entry_limit_max_wait_attempts", payload.get("entry_limit_max_wait_cycles", 15))),
        "entry_limit_max_wait_cycles": int(payload.get("entry_limit_max_wait_cycles", 15)),
        "entry_market_fallback_enabled": bool(payload.get("entry_market_fallback_enabled", True)),
        "protective_orders_enabled": bool(payload.get("protective_orders_enabled", True)),
        "tp1_close_pct": float(payload.get("tp1_close_pct", 50.0)),
        "tp2_close_pct": float(payload.get("tp2_close_pct", 30.0)),
        "tp3_close_pct": float(payload.get("tp3_close_pct", 20.0)),
        "protective_stop_order_type": str(payload.get("protective_stop_order_type", "protective_limit")),
        "take_profit_order_type": str(payload.get("take_profit_order_type", "limit_exit")),
        "partial_tp_enabled": bool(payload.get("partial_tp_enabled", True)),
        "stop_reprice_buffer_bps": float(payload.get("stop_reprice_buffer_bps", 10.0)),
        "stop_limit_max_reprice_attempts": int(payload.get("stop_limit_max_reprice_attempts", 3)),
        "sl2_enabled": bool(payload.get("sl2_enabled", True)),
        "sl2_default_close_pct": float(payload.get("sl2_default_close_pct", 50.0)),
        "adaptive_stop_enabled": bool(payload.get("adaptive_stop_enabled", True)),
        "regime_change_exit_enabled": bool(payload.get("regime_change_exit_enabled", True)),
        "regime_change_sl2_close_pct": float(payload.get("regime_change_sl2_close_pct", 50.0)),
        "regime_change_require_profit": bool(payload.get("regime_change_require_profit", True)),
        "regime_change_min_profit_r": float(payload.get("regime_change_min_profit_r", 0.4)),
        "regime_change_breakeven_buffer_pct": float(payload.get("regime_change_breakeven_buffer_pct", 0.0015)),
        "volatility_spike_exit_enabled": bool(payload.get("volatility_spike_exit_enabled", True)),
        "volatility_spike_min_profit_r": float(payload.get("volatility_spike_min_profit_r", 0.4)),
        "volatility_spike_multiplier": float(payload.get("volatility_spike_multiplier", 1.6)),
        "volatility_spike_breakeven_buffer_pct": float(payload.get("volatility_spike_breakeven_buffer_pct", 0.0015)),
        "volatility_spike_sl2_close_pct": float(payload.get("volatility_spike_sl2_close_pct", 50.0)),
        "volatility_spike_atr_period": int(payload.get("volatility_spike_atr_period", 14)),
        "adaptive_stop_after_tp1_enabled": bool(payload.get("adaptive_stop_after_tp1_enabled", True)),
        "adaptive_stop_after_tp2_enabled": bool(payload.get("adaptive_stop_after_tp2_enabled", True)),
        "adaptive_stop_breakeven_buffer_bps": float(payload.get("adaptive_stop_breakeven_buffer_bps", 2.0)),
        "near_tp_reversal_enabled": bool(payload.get("near_tp_reversal_enabled", True)),
        "near_tp_progress_threshold": float(payload.get("near_tp_progress_threshold", 0.92)),
        "near_tp_pullback_threshold_pct": float(payload.get("near_tp_pullback_threshold_pct", 0.005)),
        "near_tp_breakeven_buffer_pct": float(payload.get("near_tp_breakeven_buffer_pct", 0.0)),
        "data_mode": payload.get("data_mode", "phase14b_sample_historical_feed"),
        "dataset_id": int(payload.get("dataset_id", 0) or 0),
        "execution_model": payload.get("execution_model", "phase18_virtual_1m_order_lifecycle"),
        "preflight_strict": bool(payload.get("preflight_strict", True)),
        "warmup_required_bars": int(payload.get("warmup_required_bars", 8)),
        "cycle_decision_log_interval": int(payload.get("cycle_decision_log_interval", 25)),
        "backtest_feature_workers": max(1, min(8, int(payload.get("backtest_feature_workers", 1) or 1))),
        "strategy_validation_strict_timeframes": bool(payload.get("strategy_validation_strict_timeframes", False)),
        "guardian_account_enabled": bool(payload.get("guardian_account_enabled", True)),
        "guardian_account_active": bool(payload.get("guardian_account_active", True)),
        "guardian_trading_enabled": bool(payload.get("guardian_trading_enabled", True)),
        "guardian_manual_halt": bool(payload.get("guardian_manual_halt", False)),
        "guardian_read_only_mode": bool(payload.get("guardian_read_only_mode", False)),
        "guardian_maintenance_only_mode": bool(payload.get("guardian_maintenance_only_mode", False)),
        "guardian_max_concurrent_positions": int(payload.get("guardian_max_concurrent_positions", 5)),
        "guardian_max_account_exposure_pct": float(payload.get("guardian_max_account_exposure_pct", 80.0)),
        "guardian_max_position_leverage": float(payload.get("guardian_max_position_leverage", payload.get("guardian_max_leverage", 15.0))),
        "guardian_account_max_notional_multiplier": float(payload.get("guardian_account_max_notional_multiplier", payload.get("guardian_account_exposure_multiplier", 10.0))),
        "guardian_daily_loss_limit_pct": float(payload.get("guardian_daily_loss_limit_pct", 3.0)),
        "guardian_weekly_loss_limit_pct": float(payload.get("guardian_weekly_loss_limit_pct", 6.0)),
        "guardian_max_consecutive_losses": int(payload.get("guardian_max_consecutive_losses", 3)),
        "guardian_consecutive_loss_cooldown_hours": int(payload.get("guardian_consecutive_loss_cooldown_hours", 4)),
        "risk_max_risk_pct": float(payload.get("risk_max_risk_pct", payload.get("risk_per_trade_pct", 1.0))),
        "risk_max_leverage": float(payload.get("risk_max_leverage", 15.0)),
        "risk_min_liquidation_buffer_pct": float(payload.get("risk_min_liquidation_buffer_pct", 0.35)),
        "risk_min_notional_pct_of_max_deployable": float(payload.get("risk_min_notional_pct_of_max_deployable", 1.0)),
        "risk_max_open_positions": int(payload.get("risk_max_open_positions", 5)),
        "risk_max_pending_entries": int(payload.get("risk_max_pending_entries", 5)),
        "risk_max_total_active_entries": int(payload.get("risk_max_total_active_entries", 5)),
        "risk_max_directional_entries": int(payload.get("risk_max_directional_entries", 4)),
        "risk_max_portfolio_notional_multiple": float(payload.get("risk_max_portfolio_notional_multiple", 10.0)),
        "risk_max_margin_usage_pct": float(payload.get("risk_max_margin_usage_pct", 80.0)),
        "risk_max_correlated_entries": int(payload.get("risk_max_correlated_entries", 2)),
        "risk_weekly_drawdown_threshold_pct": float(payload.get("risk_weekly_drawdown_threshold_pct", 5.0)),
        "risk_weekly_drawdown_score_penalty": int(payload.get("risk_weekly_drawdown_score_penalty", 10)),
        "risk_base_trade_score_threshold": int(payload.get("risk_base_trade_score_threshold", 75)),
    }


def _create_run(config: dict[str, Any]) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_runs(
                status, strategy_name, strategy_version, symbols, timeframes,
                start_time, end_time, cycle_timeframe, starting_capital, config_json
            )
            VALUES ('created', %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING run_id
            """,
            (
                config["strategy_name"], config["strategy_version"], config["symbols"],
                config["timeframes"], config["start_time"], config.get("end_time"),
                config["cycle_timeframe"], config["starting_capital"], _json(config),
            ),
        )
        return int(cur.fetchone()[0])


def _log(run_id: int | None, event_type: str, message: str, details: dict[str, Any] | None = None, level: str = "INFO") -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO backtest_logs(run_id, level, event_type, message, details_json) VALUES (%s, %s, %s, %s, %s::jsonb)",
            (run_id, level, event_type, message, _json(details or {})),
        )


def _record_order(run_id: int, symbol: str, side: str, order_type: str, requested_price: float, filled_price: float | None, quantity: float, fee: float, reason: str, timestamp, details: dict[str, Any] | None = None, status: str = "filled") -> int:
    filled_at = timestamp if status == "filled" else None
    effective_price = filled_price if filled_price is not None else requested_price
    slippage = abs(effective_price - requested_price) if filled_price is not None else 0.0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_orders(
                run_id, symbol, side, order_type, status, requested_price, filled_price,
                quantity, notional, fee, slippage, reason, created_at, filled_at, details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING order_id
            """,
            (
                run_id, symbol, side, order_type, status, requested_price, filled_price,
                quantity, abs(effective_price * quantity), fee, slippage,
                reason, timestamp, filled_at, _json(details or {}),
            ),
        )
        return int(cur.fetchone()[0])


def _update_order_fill(order_id: int, filled_price: float, quantity: float, fee: float, timestamp, details: dict[str, Any] | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_orders
            SET status='filled',
                filled_price=%s,
                quantity=%s,
                notional=ABS(%s * %s),
                fee=%s,
                slippage=ABS(%s - requested_price),
                filled_at=%s,
                details_json=COALESCE(details_json, '{}'::jsonb) || %s::jsonb
            WHERE order_id=%s
            """,
            (filled_price, quantity, filled_price, quantity, fee, filled_price, timestamp, _json(details or {}), order_id),
        )


def _update_order_status(order_id: int, status: str, timestamp, details: dict[str, Any] | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_orders
            SET status=%s,
                details_json=COALESCE(details_json, '{}'::jsonb) || %s::jsonb
            WHERE order_id=%s
            """,
            (status, _json(details or {}), order_id),
        )



def _open_position(run_id: int, position: dict[str, Any]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_positions(
                run_id, symbol, side, status, entry_time, entry_price, stop_price,
                tp1, tp2, tp3, size, fees, metadata_json
            )
            VALUES (%s, %s, %s, 'open', %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING position_id
            """,
            (
                run_id, position["symbol"], position["side"], position["entry_time"],
                position["entry"], position["stop"], position["tp1"], position["tp2"],
                position["tp3"], position["qty"], position["fees"], _json(position),
            ),
        )
        position["position_id"] = int(cur.fetchone()[0])


def _allocate_entry_fee(position: dict[str, Any], quantity: float, *, final_leg: bool = False) -> float:
    """Allocate the once-paid entry fee across persisted exit-leg rows."""
    entry_fee_total = max(
        0.0,
        float(position.get("fees", 0.0)) - float(position.get("exit_fees", 0.0)),
    )
    already_allocated = max(0.0, float(position.get("allocated_entry_fees", 0.0)))
    remaining = max(0.0, entry_fee_total - already_allocated)

    if final_leg:
        allocation = remaining
    else:
        original_qty = max(0.0, float(position.get("original_qty", position.get("qty", 0.0))))
        proportional = entry_fee_total * (max(0.0, float(quantity)) / original_qty) if original_qty else 0.0
        allocation = min(remaining, proportional)

    position["allocated_entry_fees"] = already_allocated + allocation
    return allocation


def _close_position(
    run_id: int,
    position: dict[str, Any],
    exit_time,
    exit_price: float,
    exit_quantity: float,
    leg_gross_pnl: float,
    exit_fee: float,
    position_gross_pnl: float,
    position_net_pnl: float,
    exit_reason: str,
) -> None:
    entry_fee_allocation = _allocate_entry_fee(position, exit_quantity, final_leg=True)
    leg_fees = entry_fee_allocation + exit_fee
    leg_net_pnl = leg_gross_pnl - leg_fees
    total_fees = position["fees"] + exit_fee
    original_qty = float(position.get("original_qty", position["qty"]))
    risk_stop = float(position.get("original_stop", position.get("initial_stop", position["stop"])))
    initial_risk = abs(position["entry"] - risk_stop) * original_qty
    r_multiple = leg_net_pnl / initial_risk if initial_risk else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_positions
            SET status='closed', exit_time=%s, exit_price=%s, realized_pnl=%s,
                unrealized_pnl=0, fees=%s, exit_reason=%s
            WHERE position_id=%s
            """,
            (exit_time, exit_price, position_net_pnl, total_fees, exit_reason, position["position_id"]),
        )
        cur.execute(
            """
            INSERT INTO backtest_trades(
                run_id, position_id, symbol, side, entry_time, exit_time, entry_price,
                exit_price, quantity, gross_pnl, fees, net_pnl, r_multiple, exit_reason,
                regime, strategy_score, confidence, reason_tags, debug_components
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                run_id, position["position_id"], position["symbol"], position["side"],
                position["entry_time"], exit_time, position["entry"], exit_price,
                exit_quantity, leg_gross_pnl, leg_fees, leg_net_pnl, r_multiple, exit_reason,
                position["regime"], position["score"], position["confidence"],
                position["reason_tags"], _json({
                    **(position.get("debug") or {}),
                    "exit_leg_accounting": {
                        "entry_fee_allocation": entry_fee_allocation,
                        "exit_fee": exit_fee,
                        "position_gross_pnl": position_gross_pnl,
                        "position_net_pnl": position_net_pnl,
                    },
                }),
            ),
        )



def _record_protective_orders_for_position(run_id: int, position: dict[str, Any], timestamp, config: dict[str, Any], details: dict[str, Any] | None = None) -> dict[str, int]:
    if not config.get("protective_orders_enabled", True):
        return {}

    orders = build_protective_orders_for_position(
        run_id=run_id,
        position_id=int(position["position_id"]),
        symbol=position["symbol"],
        side=position["side"],
        entry_price=position["entry"],
        size=position["qty"],
        stop=position["stop"],
        tp1=position["tp1"],
        tp2=position["tp2"],
        tp3=position["tp3"],
        timestamp=timestamp,
        config=config,
    )

    order_ids: dict[str, int] = {}
    for order in orders:
        lifecycle = {
            "version": order["version"],
            "role": order["role"],
            "order_type": order["order_type"],
            "side": order["side"],
            "requested_price": order["requested_price"],
            "requested_size": order["requested_size"],
            "status": "open",
            "events": [
                {"status": "created", "timestamp": timestamp, "details": {"reason": order["reason"], "position_id": position["position_id"]}},
                {"status": "open", "timestamp": timestamp, "details": {"reason": "RESTING_PROTECTIVE_ORDER", "position_id": position["position_id"]}},
            ],
        }

        order_details = {
            "position_id": position["position_id"],
            "role": order["role"],
            "position_side": order["position_side"],
            "entry_price": order["entry_price"],
            "protective_order_model": protective_order_model_contract(config),
            "partial_tp_model": partial_tp_model_contract(config),
            "stop_loss_model": stop_loss_model_contract(config),
            "order_lifecycle": lifecycle,
            **(details or {}),
        }
        if "close_pct" in order:
            order_details["close_pct"] = order["close_pct"]

        order_id = _record_order(
            run_id,
            order["symbol"],
            order["side"],
            order["order_type"],
            order["requested_price"],
            None,
            order["requested_size"],
            0.0,
            order["reason"],
            timestamp,
            order_details,
            status="open",
        )
        order_ids[order["role"]] = order_id

    return order_ids


def _update_open_order_quantity(order_id: int, quantity: float, timestamp, details: dict[str, Any] | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_orders
            SET quantity=%s,
                notional=ABS(requested_price * %s),
                details_json=COALESCE(details_json, '{}'::jsonb) || %s::jsonb
            WHERE order_id=%s
            """,
            (quantity, quantity, _json(details or {}), order_id),
        )



def _update_open_order_price_quantity(order_id: int, price: float, quantity: float, timestamp, details: dict[str, Any] | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_orders
            SET requested_price=%s,
                quantity=%s,
                notional=ABS(%s * %s),
                details_json=COALESCE(details_json, '{}'::jsonb) || %s::jsonb
            WHERE order_id=%s
            """,
            (price, quantity, price, quantity, _json(details or {}), order_id),
        )


def _insert_partial_trade(run_id: int, position: dict[str, Any], role: str, exit_time, exit_price: float, quantity: float, gross_pnl: float, fee: float, net_pnl: float, details: dict[str, Any] | None = None) -> None:
    entry_fee_allocation = _allocate_entry_fee(position, quantity)
    leg_fees = fee + entry_fee_allocation
    leg_net_pnl = gross_pnl - leg_fees
    initial_risk = abs(position["entry"] - position["stop"]) * float(position.get("original_qty", position["qty"]))
    r_multiple = leg_net_pnl / initial_risk if initial_risk else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_trades(
                run_id, position_id, symbol, side, entry_time, exit_time, entry_price,
                exit_price, quantity, gross_pnl, fees, net_pnl, r_multiple, exit_reason,
                regime, strategy_score, confidence, reason_tags, debug_components
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                run_id, position["position_id"], position["symbol"], position["side"],
                position["entry_time"], exit_time, position["entry"], exit_price,
                quantity, gross_pnl, leg_fees, leg_net_pnl, r_multiple, role,
                position["regime"], position["score"], position["confidence"],
                position["reason_tags"], _json({
                    **(position.get("debug") or {}),
                    "partial_tp": details or {},
                    "exit_leg_accounting": {
                        "cash_net_pnl": net_pnl,
                        "entry_fee_allocation": entry_fee_allocation,
                        "exit_fee": fee,
                    },
                }),
            ),
        )



def _record_secondary_stop_order(run_id: int, position: dict[str, Any], trigger_reason: str, stop_price: float, close_pct: float, timestamp, config: dict[str, Any], details: dict[str, Any] | None = None) -> int | None:
    if not config.get("sl2_enabled", True):
        return None

    order = build_sl2_order_payload(
        run_id=run_id,
        position=position,
        trigger_reason=trigger_reason,
        stop_price=stop_price,
        close_pct=close_pct,
        timestamp=timestamp,
        config=config,
    )
    if float(order.get("requested_size") or 0.0) <= 0:
        return None

    lifecycle = {
        "version": order["version"],
        "role": "sl2",
        "order_type": order["order_type"],
        "side": order["side"],
        "requested_price": order["requested_price"],
        "requested_size": order["requested_size"],
        "status": "open",
        "events": [
            {"status": "created", "timestamp": timestamp, "details": {"reason": trigger_reason, "position_id": position["position_id"]}},
            {"status": "open", "timestamp": timestamp, "details": {"reason": "RESTING_SECONDARY_STOP", "position_id": position["position_id"]}},
        ],
    }

    order_id = _record_order(
        run_id,
        order["symbol"],
        order["side"],
        order["order_type"],
        order["requested_price"],
        None,
        order["requested_size"],
        0.0,
        order["reason"],
        timestamp,
        {
            "position_id": position["position_id"],
            "role": "sl2",
            "trigger_reason": trigger_reason,
            "position_side": position["side"],
            "close_pct": order["close_pct"],
            "sl2_model": sl2_model_contract(config),
            "adaptive_stop_model": adaptive_stop_model_contract(config),
            "regime_change_model": regime_change_model_contract(config),
            "volatility_spike_model": volatility_spike_model_contract(config),
            "order_lifecycle": lifecycle,
            **(details or {}),
        },
        status="open",
    )
    mark_sl2_activated(position, order_id=order_id, order_payload=order, timestamp=timestamp)
    return order_id

def _record_equity(run_id: int, timestamp, equity: float, cash: float, realized_pnl: float, unrealized_pnl: float, drawdown_pct: float, conn=None) -> None:
    def write(cur) -> None:
        cur.execute(
            """
            INSERT INTO backtest_equity_curve(
                run_id, timestamp, equity, cash, open_position_value,
                realized_pnl, unrealized_pnl, drawdown_pct
            )
            VALUES (%s, %s, %s, %s, 0, %s, %s, %s)
            """,
            (run_id, timestamp, equity, cash, realized_pnl, unrealized_pnl, drawdown_pct),
        )

    if conn is not None:
        with conn.cursor() as cur:
            write(cur)
        return

    with get_conn() as owned_conn, owned_conn.cursor() as cur:
        write(cur)


def _finalize_run(run_id: int, final_equity: float, starting_capital: float, max_drawdown_pct: float) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)::int,
                COALESCE(SUM(gross_pnl), 0)::float,
                COALESCE(SUM(net_pnl), 0)::float,
                COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0)::float,
                COALESCE(SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END), 0)::float,
                ABS(COALESCE(SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END), 0))::float
            FROM backtest_trades
            WHERE run_id=%s
            """,
            (run_id,),
        )
        total_trades, gross_pnl, net_pnl, wins, gross_wins, gross_losses = cur.fetchone()

        # Phase 18O-HF2:
        # Simulation cash and the exit-leg ledger are independent accounting
        # paths. They must agree; never replace the recorded cash result with a
        # divergent ledger total because that can hide duplicate exit-leg PnL.
        simulation_final_equity = float(final_equity or 0.0)
        ledger_final_equity = float(starting_capital) + float(net_pnl or 0.0)
        equity_reconciliation_delta = ledger_final_equity - simulation_final_equity
        if abs(equity_reconciliation_delta) > 0.01:
            raise RuntimeError(
                "equity_ledger_mismatch: "
                f"cash={simulation_final_equity:.8f}, "
                f"ledger={ledger_final_equity:.8f}, "
                f"delta={equity_reconciliation_delta:.8f}"
            )
        final_equity = simulation_final_equity

        win_rate = wins / total_trades if total_trades else None
        profit_factor = gross_wins / gross_losses if gross_losses else None
        return_pct = ((final_equity - starting_capital) / starting_capital * 100.0) if starting_capital else 0
        summary = {
            "run_id": run_id, "final_equity": final_equity, "return_pct": return_pct,
            "gross_pnl": gross_pnl, "net_pnl": net_pnl, "max_drawdown_pct": max_drawdown_pct,
            "total_trades": total_trades, "win_rate": win_rate, "profit_factor": profit_factor,
            "equity_reconciliation_delta": equity_reconciliation_delta,
        }
        cur.execute(
            """
            UPDATE backtest_runs
            SET status='completed', final_equity=%s, gross_pnl=%s, net_pnl=%s,
                max_drawdown_pct=%s, total_trades=%s, win_rate=%s,
                profit_factor=%s, completed_at=NOW()
            WHERE run_id=%s
            """,
            (final_equity, gross_pnl, net_pnl, max_drawdown_pct, total_trades, win_rate, profit_factor, run_id),
        )
        for key, value in summary.items():
            if key != "run_id" and isinstance(value, (int, float)) and value is not None:
                cur.execute(
                    """
                    INSERT INTO backtest_metrics(run_id, metric_name, metric_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(run_id, metric_name)
                    DO UPDATE SET metric_value=EXCLUDED.metric_value
                    """,
                    (run_id, key, value),
                )
        return summary


def _unrealized(position: dict[str, Any], price: float) -> float:
    if position["side"] == "long":
        return (price - position["entry"]) * position["qty"]
    return (position["entry"] - price) * position["qty"]



def _emit_progress(progress_callback, **event):
    if not progress_callback:
        return
    try:
        progress_callback(event)
    except Exception:
        pass

def run_backtest(payload: dict[str, Any], progress_callback=None, cancel_event=None) -> dict[str, Any]:
    config = _normalize_config(payload)
    strategy_validation = validate_strategy_run_config(config)
    if not strategy_validation.get("valid"):
        return {
            "ok": False,
            "error": "strategy_validation_failed",
            "validation": strategy_validation,
            "config": config,
        }
    run_id = _create_run(config)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE backtest_runs SET status='running', started_at=NOW() WHERE run_id=%s", (run_id,))
    _log(run_id, "BACKTEST_STARTED", "Backtest started.", config)
    _log(run_id, "EXECUTION_TIMELINE_INITIALIZED", "Execution timeline initialized.", config["execution_timeline"])
    _log(run_id, "ORDER_LIFECYCLE_INITIALIZED", "Order lifecycle model initialized.", phase18_lifecycle_contract())
    _log(run_id, "FILL_MODEL_INITIALIZED", "Fill model initialized.", fill_model_contract(config))
    _log(run_id, "ENTRY_ORDER_MODEL_INITIALIZED", "Entry order model initialized.", entry_order_model_contract(config))
    _log(run_id, "PROTECTIVE_ORDER_MODEL_INITIALIZED", "Protective order model initialized.", protective_order_model_contract(config))
    _log(run_id, "PARTIAL_TP_MODEL_INITIALIZED", "Partial TP model initialized.", partial_tp_model_contract(config))
    _log(run_id, "STOP_LOSS_MODEL_INITIALIZED", "Stop-loss model initialized.", stop_loss_model_contract(config))
    _log(run_id, "SL2_MODEL_INITIALIZED", "Secondary stop model initialized.", sl2_model_contract(config))
    _log(run_id, "ADAPTIVE_STOP_MODEL_INITIALIZED", "Adaptive stop model initialized.", adaptive_stop_model_contract(config))
    _log(run_id, "REGIME_CHANGE_MODEL_INITIALIZED", "Regime-change exit model initialized.", regime_change_model_contract(config))
    ensure_position_lifecycle_table()
    _log(run_id, "VOLATILITY_SPIKE_MODEL_INITIALIZED", "Volatility-spike exit model initialized.", volatility_spike_model_contract(config))
    _log(run_id, "POSITION_LIFECYCLE_LEDGER_INITIALIZED", "Position lifecycle ledger initialized.", lifecycle_ledger_contract())

    feed = build_historical_feed(config)
    preflight = feed.preflight()
    _log(run_id, "DATA_PREFLIGHT", "Historical feed preflight completed.", preflight.to_dict(), "INFO" if preflight.ok else "ERROR")

    if not preflight.ok and config["preflight_strict"]:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backtest_runs SET status='failed', completed_at=NOW(), error=%s WHERE run_id=%s", ("data_preflight_failed", run_id))
        return {"ok": False, "run_id": run_id, "error": "data_preflight_failed", "preflight": preflight.to_dict(), "config": config}

    cash = config["starting_capital"]
    realized_pnl = 0.0
    peak_equity = cash
    max_drawdown_pct = 0.0
    open_positions: dict[str, dict[str, Any]] = {}
    pending_entry_orders: dict[str, dict[str, Any]] = {}

    fee_model = FeeModel.from_config(config)
    guardian_policy = GuardianPolicy.from_config(config)
    guardian_state = HistoricalGuardianState()

    guard_rejections = 0
    risk_approved = 0
    risk_notional_requested = 0.0
    entry_orders_submitted = 0
    entry_orders_filled = 0
    entry_orders_expired = 0
    entry_market_fallbacks = 0
    protective_orders_created = 0
    partial_tp_fills = 0
    partial_tp_realized_gross = 0.0
    partial_tp_fees = 0.0
    stop_loss_exits = 0
    missed_stop_reprices = 0
    stop_loss_limit_reprice_attempts = 0
    stop_loss_market_fallbacks = 0
    stop_loss_limit_maker_fills = 0
    sl2_orders_created = 0
    sl2_orders_filled = 0
    sl2_orders_cancelled = 0
    adaptive_stop_updates = 0
    adaptive_stop_skips = 0
    regime_change_checks = 0
    regime_change_sl2_created = 0
    regime_change_sl2_fills = 0
    volatility_spike_checks = 0
    volatility_spike_sl2_created = 0
    volatility_spike_sl2_fills = 0
    near_tp_reversal_checks = 0
    near_tp_stop_updates = 0
    risk_rejections = 0

    _emit_progress(progress_callback, status="running", run_id=run_id, cycle_count=0, cycles_processed=0, candles_processed=0, trades_generated=0, progress_pct=0.0, message="Backtest initialized")

    snapshot_builder = MarketSnapshotBuilder(
        config["symbols"],
        warmup_required_bars=max(config["warmup_required_bars"], 72),
        cycle_timeframe=config["cycle_timeframe"],
    )
    if hasattr(feed, "bootstrap_history"):
        snapshot_builder.seed(feed.bootstrap_history())
    strategy = build_strategy(config["strategy_name"], config)
    strategy_context = StrategyContext(run_config=config)
    cycle_count = 0
    decision_count = 0
    skipped_warmup = 0
    last_snapshot = None
    performance_totals = {
        "feed_seconds": 0.0,
        "snapshot_seconds": 0.0,
        "execution_seconds": 0.0,
        "equity_persistence_seconds": 0.0,
        "production_feature_wall_seconds": 0.0,
        "production_feature_compute_seconds": 0.0,
        "candidate_filter_seconds": 0.0,
        "strategy_engine_seconds": 0.0,
        "strategy_evaluation_seconds": 0.0,
        "atr_seconds": 0.0,
        "decision_seconds": 0.0,
        "cycle_log_seconds": 0.0,
        "cycle_seconds": 0.0,
    }
    feature_cache_totals = {
        "blocks_built": 0,
        "blocks_reused": 0,
        "by_timeframe": {},
    }
    performance_batch_cycles = 0
    performance_batch_seconds = 0.0
    previous_cycle_completed_at = time.perf_counter()
    equity_conn = None

    try:
        equity_conn = get_conn()
        for cycle_index, candles in enumerate(feed.iter_cycles()):
            cycle_started_at = time.perf_counter()
            performance_totals["feed_seconds"] += cycle_started_at - previous_cycle_completed_at
            if cancel_event is not None and cancel_event.is_set():
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE backtest_runs SET status='cancelled', completed_at=NOW(), error=%s WHERE run_id=%s", ("backtest_cancel_requested", run_id))
                _log(run_id, "BACKTEST_CANCELLED", "Backtest cancelled by dashboard.", {"cycle_index": cycle_index}, "WARN")
                _emit_progress(progress_callback, status="cancelled", run_id=run_id, cycle_index=cycle_index, cycle_count=cycle_count, cycles_processed=cycle_count, candles_processed=cycle_count * len(candles), trades_generated=risk_approved, current_simulated_date=candles[0].timestamp.isoformat() if candles else None, progress_pct=100.0, message="Backtest cancelled")
                return {"ok": False, "cancelled": True, "run_id": run_id, "error": "backtest_cancel_requested", "config": config}

            if not candles:
                continue

            cycle_count += 1
            snapshot_started_at = time.perf_counter()
            snapshot = snapshot_builder.build(cycle_index, candles)
            performance_totals["snapshot_seconds"] += time.perf_counter() - snapshot_started_at
            last_snapshot = snapshot

            provisional_unrealized = sum(
                _unrealized(position, snapshot.closes[symbol])
                for symbol, position in open_positions.items()
                if symbol in snapshot.closes
            )
            provisional_equity = cash + provisional_unrealized
            guardian_state.refresh(timestamp=snapshot.timestamp, equity=provisional_equity, policy=guardian_policy)
            strategy_context.account_context.clear()
            strategy_context.account_context.update(guardian_state.to_dict(equity=provisional_equity))
            if hasattr(strategy, "prepare_features"):
                strategy_prepare_started_at = time.perf_counter()
                feature_diagnostics = strategy.prepare_features(
                    snapshot,
                    symbols=config["symbols"],
                )
                feature_wall_seconds = time.perf_counter() - strategy_prepare_started_at
                performance_totals["production_feature_wall_seconds"] += feature_wall_seconds
                performance_totals["production_feature_compute_seconds"] += float(
                    (feature_diagnostics or {}).get("compute_seconds", feature_wall_seconds)
                )
                performance_totals["strategy_evaluation_seconds"] += feature_wall_seconds
                feature_cache_totals["blocks_built"] += int((feature_diagnostics or {}).get("blocks_built", 0))
                feature_cache_totals["blocks_reused"] += int((feature_diagnostics or {}).get("blocks_reused", 0))
                for timeframe, values in ((feature_diagnostics or {}).get("by_timeframe", {}) or {}).items():
                    aggregate = feature_cache_totals["by_timeframe"].setdefault(
                        timeframe,
                        {"built": 0, "reused": 0, "compute_seconds": 0.0},
                    )
                    aggregate["built"] += int(values.get("built", 0))
                    aggregate["reused"] += int(values.get("reused", 0))
                    aggregate["compute_seconds"] += float(values.get("compute_seconds", 0.0))
            elif hasattr(strategy, "prepare_cycle"):
                strategy_prepare_started_at = time.perf_counter()
                strategy.prepare_cycle(
                    snapshot,
                    symbols=config["symbols"],
                    excluded_symbols=set(open_positions) | set(pending_entry_orders),
                )
                performance_totals["strategy_evaluation_seconds"] += time.perf_counter() - strategy_prepare_started_at

            cycle_strategy_decisions: dict[str, Any] = {}
            cycle_atr_values: dict[str, float | None] = {}

            def strategy_decision_for(symbol: str):
                if symbol not in cycle_strategy_decisions:
                    strategy_started_at = time.perf_counter()
                    cycle_strategy_decisions[symbol] = strategy.evaluate_symbol(
                        snapshot,
                        symbol,
                        strategy_context,
                    )
                    strategy_seconds = time.perf_counter() - strategy_started_at
                    performance_totals["strategy_engine_seconds"] += strategy_seconds
                    performance_totals["strategy_evaluation_seconds"] += strategy_seconds
                return cycle_strategy_decisions[symbol]

            def atr_for_symbol(symbol: str) -> float | None:
                if symbol not in cycle_atr_values:
                    atr_started_at = time.perf_counter()
                    timeframe_rows = (
                        ((getattr(snapshot, "timeframe_history", {}) or {}).get(symbol, {}) or {})
                        .get(config.get("cycle_timeframe", "5m"), [])
                    )
                    cycle_atr_values[symbol] = atr_from_rows(
                        timeframe_rows,
                        int(config.get("volatility_spike_atr_period", 14)),
                    )
                    performance_totals["atr_seconds"] += time.perf_counter() - atr_started_at
                return cycle_atr_values[symbol]

            if cycle_count == 1 or cycle_count % max(1, config["cycle_decision_log_interval"]) == 0:
                expected = max(1, int(getattr(preflight, "expected_cycles", config["max_cycles"]) or config["max_cycles"]))
                _emit_progress(progress_callback, status="running", run_id=run_id, cycle_index=cycle_index, cycle_count=cycle_count, cycles_processed=cycle_count, candles_processed=cycle_count * len(candles), trades_generated=risk_approved, current_simulated_date=snapshot.timestamp.isoformat(), progress_pct=min(99.0, cycle_count / expected * 100.0), message="Backtest cycle progress")

            execution_started_at = time.perf_counter()
            execution_slots = virtual_execution_slots(snapshot.timestamp, config["execution_timeline"])
            execution_steps_processed = cycle_count * int(config.get("virtual_execution_steps_per_decision", 1) or 1)

            # 0) Evaluate pending entry orders.
            for symbol, pending_order in list(pending_entry_orders.items()):
                if symbol not in snapshot.highs or symbol not in snapshot.lows:
                    continue

                entry_eval = evaluate_pending_entry_order(
                    order=pending_order,
                    candle_high=snapshot.highs[symbol],
                    candle_low=snapshot.lows[symbol],
                    cycle_index=cycle_index,
                    timestamp=snapshot.timestamp,
                    config=config,
                )

                if entry_eval["action"] == "waiting":
                    continue

                if entry_eval["action"] == "expired":
                    entry_orders_expired += 1
                    pending_order["lifecycle"]["status"] = "expired"
                    pending_order["lifecycle"]["events"].append({"status": "expired", "timestamp": snapshot.timestamp, "details": entry_eval})
                    _update_order_status(int(pending_order["order_id"]), "expired", snapshot.timestamp, {"entry_order_evaluation": entry_eval, "order_lifecycle": pending_order["lifecycle"]})
                    _log(run_id, "ENTRY_ORDER_EXPIRED", f"{symbol} limit entry expired.", {"cycle_index": cycle_index, "entry_order_evaluation": entry_eval})
                    del pending_entry_orders[symbol]
                    continue

                plan = pending_order["plan"]
                side = pending_order["side"]

                if entry_eval["action"] == "market_fallback":
                    entry_market_fallbacks += 1
                    entry_orders_expired += 1
                    market_fill = simulate_market_entry_fill(
                        config=config,
                        position_side=side,
                        requested_price=snapshot.closes[symbol],
                        requested_size=pending_order["requested_size"],
                        timestamp=snapshot.timestamp,
                        reason="ENTRY_MARKET_FALLBACK",
                    )
                    filled_entry = float(market_fill["filled_price"])
                    filled_entry_size = float(market_fill["filled_size"])
                    entry_eval["market_fill"] = market_fill
                    entry_eval["liquidity"] = market_fill.get("liquidity")
                else:
                    filled_entry = float(entry_eval["filled_price"])
                    filled_entry_size = float(entry_eval["filled_size"])

                planned_notional = abs(filled_entry * filled_entry_size)
                entry_fee_details = fee_model.fee_details(planned_notional, entry_eval.get("liquidity"))
                entry_fee = float(entry_fee_details["fee"])

                cash -= entry_fee
                realized_pnl -= entry_fee

                level_reprice = reprice_levels_to_actual_entry(
                    side=side,
                    planned_entry=float(plan["entry"]),
                    actual_entry=filled_entry,
                    stop=float(plan["stop"]),
                    tp1=float(plan["tp1"]),
                    tp2=float(plan["tp2"]),
                    tp3=float(plan["tp3"]),
                )
                repriced_levels = level_reprice["repriced_levels"]

                position = {
                    "symbol": symbol, "side": side, "entry_time": snapshot.timestamp,
                    "entry": filled_entry, "stop": repriced_levels["stop"], "original_stop": repriced_levels["stop"], "tp1": repriced_levels["tp1"],
                    "tp2": repriced_levels["tp2"], "tp3": repriced_levels["tp3"], "qty": filled_entry_size,
                    "original_qty": filled_entry_size, "partial_tp_filled": [],
                    "realized_exit_gross": 0.0, "exit_fees": 0.0, "allocated_entry_fees": 0.0,
                    "fees": entry_fee, "bars": 0, "regime": plan["regime"],
                    "score": plan["score"], "confidence": plan["confidence"],
                    "reason_tags": plan["reason_tags"], "debug": plan["debug"],
                    "level_reprice": level_reprice,
                    "entry_atr": atr_for_symbol(symbol),
                    "margin_used": float(pending_order.get("margin_required", 0.0)),
                    "leverage": float(pending_order.get("leverage", 0.0)),
                }

                initialize_sl2_state(position)
                _open_position(run_id, position)
                record_position_event(
                    run_id=run_id,
                    position=position,
                    event_type="POSITION_OPENED",
                    event_time=snapshot.timestamp,
                    price=filled_entry,
                    quantity=filled_entry_size,
                    fee=entry_fee,
                    remaining_size=position["qty"],
                    reason="ENTRY_FILLED",
                    details={"entry_order_evaluation": entry_eval, "fee_details": entry_fee_details, "level_reprice": level_reprice},
                )
                protective_order_ids = _record_protective_orders_for_position(
                    run_id,
                    position,
                    snapshot.timestamp,
                    config,
                    {
                        "entry_order_id": pending_order.get("order_id"),
                        "entry_order_evaluation": entry_eval,
                        "level_reprice": level_reprice,
                    },
                )
                position["protective_order_ids"] = protective_order_ids
                protective_orders_created += len(protective_order_ids)
                record_position_event(
                    run_id=run_id,
                    position=position,
                    event_type="PROTECTIVE_ORDERS_CREATED",
                    event_time=snapshot.timestamp,
                    remaining_size=position["qty"],
                    reason="PROTECTIVE_ORDERS_CREATED",
                    details={"protective_order_ids": protective_order_ids},
                )
                open_positions[symbol] = position
                entry_orders_filled += 1

                pending_order["lifecycle"]["status"] = "filled"
                pending_order["lifecycle"]["events"].append({"status": "filled", "timestamp": snapshot.timestamp, "details": {"entry_order_evaluation": entry_eval, "position_id": position["position_id"]}})
                _update_order_fill(
                    int(pending_order["order_id"]),
                    filled_entry,
                    filled_entry_size,
                    entry_fee,
                    snapshot.timestamp,
                    {
                        "position_id": position["position_id"],
                        "entry_order_evaluation": entry_eval,
                        "fee_details": entry_fee_details,
                        "order_lifecycle": pending_order["lifecycle"],
                    },
                )
                _log(run_id, "POSITION_OPENED", f"{symbol} {side} opened from entry order.", {"cycle_index": cycle_index, "entry": filled_entry, "quantity": filled_entry_size, "score": plan["score"], "entry_order_evaluation": entry_eval})
                del pending_entry_orders[symbol]

            # 1) Manage existing positions before new entries.
            for symbol, position in list(open_positions.items()):
                if symbol not in snapshot.closes:
                    continue

                position["bars"] += 1
                requested_exit = snapshot.closes[symbol]
                exit_reason = None

                if config.get("near_tp_reversal_enabled", True):
                    near_tp_event = evaluate_near_tp_reversal(
                        position=position,
                        current_price=snapshot.closes[symbol],
                        candle_high=snapshot.highs[symbol],
                        candle_low=snapshot.lows[symbol],
                        config=config,
                    )
                    near_tp_reversal_checks += 1
                    if near_tp_event.get("action") == "MOVE_STOP_TO_BREAKEVEN":
                        position["stop"] = float(near_tp_event["proposed_stop"])
                        stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                        if stop_id:
                            _update_open_order_price_quantity(
                                int(stop_id),
                                position["stop"],
                                position["qty"],
                                snapshot.timestamp,
                                {"reason": "NEAR_TP_REVERSAL_MOVE_STOP_TO_BREAKEVEN", "near_tp_reversal": near_tp_event},
                            )
                        record_position_event(
                            run_id=run_id,
                            position=position,
                            event_type="NEAR_TP_REVERSAL_STOP_UPDATED",
                            event_time=snapshot.timestamp,
                            price=position["stop"],
                            remaining_size=position["qty"],
                            order_id=int(stop_id) if stop_id else None,
                            reason="NEAR_TP_REVERSAL_MOVE_STOP_TO_BREAKEVEN",
                            details={"near_tp_reversal": near_tp_event},
                        )
                        near_tp_stop_updates += 1
                        _log(run_id, "NEAR_TP_REVERSAL_STOP_UPDATED", f"{symbol} stop moved to breakeven after near-TP reversal.", {"cycle_index": cycle_index, "near_tp_reversal": near_tp_event})

                defensive_sl2_active = bool(position.get("sl2_order_id") and position.get("sl2"))
                defensive_sl2_consumed = bool(
                    position.get("defensive_sl2_consumed", False)
                    or position.get("regime_change_sl2_consumed", False)
                    or position.get("volatility_spike_sl2_consumed", False)
                )

                stop_hit = False
                if position["side"] == "long":
                    stop_hit = snapshot.lows[symbol] <= position["stop"]
                else:
                    stop_hit = snapshot.highs[symbol] >= position["stop"]

                # Phase 18J: regime-change SL2 protection.
                # This runs before the normal stop/TP ladder. It only closes a
                # secondary 50% SL2 leg if the SL2 price is actually touched.
                if config.get("regime_change_exit_enabled", True) and not defensive_sl2_active and not defensive_sl2_consumed:
                    regime_sl2_created_this_cycle = False
                    current_regime = None
                    try:
                        if hasattr(strategy, "current_regime"):
                            current_regime = strategy.current_regime(symbol)
                        else:
                            regime_decision = strategy_decision_for(symbol)
                            current_regime = regime_decision.regime
                    except Exception:
                        current_regime = None

                    regime_change_event = evaluate_regime_change_exit(
                        position=position,
                        current_regime=current_regime,
                        latest_price=snapshot.closes[symbol],
                        timestamp=snapshot.timestamp,
                        config=config,
                    )
                    regime_change_checks += 1

                    if regime_change_event.get("action") == "activate_regime_change_sl2":
                        sl2_order_id = _record_secondary_stop_order(
                            run_id,
                            position,
                            "REGIME_CHANGE_SL2",
                            float(regime_change_event["sl2_price"]),
                            float(regime_change_event["sl2_close_pct"]),
                            snapshot.timestamp,
                            config,
                            {"regime_change_event": regime_change_event},
                        )
                        if sl2_order_id:
                            position["regime_change_sl2_active"] = True
                            position["regime_change_sl2_event"] = regime_change_event
                            defensive_sl2_active = True
                            position["defensive_sl2_trigger"] = "regime_change"
                            regime_change_sl2_created += 1
                            sl2_orders_created += 1
                            regime_sl2_created_this_cycle = True

                            # A newly-created SL2 covers 50% by default, so the
                            # primary SL must be reduced immediately to avoid
                            # double-covering the whole position.
                            sl2_requested_size = float((position.get("sl2") or {}).get("requested_size") or 0.0)
                            primary_stop_cover_size = max(0.0, float(position["qty"]) - sl2_requested_size)
                            stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                            if stop_id:
                                _update_open_order_quantity(
                                    int(stop_id),
                                    primary_stop_cover_size,
                                    snapshot.timestamp,
                                    {
                                        "reason": "STOP_RESIZED_AFTER_REGIME_CHANGE_SL2_CREATED",
                                        "remaining_position_size": position["qty"],
                                        "stop_cover_size": primary_stop_cover_size,
                                        "sl2_cover_size": sl2_requested_size,
                                        "sl2_active": True,
                                        "regime_change_event": regime_change_event,
                                    },
                                )

                            record_position_event(
                                run_id=run_id,
                                position=position,
                                event_type="REGIME_CHANGE_SL2_CREATED",
                                event_time=snapshot.timestamp,
                                price=float(regime_change_event["sl2_price"]),
                                quantity=sl2_requested_size,
                                remaining_size=position["qty"],
                                order_id=int(sl2_order_id),
                                reason="REGIME_CHANGE_SL2",
                                details={"regime_change_event": regime_change_event, "stop_cover_size": primary_stop_cover_size, "sl2_cover_size": sl2_requested_size},
                            )
                            _log(run_id, "REGIME_CHANGE_SL2_CREATED", f"{symbol} regime change SL2 created.", {"cycle_index": cycle_index, "symbol": symbol, "regime_change_event": regime_change_event, "stop_cover_size": primary_stop_cover_size, "sl2_cover_size": sl2_requested_size})

                    active_sl2 = position.get("sl2") if position.get("regime_change_sl2_active") else None
                    if active_sl2 and not regime_sl2_created_this_cycle and sl2_touched(
                        side=position["side"],
                        stop_price=float(active_sl2["requested_price"]),
                        candle_high=snapshot.highs[symbol],
                        candle_low=snapshot.lows[symbol],
                    ):
                        sl2_price = float(active_sl2["requested_price"])
                        sl2_size = min(float(position["qty"]), float(active_sl2["requested_size"]))
                        if sl2_size > 0:
                            sl2_gross = realized_gross_for_exit(position, sl2_price, sl2_size)
                            sl2_fee_details = fee_model.fee_details(abs(sl2_price * sl2_size), "maker")
                            sl2_fee = float(sl2_fee_details["fee"])
                            sl2_net = sl2_gross - sl2_fee
                            cash += sl2_net
                            realized_pnl += sl2_net
                            position["qty"] = max(0.0, float(position["qty"]) - sl2_size)
                            position["fees"] += sl2_fee
                            position["exit_fees"] = float(position.get("exit_fees", 0.0)) + sl2_fee
                            position["realized_exit_gross"] = float(position.get("realized_exit_gross", 0.0)) + sl2_gross
                            position.setdefault("partial_tp_filled", []).append("regime_change_sl2")

                            if position.get("sl2_order_id"):
                                _update_order_fill(
                                    int(position["sl2_order_id"]),
                                    sl2_price,
                                    sl2_size,
                                    sl2_fee,
                                    snapshot.timestamp,
                                    {
                                        "regime_change_event": position.get("regime_change_sl2_event"),
                                        "fee_details": sl2_fee_details,
                                        "remaining_position_size": position["qty"],
                                    },
                                )

                            stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                            if stop_id:
                                _update_open_order_quantity(
                                    int(stop_id),
                                    position["qty"],
                                    snapshot.timestamp,
                                    {
                                        "reason": "STOP_RESIZED_AFTER_REGIME_CHANGE_SL2",
                                        "remaining_position_size": position["qty"],
                                        "regime_change_event": position.get("regime_change_sl2_event"),
                                    },
                                )

                            _insert_partial_trade(
                                run_id,
                                position,
                                "REGIME_CHANGE_SL2",
                                snapshot.timestamp,
                                sl2_price,
                                sl2_size,
                                sl2_gross,
                                sl2_fee,
                                sl2_net,
                                {
                                    "regime_change_event": position.get("regime_change_sl2_event"),
                                    "fee_details": sl2_fee_details,
                                },
                            )
                            record_position_event(
                                run_id=run_id,
                                position=position,
                                event_type="REGIME_CHANGE_SL2_FILLED",
                                event_time=snapshot.timestamp,
                                price=sl2_price,
                                quantity=sl2_size,
                                gross_pnl=sl2_gross,
                                fee=sl2_fee,
                                net_pnl=sl2_net,
                                remaining_size=position["qty"],
                                order_id=int(position["sl2_order_id"]) if position.get("sl2_order_id") else None,
                                reason="REGIME_CHANGE_SL2",
                                details={"regime_change_event": position.get("regime_change_sl2_event"), "fee_details": sl2_fee_details},
                            )
                            regime_change_sl2_fills += 1
                            sl2_orders_filled += 1
                            position["regime_change_sl2_active"] = False
                            position["regime_change_sl2_consumed"] = True
                            position["defensive_sl2_consumed"] = True
                            position["defensive_sl2_trigger"] = "regime_change"
                            position["sl2"] = None
                            _log(run_id, "REGIME_CHANGE_SL2_FILLED", f"{symbol} regime-change SL2 filled.", {"cycle_index": cycle_index, "symbol": symbol, "price": sl2_price, "size": sl2_size, "net_pnl": sl2_net, "remaining_size": position["qty"], "regime_change_sl2_consumed": True})
                            continue

                # Phase 18K: volatility-spike SL2 protection.
                if config.get("volatility_spike_exit_enabled", True) and not defensive_sl2_active and not defensive_sl2_consumed:
                    volatility_sl2_created_this_cycle = False
                    current_atr = atr_for_symbol(symbol)
                    volatility_spike_event = evaluate_volatility_spike_exit(
                        position=position,
                        latest_price=snapshot.closes[symbol],
                        current_atr=current_atr,
                        timestamp=snapshot.timestamp,
                        config=config,
                    )
                    volatility_spike_checks += 1

                    if volatility_spike_event.get("action") == "activate_volatility_spike_sl2":
                        sl2_order_id = _record_secondary_stop_order(
                            run_id,
                            position,
                            "VOLATILITY_SPIKE_SL2",
                            float(volatility_spike_event["sl2_price"]),
                            float(volatility_spike_event["sl2_close_pct"]),
                            snapshot.timestamp,
                            config,
                            {"volatility_spike_event": volatility_spike_event},
                        )
                        if sl2_order_id:
                            position["volatility_spike_sl2_active"] = True
                            position["volatility_spike_sl2_event"] = volatility_spike_event
                            defensive_sl2_active = True
                            position["defensive_sl2_trigger"] = "volatility_spike"
                            volatility_spike_sl2_created += 1
                            sl2_orders_created += 1
                            volatility_sl2_created_this_cycle = True

                            sl2_requested_size = float((position.get("sl2") or {}).get("requested_size") or 0.0)
                            primary_stop_cover_size = max(0.0, float(position["qty"]) - sl2_requested_size)
                            stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                            if stop_id:
                                _update_open_order_quantity(
                                    int(stop_id),
                                    primary_stop_cover_size,
                                    snapshot.timestamp,
                                    {
                                        "reason": "STOP_RESIZED_AFTER_VOLATILITY_SPIKE_SL2_CREATED",
                                        "remaining_position_size": position["qty"],
                                        "stop_cover_size": primary_stop_cover_size,
                                        "sl2_cover_size": sl2_requested_size,
                                        "sl2_active": True,
                                        "volatility_spike_event": volatility_spike_event,
                                    },
                                )
                            record_position_event(
                                run_id=run_id,
                                position=position,
                                event_type="VOLATILITY_SPIKE_SL2_CREATED",
                                event_time=snapshot.timestamp,
                                price=float(volatility_spike_event["sl2_price"]),
                                quantity=sl2_requested_size,
                                remaining_size=position["qty"],
                                order_id=int(sl2_order_id),
                                reason="VOLATILITY_SPIKE_SL2",
                                details={"volatility_spike_event": volatility_spike_event, "stop_cover_size": primary_stop_cover_size, "sl2_cover_size": sl2_requested_size},
                            )
                            _log(run_id, "VOLATILITY_SPIKE_SL2_CREATED", f"{symbol} volatility spike SL2 created.", {"cycle_index": cycle_index, "symbol": symbol, "volatility_spike_event": volatility_spike_event, "stop_cover_size": primary_stop_cover_size, "sl2_cover_size": sl2_requested_size})

                    active_vol_sl2 = position.get("sl2") if position.get("volatility_spike_sl2_active") else None
                    if active_vol_sl2 and not volatility_sl2_created_this_cycle and sl2_touched(
                        side=position["side"],
                        stop_price=float(active_vol_sl2["requested_price"]),
                        candle_high=snapshot.highs[symbol],
                        candle_low=snapshot.lows[symbol],
                    ):
                        sl2_price = float(active_vol_sl2["requested_price"])
                        sl2_size = min(float(position["qty"]), float(active_vol_sl2["requested_size"]))
                        if sl2_size > 0:
                            sl2_gross = realized_gross_for_exit(position, sl2_price, sl2_size)
                            sl2_fee_details = fee_model.fee_details(abs(sl2_price * sl2_size), "maker")
                            sl2_fee = float(sl2_fee_details["fee"])
                            sl2_net = sl2_gross - sl2_fee
                            cash += sl2_net
                            realized_pnl += sl2_net
                            position["qty"] = max(0.0, float(position["qty"]) - sl2_size)
                            position["fees"] += sl2_fee
                            position["exit_fees"] = float(position.get("exit_fees", 0.0)) + sl2_fee
                            position["realized_exit_gross"] = float(position.get("realized_exit_gross", 0.0)) + sl2_gross
                            position.setdefault("partial_tp_filled", []).append("volatility_spike_sl2")

                            if position.get("sl2_order_id"):
                                _update_order_fill(
                                    int(position["sl2_order_id"]),
                                    sl2_price,
                                    sl2_size,
                                    sl2_fee,
                                    snapshot.timestamp,
                                    {
                                        "volatility_spike_event": position.get("volatility_spike_sl2_event"),
                                        "fee_details": sl2_fee_details,
                                        "remaining_position_size": position["qty"],
                                    },
                                )

                            stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                            if stop_id:
                                _update_open_order_quantity(
                                    int(stop_id),
                                    position["qty"],
                                    snapshot.timestamp,
                                    {
                                        "reason": "STOP_RESIZED_AFTER_VOLATILITY_SPIKE_SL2",
                                        "remaining_position_size": position["qty"],
                                        "volatility_spike_event": position.get("volatility_spike_sl2_event"),
                                    },
                                )

                            _insert_partial_trade(
                                run_id,
                                position,
                                "VOLATILITY_SPIKE_SL2",
                                snapshot.timestamp,
                                sl2_price,
                                sl2_size,
                                sl2_gross,
                                sl2_fee,
                                sl2_net,
                                {
                                    "volatility_spike_event": position.get("volatility_spike_sl2_event"),
                                    "fee_details": sl2_fee_details,
                                },
                            )
                            record_position_event(
                                run_id=run_id,
                                position=position,
                                event_type="VOLATILITY_SPIKE_SL2_FILLED",
                                event_time=snapshot.timestamp,
                                price=sl2_price,
                                quantity=sl2_size,
                                gross_pnl=sl2_gross,
                                fee=sl2_fee,
                                net_pnl=sl2_net,
                                remaining_size=position["qty"],
                                order_id=int(position["sl2_order_id"]) if position.get("sl2_order_id") else None,
                                reason="VOLATILITY_SPIKE_SL2",
                                details={"volatility_spike_event": position.get("volatility_spike_sl2_event"), "fee_details": sl2_fee_details},
                            )
                            volatility_spike_sl2_fills += 1
                            sl2_orders_filled += 1
                            position["volatility_spike_sl2_active"] = False
                            position["volatility_spike_sl2_consumed"] = True
                            position["defensive_sl2_consumed"] = True
                            position["defensive_sl2_trigger"] = "volatility_spike"
                            position["sl2"] = None
                            _log(run_id, "VOLATILITY_SPIKE_SL2_FILLED", f"{symbol} volatility-spike SL2 filled.", {"cycle_index": cycle_index, "symbol": symbol, "price": sl2_price, "size": sl2_size, "net_pnl": sl2_net, "remaining_size": position["qty"], "volatility_spike_sl2_consumed": True})
                            continue

                stop_loss_event = None
                if stop_hit:
                    stop_loss_event = evaluate_stop_loss_order(
                        position=position,
                        original_stop_price=position["stop"],
                        latest_price=snapshot.closes[symbol],
                        requested_size=position["qty"],
                        timestamp=snapshot.timestamp,
                        config=config,
                    )
                    position["stop_loss_state"] = stop_loss_event.get("state", position.get("stop_loss_state", {}))

                    if stop_loss_event["action"] == "repriced_stop_limit_attempt":
                        stop_loss_limit_reprice_attempts += 1
                        missed_stop_reprices += 1
                        stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                        if stop_id:
                            _update_open_order_quantity(
                                int(stop_id),
                                position["qty"],
                                snapshot.timestamp,
                                {
                                    "stop_loss_event": stop_loss_event,
                                    "reason": "STOP_LIMIT_REPRICE_ATTEMPT",
                                    "remaining_position_size": position["qty"],
                                    "requested_price": stop_loss_event.get("requested_price"),
                                },
                            )
                        _log(run_id, "STOP_LIMIT_REPRICE_ATTEMPT", f"{symbol} stop breached; repricing protective stop-limit.", {"cycle_index": cycle_index, "symbol": symbol, "stop_loss_event": stop_loss_event})
                        continue

                    exit_reason, requested_exit = "STOP_LOSS", float(stop_loss_event["requested_price"])
                elif config.get("partial_tp_enabled", True):
                    partial_tp_event = next_triggered_tp(
                        position,
                        candle_high=snapshot.highs[symbol],
                        candle_low=snapshot.lows[symbol],
                    )

                    if partial_tp_event and partial_tp_event["role"] in ("tp1", "tp2"):
                        role = partial_tp_event["role"]
                        tp_price = float(partial_tp_event["target_price"])
                        tp_size = partial_tp_size(position, role, config)
                        if tp_size > 0:
                            tp_gross = realized_gross_for_exit(position, tp_price, tp_size)
                            tp_fee_details = fee_model.fee_details(abs(tp_price * tp_size), "maker")
                            tp_fee = float(tp_fee_details["fee"])
                            tp_net = tp_gross - tp_fee
                            cash += tp_net
                            realized_pnl += tp_net
                            position["qty"] = max(0.0, float(position["qty"]) - tp_size)
                            position["fees"] += tp_fee
                            position["exit_fees"] = float(position.get("exit_fees", 0.0)) + tp_fee
                            position["realized_exit_gross"] = float(position.get("realized_exit_gross", 0.0)) + tp_gross
                            position.setdefault("partial_tp_filled", []).append(role)

                            order_id = (position.get("protective_order_ids") or {}).get(role)
                            if order_id:
                                _update_order_fill(
                                    int(order_id),
                                    tp_price,
                                    tp_size,
                                    tp_fee,
                                    snapshot.timestamp,
                                    {
                                        "partial_tp_event": partial_tp_event,
                                        "fee_details": tp_fee_details,
                                        "remaining_position_size": position["qty"],
                                    },
                                )

                            stop_id = (position.get("protective_order_ids") or {}).get("stop_loss")
                            active_sl2_id = position.get("sl2_order_id") if position.get("regime_change_sl2_active") else None
                            remaining_after_tp = float(position["qty"])

                            if active_sl2_id:
                                stop_cover_size = remaining_after_tp * 0.5
                                sl2_cover_size = remaining_after_tp - stop_cover_size
                            else:
                                stop_cover_size = remaining_after_tp
                                sl2_cover_size = 0.0

                            adaptive_stop_update = build_adaptive_stop_update(
                                position=position,
                                trigger_role=role,
                                timestamp=snapshot.timestamp,
                                config=config,
                            )

                            if adaptive_stop_update and adaptive_stop_update.get("action") == "adaptive_stop_updated":
                                position["stop"] = float(adaptive_stop_update["new_stop"])
                                adaptive_stop_updates += 1
                                if stop_id:
                                    _update_open_order_price_quantity(
                                        int(stop_id),
                                        position["stop"],
                                        stop_cover_size,
                                        snapshot.timestamp,
                                        {
                                            "reason": "ADAPTIVE_STOP_UPDATED_AFTER_PARTIAL_TP",
                                            "filled_tp_role": role,
                                            "remaining_position_size": remaining_after_tp,
                                            "stop_cover_size": stop_cover_size,
                                            "sl2_cover_size": sl2_cover_size,
                                            "sl2_active": bool(active_sl2_id),
                                            "adaptive_stop_update": adaptive_stop_update,
                                            f"adaptive_stop_update_{role}": adaptive_stop_update,
                                        },
                                    )
                                _log(
                                    run_id,
                                    "ADAPTIVE_STOP_UPDATED",
                                    f"{symbol} stop tightened after {role.upper()}.",
                                    {
                                        "cycle_index": cycle_index,
                                        "symbol": symbol,
                                        "adaptive_stop_update": adaptive_stop_update,
                                        "remaining_position_size": remaining_after_tp,
                                        "stop_cover_size": stop_cover_size,
                                        "sl2_cover_size": sl2_cover_size,
                                        "sl2_active": bool(active_sl2_id),
                                    },
                                )
                            else:
                                if adaptive_stop_update:
                                    adaptive_stop_skips += 1
                                if stop_id:
                                    _update_open_order_quantity(
                                        int(stop_id),
                                        stop_cover_size,
                                        snapshot.timestamp,
                                        {
                                            "reason": "STOP_RESIZED_AFTER_PARTIAL_TP",
                                            "filled_tp_role": role,
                                            "remaining_position_size": remaining_after_tp,
                                            "stop_cover_size": stop_cover_size,
                                            "sl2_cover_size": sl2_cover_size,
                                            "sl2_active": bool(active_sl2_id),
                                            "adaptive_stop_update": adaptive_stop_update,
                                            f"adaptive_stop_update_{role}": adaptive_stop_update,
                                        },
                                    )

                            if active_sl2_id:
                                if isinstance(position.get("sl2"), dict):
                                    position["sl2"]["requested_size"] = sl2_cover_size
                                _update_open_order_quantity(
                                    int(active_sl2_id),
                                    sl2_cover_size,
                                    snapshot.timestamp,
                                    {
                                        "reason": "SL2_RESIZED_AFTER_PARTIAL_TP",
                                        "filled_tp_role": role,
                                        "remaining_position_size": remaining_after_tp,
                                        "stop_cover_size": stop_cover_size,
                                        "sl2_cover_size": sl2_cover_size,
                                        "sl2_active": True,
                                        "adaptive_stop_update": adaptive_stop_update,
                                        f"adaptive_stop_update_{role}": adaptive_stop_update,
                                    },
                                )

                            _insert_partial_trade(
                                run_id,
                                position,
                                role.upper(),
                                snapshot.timestamp,
                                tp_price,
                                tp_size,
                                tp_gross,
                                tp_fee,
                                tp_net,
                                {"partial_tp_event": partial_tp_event, "fee_details": tp_fee_details},
                            )
                            record_position_event(
                                run_id=run_id,
                                position=position,
                                event_type=f"{role.upper()}_FILLED",
                                event_time=snapshot.timestamp,
                                price=tp_price,
                                quantity=tp_size,
                                gross_pnl=tp_gross,
                                fee=tp_fee,
                                net_pnl=tp_net,
                                remaining_size=position["qty"],
                                order_id=int(order_id) if order_id else None,
                                reason=role.upper(),
                                details={"partial_tp_event": partial_tp_event, "fee_details": tp_fee_details},
                            )
                            partial_tp_fills += 1
                            partial_tp_realized_gross += tp_gross
                            partial_tp_fees += tp_fee
                            _log(run_id, "PARTIAL_TP_FILLED", f"{symbol} {role.upper()} partial take-profit filled.", {"cycle_index": cycle_index, "symbol": symbol, "price": tp_price, "size": tp_size, "net_pnl": tp_net, "remaining_size": position["qty"]})
                            continue

                    if partial_tp_event and partial_tp_event["role"] == "tp3":
                        exit_reason, requested_exit = "TP3", position["tp3"]
                else:
                    if position["side"] == "long" and snapshot.highs[symbol] >= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]
                    elif position["side"] == "short" and snapshot.lows[symbol] <= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]

                # Timeout/stale-trade exits are intentionally disabled.
                # Remaining positions close only at protective exits or final backtest settlement.

                if exit_reason:
                    is_tp3_limit_fill = exit_reason == "TP3" and config.get("partial_tp_enabled", True)
                    is_stop_loss_fill = exit_reason == "STOP_LOSS"

                    if is_tp3_limit_fill:
                        filled_exit = float(requested_exit)
                        filled_exit_size = float(position["qty"])
                        exit_fill = {
                            "version": "phase18f_hf3_tp3_maker_limit_fill",
                            "execution_type": "exit",
                            "order_type": "limit_exit",
                            "liquidity": "maker",
                            "position_side": position["side"],
                            "requested_price": float(requested_exit),
                            "filled_price": filled_exit,
                            "requested_size": float(position["qty"]),
                            "filled_size": filled_exit_size,
                            "unfilled_size": 0.0,
                            "partial_fill": False,
                            "fill_ratio": 1.0,
                            "spread_bps": 0.0,
                            "slippage_bps": 0.0,
                            "total_adverse_bps": 0.0,
                            "price_impact": 0.0,
                            "reason": "TP3_LIMIT_EXIT_FILLED",
                        }
                    elif is_stop_loss_fill:
                        if stop_loss_event is None:
                            stop_loss_event = evaluate_stop_loss_order(
                                position=position,
                                original_stop_price=position["stop"],
                                latest_price=snapshot.closes[symbol],
                                requested_size=position["qty"],
                                timestamp=snapshot.timestamp,
                                config=config,
                            )

                        if stop_loss_event["action"] == "stop_limit_fill":
                            filled_exit = float(stop_loss_event["filled_price"])
                            filled_exit_size = float(stop_loss_event["filled_size"])
                            exit_fill = {
                                **stop_loss_event,
                                "filled_price": filled_exit,
                                "filled_size": filled_exit_size,
                            }
                            stop_loss_limit_maker_fills += 1
                        elif stop_loss_event["action"] == "market_stop_fallback":
                            market_fill = simulate_market_exit_fill(
                                config=config,
                                position_side=position["side"],
                                requested_price=float(stop_loss_event["requested_price"]),
                                requested_size=position["qty"],
                                timestamp=snapshot.timestamp,
                                reason="STOP_LOSS_MARKET_FALLBACK",
                            )
                            filled_exit = float(market_fill["filled_price"])
                            filled_exit_size = float(market_fill["filled_size"])
                            exit_fill = {
                                **market_fill,
                                "version": stop_loss_event.get("version"),
                                "action": "market_stop_fallback",
                                "stop_loss_event": stop_loss_event,
                            }
                            stop_loss_market_fallbacks += 1
                        else:
                            raise RuntimeError(f"unsupported_stop_loss_action: {stop_loss_event.get('action')}")

                        stop_loss_exits += 1
                    else:
                        exit_fill = simulate_market_exit_fill(
                            config=config,
                            position_side=position["side"],
                            requested_price=requested_exit,
                            requested_size=position["qty"],
                            timestamp=snapshot.timestamp,
                            reason=exit_reason,
                        )
                        filled_exit = float(exit_fill["filled_price"])
                        filled_exit_size = float(exit_fill["filled_size"])

                    remaining_gross = _unrealized(position, filled_exit)
                    gross = float(position.get("realized_exit_gross", 0.0)) + remaining_gross
                    exit_fee_details = fee_model.fee_details(abs(filled_exit * filled_exit_size), exit_fill.get("liquidity"))
                    exit_fee = float(exit_fee_details["fee"])
                    cash_delta = remaining_gross - exit_fee
                    trade_net = gross - position["fees"] - exit_fee
                    cash += cash_delta
                    realized_pnl += cash_delta
                    exit_side = "sell" if position["side"] == "long" else "buy"
                    if is_tp3_limit_fill:
                        exit_order_type = "limit_exit"
                    elif is_stop_loss_fill:
                        exit_order_type = "stop_limit_exit"
                    else:
                        exit_order_type = "market_exit"
                    exit_role = "tp3" if exit_reason == "TP3" else "stop_loss"
                    exit_lifecycle = build_instant_fill_lifecycle(
                        role=exit_role,
                        order_type=exit_order_type,
                        side=exit_side,
                        requested_price=requested_exit,
                        requested_size=position["qty"],
                        filled_price=filled_exit,
                        filled_size=filled_exit_size,
                        timestamp=snapshot.timestamp,
                        reason=exit_reason,
                        details={"position_id": position["position_id"], "cycle_index": cycle_index, "execution_slots": execution_slots, "fill_model": exit_fill, "fee_details": exit_fee_details},
                    )

                    exit_order_details = {
                        "position_id": position["position_id"],
                        "cycle_index": cycle_index,
                        "order_lifecycle": exit_lifecycle,
                        "fill_model": exit_fill,
                        "fee_details": exit_fee_details,
                    }

                    if is_tp3_limit_fill and (position.get("protective_order_ids") or {}).get("tp3"):
                        _update_order_fill(
                            int((position.get("protective_order_ids") or {})["tp3"]),
                            filled_exit,
                            filled_exit_size,
                            exit_fee,
                            snapshot.timestamp,
                            {
                                **exit_order_details,
                                "partial_tp_event": {
                                    "role": "tp3",
                                    "side": position["side"],
                                    "reason": "TP3",
                                    "version": "phase18f_hf3_tp3_maker_limit_fill",
                                    "target_price": requested_exit,
                                },
                                "remaining_position_size": 0.0,
                            },
                        )
                    elif is_stop_loss_fill and (position.get("protective_order_ids") or {}).get("stop_loss"):
                        _update_order_fill(
                            int((position.get("protective_order_ids") or {})["stop_loss"]),
                            filled_exit,
                            filled_exit_size,
                            exit_fee,
                            snapshot.timestamp,
                            {
                                **exit_order_details,
                                "stop_loss_event": stop_loss_event or exit_fill,
                                "remaining_position_size": 0.0,
                            },
                        )
                    else:
                        _record_order(
                            run_id,
                            symbol,
                            exit_side,
                            exit_order_type,
                            requested_exit,
                            filled_exit,
                            filled_exit_size,
                            exit_fee,
                            exit_reason,
                            snapshot.timestamp,
                            exit_order_details,
                        )

                    _close_position(
                        run_id,
                        position,
                        snapshot.timestamp,
                        filled_exit,
                        filled_exit_size,
                        remaining_gross,
                        exit_fee,
                        gross,
                        trade_net,
                        exit_reason,
                    )
                    guardian_state.record_completed_trade(timestamp=snapshot.timestamp, realized_pnl=trade_net, policy=guardian_policy)
                    record_position_event(
                        run_id=run_id,
                        position=position,
                        event_type="POSITION_CLOSED",
                        event_time=snapshot.timestamp,
                        price=filled_exit,
                        quantity=filled_exit_size,
                        gross_pnl=remaining_gross,
                        fee=exit_fee,
                        net_pnl=cash_delta,
                        remaining_size=0.0,
                        reason=exit_reason,
                        details={
                            "exit_reason": exit_reason,
                            "fill_model": exit_fill,
                            "fee_details": exit_fee_details,
                            "position_net_pnl": trade_net,
                        },
                    )
                    _log(run_id, "POSITION_CLOSED", f"{symbol} closed via {exit_reason}.", {"cycle_index": cycle_index, "symbol": symbol, "net_pnl": trade_net, "fill_liquidity": exit_fill.get("liquidity"), "order_type": exit_order_type, "stop_action": exit_fill.get("action")})
                    del open_positions[symbol]

            # 2) Mark-to-market.
            unrealized = sum(_unrealized(p, snapshot.closes[s]) for s, p in open_positions.items() if s in snapshot.closes)
            equity = cash + unrealized
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity else 0.0
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            equity_persistence_started_at = time.perf_counter()
            _record_equity(
                run_id,
                snapshot.timestamp,
                equity,
                cash,
                realized_pnl,
                unrealized,
                drawdown_pct,
                conn=equity_conn,
            )
            performance_totals["equity_persistence_seconds"] += time.perf_counter() - equity_persistence_started_at
            performance_totals["execution_seconds"] += time.perf_counter() - execution_started_at

            guardian_state.refresh(timestamp=snapshot.timestamp, equity=equity, policy=guardian_policy)
            strategy_context.account_context.clear()
            strategy_context.account_context.update(guardian_state.to_dict(equity=equity))
            if hasattr(strategy, "rank_candidates"):
                candidate_started_at = time.perf_counter()
                strategy.rank_candidates(
                    excluded_symbols=set(open_positions) | set(pending_entry_orders),
                )
                candidate_seconds = time.perf_counter() - candidate_started_at
                performance_totals["candidate_filter_seconds"] += candidate_seconds
                performance_totals["strategy_evaluation_seconds"] += candidate_seconds
                cycle_strategy_decisions.clear()
            elif hasattr(strategy, "prepare_cycle"):
                strategy_prepare_started_at = time.perf_counter()
                strategy.prepare_cycle(
                    snapshot,
                    symbols=config["symbols"],
                    excluded_symbols=set(open_positions) | set(pending_entry_orders),
                )
                performance_totals["strategy_evaluation_seconds"] += time.perf_counter() - strategy_prepare_started_at
                cycle_strategy_decisions.clear()

            # 3) Evaluate decisions from point-in-time snapshot.
            decision_started_at = time.perf_counter()
            cycle_decisions = []
            decision_symbols = (
                strategy.decision_symbol_order(config["symbols"])
                if hasattr(strategy, "decision_symbol_order")
                else config["symbols"]
            )
            for symbol in decision_symbols:
                if symbol not in snapshot.closes:
                    continue

                decision = strategy_decision_for(symbol)
                decision_count += 1
                if decision.reason == "WARMUP_NOT_READY":
                    skipped_warmup += 1

                cycle_decisions.append({
                    "symbol": decision.symbol, "action": decision.action, "side": decision.side,
                    "reason": decision.reason, "score": decision.score, "confidence": decision.confidence,
                    "reason_tags": decision.reason_tags,
                    "diagnostics": _compact_cycle_decision_debug(decision.debug),
                })

                if symbol in open_positions or symbol in pending_entry_orders:
                    continue

                plan = strategy.build_entry_plan(
                    snapshot,
                    decision,
                    equity,
                    dynamic_risk_pct(equity, config["risk_max_risk_pct"]),
                )
                if not plan:
                    continue

                strategy_signal = (decision.debug.get("strategy_signal", {}) or {})
                risk = evaluate_production_risk(
                    plan=plan,
                    strategy_signal=strategy_signal,
                    equity=equity,
                    cash_balance=cash,
                    open_positions=open_positions,
                    pending_entries=pending_entry_orders,
                    guardian_state=guardian_state.to_dict(equity=equity),
                    config=config,
                )
                if not risk.get("ok"):
                    risk_rejections += 1
                    _log(run_id, "RISK_ENTRY_REJECTED", f"{symbol} entry rejected by production risk policies.", {"cycle_index": cycle_index, "symbol": symbol, "risk": risk}, "WARNING")
                    continue
                plan["qty"] = float(risk["quantity"])
                plan["debug"]["production_risk"] = risk
                entry, side, qty = plan["entry"], plan["side"], plan["qty"]
                planned_notional = abs(entry * qty)

                guard = evaluate_entry_guard(
                    policy=guardian_policy,
                    symbol=symbol,
                    planned_notional=planned_notional,
                    equity=equity,
                    starting_capital=config["starting_capital"],
                    realized_pnl=realized_pnl,
                    open_positions=open_positions,
                    pending_entries=pending_entry_orders,
                    state=guardian_state,
                )

                risk_notional_requested += planned_notional

                if not guard.allowed:
                    guard_rejections += 1
                    _log(
                        run_id,
                        "GUARDIAN_ENTRY_REJECTED",
                        f"{symbol} entry rejected.",
                        {
                            "cycle_index": cycle_index,
                            "symbol": symbol,
                            "decision": decision.reason,
                            "guard": guard.to_dict(),
                        },
                        "WARNING",
                    )
                    continue

                risk_approved += 1

                entry_side = "buy" if side == "long" else "sell"
                pending_order = build_pending_limit_entry_order(
                    run_id=run_id,
                    symbol=symbol,
                    side=side,
                    limit_price=entry,
                    requested_size=qty,
                    created_cycle_index=cycle_index,
                    created_at=snapshot.timestamp,
                    plan=plan,
                    decision={
                        "symbol": decision.symbol,
                        "action": decision.action,
                        "side": decision.side,
                        "reason": decision.reason,
                        "score": decision.score,
                        "confidence": decision.confidence,
                        "reason_tags": decision.reason_tags,
                    },
                    guard=guard.to_dict(),
                    execution_slots=execution_slots,
                    config=config,
                )

                entry_order_id = _record_order(
                    run_id,
                    symbol,
                    entry_side,
                    "limit_entry",
                    entry,
                    None,
                    qty,
                    0.0,
                    "ENTRY_ORDER_SUBMITTED",
                    snapshot.timestamp,
                    {
                        "score": plan["score"],
                        "cycle_index": cycle_index,
                        "decision": decision.reason,
                        "guardian": guard.to_dict(),
                        "fee_model": fee_model.to_dict(),
                        "planned_notional": planned_notional,
                        "order_lifecycle": pending_order["lifecycle"],
                        "entry_order_model": entry_order_model_contract(config),
                    },
                    status="open",
                )
                pending_order["order_id"] = entry_order_id
                pending_order["margin_required"] = risk["margin_required"]
                pending_order["leverage"] = risk["leverage"]
                pending_entry_orders[symbol] = pending_order
                entry_orders_submitted += 1
                _log(run_id, "ENTRY_ORDER_SUBMITTED", f"{symbol} {side} limit entry submitted.", {"cycle_index": cycle_index, "entry": entry, "quantity": qty, "score": plan["score"], "lookahead_guard": snapshot.lookahead_guard})

            decision_seconds = time.perf_counter() - decision_started_at
            performance_totals["decision_seconds"] += decision_seconds
            cycle_seconds = time.perf_counter() - cycle_started_at
            performance_totals["cycle_seconds"] += cycle_seconds
            performance_batch_cycles += 1
            performance_batch_seconds += cycle_seconds

            if cycle_index < 3 or cycle_index % max(1, config["cycle_decision_log_interval"]) == 0:
                cycle_log_started_at = time.perf_counter()
                _log(run_id, "CYCLE_DECISIONS", "Cycle decisions recorded.", {
                    "cycle_index": cycle_index, "timestamp": snapshot.timestamp.isoformat(),
                    "equity": equity, "open_positions": list(open_positions.keys()),
                    "snapshot": snapshot.to_log_dict(),
                    "decision_debug_mode": "compact_production_parity_refs",
                    "decisions": cycle_decisions,
                    "performance": {
                        "latest_cycle_ms": round(cycle_seconds * 1000.0, 3),
                        "batch_average_cycle_ms": round(
                            performance_batch_seconds / max(1, performance_batch_cycles) * 1000.0,
                            3,
                        ),
                        "cumulative_average_cycle_ms": round(
                            performance_totals["cycle_seconds"] / max(1, cycle_count) * 1000.0,
                            3,
                        ),
                        "history_rows": {
                            symbol: {timeframe: len(rows) for timeframe, rows in timeframe_rows.items()}
                            for symbol, timeframe_rows in snapshot.timeframe_history.items()
                        },
                        "production_feature_cache": {
                            "workers": config["backtest_feature_workers"],
                            "blocks_built": feature_cache_totals["blocks_built"],
                            "blocks_reused": feature_cache_totals["blocks_reused"],
                        },
                        "stage_total_seconds": {
                            key: round(performance_totals[key], 6)
                            for key in (
                                "production_feature_wall_seconds",
                                "production_feature_compute_seconds",
                                "candidate_filter_seconds",
                                "strategy_engine_seconds",
                                "equity_persistence_seconds",
                                "cycle_log_seconds",
                            )
                        },
                    },
                })
                performance_totals["cycle_log_seconds"] += time.perf_counter() - cycle_log_started_at
                performance_batch_cycles = 0
                performance_batch_seconds = 0.0

            previous_cycle_completed_at = time.perf_counter()

        # 4) Expire remaining pending entry orders, then close remaining positions at final snapshot close.
        if last_snapshot is not None:
            for symbol, pending_order in list(pending_entry_orders.items()):
                pending_order["lifecycle"]["status"] = "expired"
                pending_order["lifecycle"]["events"].append({"status": "expired", "timestamp": last_snapshot.timestamp, "details": {"reason": "END_OF_BACKTEST"}})
                _update_order_status(int(pending_order["order_id"]), "expired", last_snapshot.timestamp, {"reason": "END_OF_BACKTEST", "order_lifecycle": pending_order["lifecycle"]})
                _log(run_id, "ENTRY_ORDER_END_OF_BACKTEST_EXPIRED", f"{symbol} pending entry expired at end of backtest.", {"cycle_index": last_snapshot.cycle_index})
                del pending_entry_orders[symbol]

            for symbol, position in list(open_positions.items()):
                if symbol not in last_snapshot.closes:
                    continue
                requested_exit = last_snapshot.closes[symbol]
                final_exit_fill = simulate_market_exit_fill(
                    config=config,
                    position_side=position["side"],
                    requested_price=requested_exit,
                    requested_size=position["qty"],
                    timestamp=last_snapshot.timestamp,
                    reason="END_OF_BACKTEST",
                )
                filled_exit = float(final_exit_fill["filled_price"])
                final_exit_size = float(final_exit_fill["filled_size"])
                final_remaining_gross = _unrealized(position, filled_exit)
                gross = float(position.get("realized_exit_gross", 0.0)) + final_remaining_gross
                final_exit_fee_details = fee_model.fee_details(abs(filled_exit * final_exit_size), final_exit_fill.get("liquidity"))
                exit_fee = float(final_exit_fee_details["fee"])
                cash_delta = final_remaining_gross - exit_fee
                trade_net = gross - position["fees"] - exit_fee
                cash += cash_delta
                realized_pnl += cash_delta
                final_exit_side = "sell" if position["side"] == "long" else "buy"
                final_lifecycle = build_instant_fill_lifecycle(
                    role="end_of_backtest",
                    order_type="market_exit",
                    side=final_exit_side,
                    requested_price=requested_exit,
                    requested_size=position["qty"],
                    filled_price=filled_exit,
                    filled_size=final_exit_size,
                    timestamp=last_snapshot.timestamp,
                    reason="END_OF_BACKTEST",
                    details={"position_id": position["position_id"], "cycle_index": last_snapshot.cycle_index, "fill_model": final_exit_fill, "fee_details": final_exit_fee_details},
                )
                _record_order(run_id, symbol, final_exit_side, "market_exit", requested_exit, filled_exit, final_exit_size, exit_fee, "END_OF_BACKTEST", last_snapshot.timestamp, {"position_id": position["position_id"], "cycle_index": last_snapshot.cycle_index, "order_lifecycle": final_lifecycle, "fill_model": final_exit_fill, "fee_details": final_exit_fee_details})
                _close_position(
                    run_id,
                    position,
                    last_snapshot.timestamp,
                    filled_exit,
                    final_exit_size,
                    final_remaining_gross,
                    exit_fee,
                    gross,
                    trade_net,
                    "END_OF_BACKTEST",
                )
                guardian_state.record_completed_trade(timestamp=last_snapshot.timestamp, realized_pnl=trade_net, policy=guardian_policy)
                record_position_event(
                    run_id=run_id,
                    position=position,
                    event_type="END_OF_BACKTEST_CLOSED",
                    event_time=last_snapshot.timestamp,
                    price=filled_exit,
                    quantity=final_exit_size,
                    gross_pnl=final_remaining_gross,
                    fee=exit_fee,
                    net_pnl=cash_delta,
                    remaining_size=0.0,
                    reason="END_OF_BACKTEST",
                    details={
                        "fill_model": final_exit_fill,
                        "fee_details": final_exit_fee_details,
                        "position_net_pnl": trade_net,
                    },
                )
                del open_positions[symbol]

        # Phase 18K-HF3:
        # The normal equity curve is recorded inside the cycle loop. End-of-backtest
        # forced settlements happen after that loop, so without this sync point the
        # chart can end below/above the final finalized equity.
        if last_snapshot is not None:
            final_equity_before_finalize = float(cash)
            final_equity_timestamp = last_snapshot.timestamp + timedelta(microseconds=1)
            peak_equity = max(peak_equity, final_equity_before_finalize)
            final_drawdown_pct = ((peak_equity - final_equity_before_finalize) / peak_equity * 100.0) if peak_equity else 0.0
            max_drawdown_pct = max(max_drawdown_pct, final_drawdown_pct)
            _record_equity(
                run_id,
                final_equity_timestamp,
                final_equity_before_finalize,
                cash,
                realized_pnl,
                0.0,
                final_drawdown_pct,
                conn=equity_conn,
            )
            _log(
                run_id,
                "FINAL_EQUITY_SYNC",
                "Final post-settlement equity point recorded.",
                {
                    "timestamp": final_equity_timestamp.isoformat(),
                    "final_equity_before_finalize": final_equity_before_finalize,
                    "cash": cash,
                    "realized_pnl": realized_pnl,
                    "unrealized_pnl": 0.0,
                    "drawdown_pct": final_drawdown_pct,
                },
            )

        summary = _finalize_run(run_id, cash, config["starting_capital"], max_drawdown_pct)
        diagnostics = {
            "cycle_count": cycle_count,
            "decision_count": decision_count,
            "skipped_warmup": skipped_warmup,
            "warmup_required_bars": config["warmup_required_bars"],
            "preflight": preflight.to_dict(),
            "guard_rejections": guard_rejections,
            "risk_approved": risk_approved,
            "risk_notional_requested": risk_notional_requested,
            "guardian_policy": guardian_policy.to_dict(),
            "fee_model": fee_model.to_dict(),
            "strategy_validation": strategy_validation,
            "execution_timeline": config["execution_timeline"],
            "order_lifecycle": phase18_lifecycle_contract(),
            "fill_model": fill_model_contract(config),
            "partial_tp_fills": partial_tp_fills,
            "partial_tp_realized_gross": partial_tp_realized_gross,
            "partial_tp_fees": partial_tp_fees,
            "stop_loss_exits": stop_loss_exits,
            "missed_stop_reprices": missed_stop_reprices,
            "stop_loss_limit_reprice_attempts": stop_loss_limit_reprice_attempts,
            "stop_loss_market_fallbacks": stop_loss_market_fallbacks,
            "stop_loss_limit_maker_fills": stop_loss_limit_maker_fills,
            "sl2_orders_created": sl2_orders_created,
            "sl2_orders_filled": sl2_orders_filled,
            "sl2_orders_cancelled": sl2_orders_cancelled,
            "adaptive_stop_updates": adaptive_stop_updates,
            "adaptive_stop_skips": adaptive_stop_skips,
            "regime_change_checks": regime_change_checks,
            "regime_change_sl2_created": regime_change_sl2_created,
            "regime_change_sl2_fills": regime_change_sl2_fills,
            "volatility_spike_checks": volatility_spike_checks,
            "volatility_spike_sl2_created": volatility_spike_sl2_created,
            "volatility_spike_sl2_fills": volatility_spike_sl2_fills,
            "near_tp_reversal_checks": near_tp_reversal_checks,
            "near_tp_stop_updates": near_tp_stop_updates,
            "risk_rejections": risk_rejections,
            "production_parity_runtime": True,
            "performance": {
                "version": "backtest_production_parity_performance_v2",
                "history_limit": snapshot_builder.history_limit,
                "strategy_evaluations_cached_per_symbol_cycle": True,
                "atr_cached_per_symbol_cycle": True,
                "equity_connection_reused": True,
                "production_feature_timeframe_cache": True,
                "candidate_filter_ranked_once_per_cycle": True,
                "routine_cycle_log_mode": "compact_production_parity_refs",
                "production_feature_workers": config["backtest_feature_workers"],
                "production_feature_cache": {
                    "blocks_built": feature_cache_totals["blocks_built"],
                    "blocks_reused": feature_cache_totals["blocks_reused"],
                    "by_timeframe": {
                        timeframe: {
                            "built": values["built"],
                            "reused": values["reused"],
                            "compute_seconds": round(values["compute_seconds"], 6),
                        }
                        for timeframe, values in feature_cache_totals["by_timeframe"].items()
                    },
                },
                "total_seconds": {
                    key: round(value, 6)
                    for key, value in performance_totals.items()
                },
                "average_cycle_ms": round(
                    performance_totals["cycle_seconds"] / max(1, cycle_count) * 1000.0,
                    3,
                ),
            },
            "timeout_exits_enabled": False,
        }
        _log(run_id, "BACKTEST_COMPLETED", "Backtest completed.", {**summary, **diagnostics})
        return {"ok": True, "run_id": run_id, "summary": summary, "diagnostics": diagnostics, "preflight": preflight.to_dict(), "config": config}

    except Exception as exc:
        exception_type = type(exc).__name__
        exception_message = str(exc) or repr(exc)
        error_text = f"{exception_type}: {exception_message}"
        failure_context = {
            "cycle_index": locals().get("cycle_index"),
            "cycle_count": cycle_count,
            "snapshot_timestamp": last_snapshot.timestamp.isoformat() if last_snapshot is not None else None,
        }
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backtest_runs SET status='failed', completed_at=NOW(), error=%s WHERE run_id=%s", (error_text, run_id))
        _log(run_id, "BACKTEST_FAILED", error_text, {
            "exception_type": exception_type,
            "exception_message": exception_message,
            "traceback": traceback.format_exc(),
            "failure_context": failure_context,
            "config": config,
        }, "ERROR")
        return {
            "ok": False,
            "run_id": run_id,
            "error": error_text,
            "exception_type": exception_type,
            "failure_context": failure_context,
            "config": config,
            "preflight": preflight.to_dict(),
        }

    finally:
        try:
            if hasattr(strategy, "close"):
                strategy.close()
        finally:
            if equity_conn is not None:
                equity_conn.close()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(r) FROM backtest_runs r ORDER BY run_id DESC LIMIT %s", (limit,))
        return [row[0] for row in cur.fetchall()]


def run_detail(run_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(r) FROM backtest_runs r WHERE run_id=%s", (run_id,))
        row = cur.fetchone()
        if not row:
            return None

        def rows(query: str):
            cur.execute(query, (run_id,))
            return [item[0] for item in cur.fetchall()]

        return {
            "run": row[0],
            "trades": rows("SELECT row_to_json(t) FROM backtest_trades t WHERE run_id=%s ORDER BY trade_id"),
            "orders": rows("SELECT row_to_json(o) FROM backtest_orders o WHERE run_id=%s ORDER BY order_id"),
            "positions": rows("SELECT row_to_json(p) FROM backtest_positions p WHERE run_id=%s ORDER BY position_id"),
            "equity_curve": rows("SELECT row_to_json(e) FROM backtest_equity_curve e WHERE run_id=%s ORDER BY timestamp"),
            "metrics": rows("SELECT row_to_json(m) FROM backtest_metrics m WHERE run_id=%s ORDER BY metric_name"),
            "logs": rows("SELECT row_to_json(l) FROM backtest_logs l WHERE run_id=%s ORDER BY timestamp, ctid"),
        }
