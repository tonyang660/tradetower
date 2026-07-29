from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config import DEFAULT_MAX_CYCLES, DEFAULT_RISK_PER_TRADE_PCT, DEFAULT_SLIPPAGE_BPS, DEFAULT_STARTING_CAPITAL
from strategies.registry import build_strategy
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
from secondary_stop_simulator import initialize_sl2_state, build_sl2_order_payload, mark_sl2_activated, sl2_model_contract
from adaptive_stop_simulator import build_adaptive_stop_update, adaptive_stop_model_contract

from fee_model import FeeModel
from guardian_risk import GuardianPolicy, evaluate_entry_guard


def _json(value: Any) -> str:
    return json.dumps(value, default=str)



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
        "strategy_version": payload.get("strategy_version", "0.2.0" if payload.get("strategy_name", "tradetower_baseline_v1") == "tradetower_baseline_v1" else "0.1.0"),
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
        "adaptive_stop_after_tp1_enabled": bool(payload.get("adaptive_stop_after_tp1_enabled", True)),
        "adaptive_stop_after_tp2_enabled": bool(payload.get("adaptive_stop_after_tp2_enabled", True)),
        "adaptive_stop_breakeven_buffer_bps": float(payload.get("adaptive_stop_breakeven_buffer_bps", 2.0)),
        "data_mode": payload.get("data_mode", "phase14b_sample_historical_feed"),
        "dataset_id": int(payload.get("dataset_id", 0) or 0),
        "execution_model": payload.get("execution_model", "phase18_virtual_1m_order_lifecycle"),
        "preflight_strict": bool(payload.get("preflight_strict", True)),
        "warmup_required_bars": int(payload.get("warmup_required_bars", 8)),
        "cycle_decision_log_interval": int(payload.get("cycle_decision_log_interval", 25)),
        "strategy_validation_strict_timeframes": bool(payload.get("strategy_validation_strict_timeframes", False)),
        "guardian_trading_enabled": bool(payload.get("guardian_trading_enabled", True)),
        "guardian_read_only_mode": bool(payload.get("guardian_read_only_mode", False)),
        "guardian_maintenance_only_mode": bool(payload.get("guardian_maintenance_only_mode", False)),
        "guardian_max_concurrent_positions": int(payload.get("guardian_max_concurrent_positions", 3)),
        "guardian_max_account_exposure_pct": float(payload.get("guardian_max_account_exposure_pct", 80.0)),
        "guardian_max_position_leverage": float(payload.get("guardian_max_position_leverage", payload.get("guardian_max_leverage", 15.0))),
        "guardian_account_max_notional_multiplier": float(payload.get("guardian_account_max_notional_multiplier", payload.get("guardian_account_exposure_multiplier", 10.0))),
        "guardian_daily_loss_limit_pct": float(payload.get("guardian_daily_loss_limit_pct", 3.0)),
        "guardian_weekly_loss_limit_pct": float(payload.get("guardian_weekly_loss_limit_pct", 6.0)),
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


def _close_position(run_id: int, position: dict[str, Any], exit_time, exit_price: float, gross_pnl: float, exit_fee: float, net_pnl: float, exit_reason: str) -> None:
    total_fees = position["fees"] + exit_fee
    original_qty = float(position.get("original_qty", position["qty"]))
    initial_risk = abs(position["entry"] - position["stop"]) * original_qty
    r_multiple = net_pnl / initial_risk if initial_risk else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_positions
            SET status='closed', exit_time=%s, exit_price=%s, realized_pnl=%s,
                unrealized_pnl=0, fees=%s, exit_reason=%s
            WHERE position_id=%s
            """,
            (exit_time, exit_price, net_pnl, total_fees, exit_reason, position["position_id"]),
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
                original_qty, gross_pnl, total_fees, net_pnl, r_multiple, exit_reason,
                position["regime"], position["score"], position["confidence"],
                position["reason_tags"], _json(position["debug"]),
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
    initial_risk = abs(position["entry"] - position["stop"]) * float(position.get("original_qty", position["qty"]))
    r_multiple = net_pnl / initial_risk if initial_risk else None
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
                quantity, gross_pnl, fee, net_pnl, r_multiple, role,
                position["regime"], position["score"], position["confidence"],
                position["reason_tags"], _json({**(position.get("debug") or {}), "partial_tp": details or {}}),
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
            "order_lifecycle": lifecycle,
            **(details or {}),
        },
        status="open",
    )
    mark_sl2_activated(position, order_id=order_id, order_payload=order, timestamp=timestamp)
    return order_id

def _record_equity(run_id: int, timestamp, equity: float, cash: float, realized_pnl: float, unrealized_pnl: float, drawdown_pct: float) -> None:
    with get_conn() as conn, conn.cursor() as cur:
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

        # Phase 18F-HF2:
        # Partial TP rows are stored as realized trade rows before the remaining
        # position is closed. Some in-memory equity paths can miss those partial
        # realized exits. At finalization all positions have been settled, so the
        # trade ledger is the source of truth for final equity.
        ledger_final_equity = float(starting_capital) + float(net_pnl or 0.0)
        equity_reconciliation_delta = ledger_final_equity - float(final_equity or 0.0)
        final_equity = ledger_final_equity

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

    _emit_progress(progress_callback, status="running", run_id=run_id, cycle_count=0, cycles_processed=0, candles_processed=0, trades_generated=0, progress_pct=0.0, message="Backtest initialized")

    snapshot_builder = MarketSnapshotBuilder(config["symbols"], warmup_required_bars=config["warmup_required_bars"])
    strategy = build_strategy(config["strategy_name"], config)
    cycle_count = 0
    decision_count = 0
    skipped_warmup = 0
    last_snapshot = None

    try:
        for cycle_index, candles in enumerate(feed.iter_cycles()):
            if cancel_event is not None and cancel_event.is_set():
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute("UPDATE backtest_runs SET status='cancelled', completed_at=NOW(), error=%s WHERE run_id=%s", ("backtest_cancel_requested", run_id))
                _log(run_id, "BACKTEST_CANCELLED", "Backtest cancelled by dashboard.", {"cycle_index": cycle_index}, "WARN")
                _emit_progress(progress_callback, status="cancelled", run_id=run_id, cycle_index=cycle_index, cycle_count=cycle_count, cycles_processed=cycle_count, candles_processed=cycle_count * len(candles), trades_generated=risk_approved, current_simulated_date=candles[0].timestamp.isoformat() if candles else None, progress_pct=100.0, message="Backtest cancelled")
                return {"ok": False, "cancelled": True, "run_id": run_id, "error": "backtest_cancel_requested", "config": config}

            if not candles:
                continue

            cycle_count += 1
            snapshot = snapshot_builder.build(cycle_index, candles)
            last_snapshot = snapshot

            if cycle_count == 1 or cycle_count % max(1, config["cycle_decision_log_interval"]) == 0:
                expected = max(1, int(getattr(preflight, "expected_cycles", config["max_cycles"]) or config["max_cycles"]))
                _emit_progress(progress_callback, status="running", run_id=run_id, cycle_index=cycle_index, cycle_count=cycle_count, cycles_processed=cycle_count, candles_processed=cycle_count * len(candles), trades_generated=risk_approved, current_simulated_date=snapshot.timestamp.isoformat(), progress_pct=min(99.0, cycle_count / expected * 100.0), message="Backtest cycle progress")

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
                    "realized_exit_gross": 0.0, "exit_fees": 0.0,
                    "fees": entry_fee, "bars": 0, "regime": plan["regime"],
                    "score": plan["score"], "confidence": plan["confidence"],
                    "reason_tags": plan["reason_tags"], "debug": plan["debug"],
                    "level_reprice": level_reprice,
                }

                initialize_sl2_state(position)
                _open_position(run_id, position)
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

                stop_hit = False
                if position["side"] == "long":
                    stop_hit = snapshot.lows[symbol] <= position["stop"]
                else:
                    stop_hit = snapshot.highs[symbol] >= position["stop"]

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
                                        position["qty"],
                                        snapshot.timestamp,
                                        {
                                            "reason": "ADAPTIVE_STOP_UPDATED_AFTER_PARTIAL_TP",
                                            "filled_tp_role": role,
                                            "remaining_position_size": position["qty"],
                                            "adaptive_stop_update": adaptive_stop_update,
                                        },
                                    )
                                _log(run_id, "ADAPTIVE_STOP_UPDATED", f"{symbol} stop tightened after {role.upper()}.", {"cycle_index": cycle_index, "symbol": symbol, "adaptive_stop_update": adaptive_stop_update})
                            else:
                                if adaptive_stop_update:
                                    adaptive_stop_skips += 1
                                if stop_id:
                                    _update_open_order_quantity(
                                        int(stop_id),
                                        position["qty"],
                                        snapshot.timestamp,
                                        {
                                            "reason": "STOP_RESIZED_AFTER_PARTIAL_TP",
                                            "filled_tp_role": role,
                                            "remaining_position_size": position["qty"],
                                            "adaptive_stop_update": adaptive_stop_update,
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

                    _close_position(run_id, position, snapshot.timestamp, filled_exit, gross, exit_fee, trade_net, exit_reason)
                    _log(run_id, "POSITION_CLOSED", f"{symbol} closed via {exit_reason}.", {"cycle_index": cycle_index, "symbol": symbol, "net_pnl": trade_net, "fill_liquidity": exit_fill.get("liquidity"), "order_type": exit_order_type, "stop_action": exit_fill.get("action")})
                    del open_positions[symbol]

            # 2) Mark-to-market.
            unrealized = sum(_unrealized(p, snapshot.closes[s]) for s, p in open_positions.items() if s in snapshot.closes)
            equity = cash + unrealized
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity else 0.0
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            _record_equity(run_id, snapshot.timestamp, equity, cash, realized_pnl, unrealized, drawdown_pct)

            # 3) Evaluate decisions from point-in-time snapshot.
            cycle_decisions = []
            for symbol in config["symbols"]:
                if symbol not in snapshot.closes:
                    continue

                decision = strategy.evaluate_symbol(snapshot, symbol)
                decision_count += 1
                if decision.reason == "WARMUP_NOT_READY":
                    skipped_warmup += 1

                cycle_decisions.append({
                    "symbol": decision.symbol, "action": decision.action, "side": decision.side,
                    "reason": decision.reason, "score": decision.score, "confidence": decision.confidence,
                    "reason_tags": decision.reason_tags, "debug": decision.debug,
                })

                if symbol in open_positions or symbol in pending_entry_orders:
                    continue

                plan = strategy.build_entry_plan(snapshot, decision, equity, config["risk_per_trade_pct"])
                if not plan:
                    continue

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
                pending_entry_orders[symbol] = pending_order
                entry_orders_submitted += 1
                _log(run_id, "ENTRY_ORDER_SUBMITTED", f"{symbol} {side} limit entry submitted.", {"cycle_index": cycle_index, "entry": entry, "quantity": qty, "score": plan["score"], "lookahead_guard": snapshot.lookahead_guard})

            if cycle_index < 3 or cycle_index % max(1, config["cycle_decision_log_interval"]) == 0:
                _log(run_id, "CYCLE_DECISIONS", "Cycle decisions recorded.", {
                    "cycle_index": cycle_index, "timestamp": snapshot.timestamp.isoformat(),
                    "equity": equity, "open_positions": list(open_positions.keys()),
                    "snapshot": snapshot.to_log_dict(), "decisions": cycle_decisions,
                })

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
                _close_position(run_id, position, last_snapshot.timestamp, filled_exit, gross, exit_fee, trade_net, "END_OF_BACKTEST")
                del open_positions[symbol]

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
            "timeout_exits_enabled": False,
        }
        _log(run_id, "BACKTEST_COMPLETED", "Backtest completed.", {**summary, **diagnostics})
        return {"ok": True, "run_id": run_id, "summary": summary, "diagnostics": diagnostics, "preflight": preflight.to_dict(), "config": config}

    except Exception as exc:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backtest_runs SET status='failed', completed_at=NOW(), error=%s WHERE run_id=%s", (str(exc), run_id))
        _log(run_id, "BACKTEST_FAILED", str(exc), config, "ERROR")
        return {"ok": False, "run_id": run_id, "error": str(exc), "config": config, "preflight": preflight.to_dict()}


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
            "logs": rows("SELECT row_to_json(l) FROM backtest_logs l WHERE run_id=%s ORDER BY timestamp, log_id"),
        }
