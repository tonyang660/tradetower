from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config import DEFAULT_MAX_CYCLES, DEFAULT_RISK_PER_TRADE_PCT, DEFAULT_SLIPPAGE_BPS, DEFAULT_STARTING_CAPITAL
from cycle_simulator import Phase14BaselineDecisionEngine, build_entry_plan
from db import get_conn
from historical_feed import build_historical_feed, parse_time
from market_snapshot import MarketSnapshotBuilder

from fee_model import FeeModel
from guardian_risk import GuardianPolicy, evaluate_entry_guard


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    symbols = payload.get("symbols") or ["BTCUSDT", "ETHUSDT"]
    if isinstance(symbols, str):
        symbols = [symbols]

    cycle_timeframe = str(payload.get("cycle_timeframe") or "15m")
    timeframes = payload.get("timeframes") or [cycle_timeframe]
    if isinstance(timeframes, str):
        timeframes = [timeframes]

    return {
        "strategy_name": payload.get("strategy_name", "phase14a_baseline"),
        "strategy_version": payload.get("strategy_version", "0.1.0"),
        "symbols": [str(s).upper().replace("/", "").replace("-", "") for s in symbols],
        "timeframes": [str(t) for t in timeframes],
        "cycle_timeframe": cycle_timeframe,
        "start_time": parse_time(payload.get("start_time"), datetime(2024, 1, 1, tzinfo=timezone.utc)),
        "end_time": parse_time(payload.get("end_time"), None) if payload.get("end_time") else None,
        "starting_capital": float(payload.get("starting_capital", DEFAULT_STARTING_CAPITAL)),
        "max_cycles": int(payload.get("max_cycles", DEFAULT_MAX_CYCLES)),
        "risk_per_trade_pct": float(payload.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT)),
        "fee_bps_override": float(payload["fee_bps"]) if "fee_bps" in payload else None,
        "maker_fee_bps": float(payload.get("maker_fee_bps", 2.0)),
        "taker_fee_bps": float(payload.get("taker_fee_bps", 6.0)),
        "limit_order_fill_ratio": float(payload.get("limit_order_fill_ratio", 0.80)),
        "slippage_bps": float(payload.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)),
        "data_mode": payload.get("data_mode", "phase14b_sample_historical_feed"),
        "execution_model": "market_with_fee_slippage_bps",
        "preflight_strict": bool(payload.get("preflight_strict", True)),
        "warmup_required_bars": int(payload.get("warmup_required_bars", 8)),
        "cycle_decision_log_interval": int(payload.get("cycle_decision_log_interval", 25)),
        "guardian_trading_enabled": bool(payload.get("guardian_trading_enabled", True)),
        "guardian_read_only_mode": bool(payload.get("guardian_read_only_mode", False)),
        "guardian_maintenance_only_mode": bool(payload.get("guardian_maintenance_only_mode", False)),
        "guardian_max_concurrent_positions": int(payload.get("guardian_max_concurrent_positions", 3)),
        "guardian_max_account_exposure_pct": float(payload.get("guardian_max_account_exposure_pct", 50.0)),
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


def _record_order(run_id: int, symbol: str, side: str, order_type: str, requested_price: float, filled_price: float, quantity: float, fee: float, reason: str, timestamp, details: dict[str, Any] | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_orders(
                run_id, symbol, side, order_type, status, requested_price, filled_price,
                quantity, notional, fee, slippage, reason, created_at, filled_at, details_json
            )
            VALUES (%s, %s, %s, %s, 'filled', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING order_id
            """,
            (
                run_id, symbol, side, order_type, requested_price, filled_price,
                quantity, abs(filled_price * quantity), fee, abs(filled_price - requested_price),
                reason, timestamp, timestamp, _json(details or {}),
            ),
        )
        return int(cur.fetchone()[0])


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
    initial_risk = abs(position["entry"] - position["stop"]) * position["qty"]
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
                position["qty"], gross_pnl, total_fees, net_pnl, r_multiple, exit_reason,
                position["regime"], position["score"], position["confidence"],
                position["reason_tags"], _json(position["debug"]),
            ),
        )


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
        win_rate = wins / total_trades if total_trades else None
        profit_factor = gross_wins / gross_losses if gross_losses else None
        return_pct = ((final_equity - starting_capital) / starting_capital * 100.0) if starting_capital else 0
        summary = {
            "run_id": run_id, "final_equity": final_equity, "return_pct": return_pct,
            "gross_pnl": gross_pnl, "net_pnl": net_pnl, "max_drawdown_pct": max_drawdown_pct,
            "total_trades": total_trades, "win_rate": win_rate, "profit_factor": profit_factor,
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


def run_backtest(payload: dict[str, Any]) -> dict[str, Any]:
    config = _normalize_config(payload)
    run_id = _create_run(config)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE backtest_runs SET status='running', started_at=NOW() WHERE run_id=%s", (run_id,))
    _log(run_id, "BACKTEST_STARTED", "Phase 14C production-like cycle simulation started.", config)

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

    fee_model = FeeModel.from_config(config)
    guardian_policy = GuardianPolicy.from_config(config)

    guard_rejections = 0
    risk_approved = 0
    risk_notional_requested = 0.0

    snapshot_builder = MarketSnapshotBuilder(config["symbols"], warmup_required_bars=config["warmup_required_bars"])
    decision_engine = Phase14BaselineDecisionEngine()
    cycle_count = 0
    decision_count = 0
    skipped_warmup = 0
    last_snapshot = None

    try:
        for cycle_index, candles in enumerate(feed.iter_cycles()):
            if not candles:
                continue

            cycle_count += 1
            snapshot = snapshot_builder.build(cycle_index, candles)
            last_snapshot = snapshot

            # 1) Manage existing positions before new entries.
            for symbol, position in list(open_positions.items()):
                if symbol not in snapshot.closes:
                    continue

                position["bars"] += 1
                requested_exit = snapshot.closes[symbol]
                exit_reason = None

                if position["side"] == "long":
                    if snapshot.lows[symbol] <= position["stop"]:
                        exit_reason, requested_exit = "STOP_LOSS", position["stop"]
                    elif snapshot.highs[symbol] >= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]
                else:
                    if snapshot.highs[symbol] >= position["stop"]:
                        exit_reason, requested_exit = "STOP_LOSS", position["stop"]
                    elif snapshot.lows[symbol] <= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]

                if position["bars"] >= 48 and not exit_reason:
                    exit_reason = "TIMEOUT_CLOSE"

                if exit_reason:
                    slip = config["slippage_bps"] / 10000
                    filled_exit = requested_exit * (1 - slip if position["side"] == "long" else 1 + slip)
                    gross = _unrealized(position, filled_exit)
                    exit_fee = fee_model.fee(abs(filled_exit * position["qty"]))
                    cash_delta = gross - exit_fee
                    trade_net = gross - position["fees"] - exit_fee
                    cash += cash_delta
                    realized_pnl += cash_delta
                    _record_order(run_id, symbol, "sell" if position["side"] == "long" else "buy", "market_exit", requested_exit, filled_exit, position["qty"], exit_fee, exit_reason, snapshot.timestamp, {"position_id": position["position_id"], "cycle_index": cycle_index})
                    _close_position(run_id, position, snapshot.timestamp, filled_exit, gross, exit_fee, trade_net, exit_reason)
                    _log(run_id, "POSITION_CLOSED", f"{symbol} closed via {exit_reason}.", {"cycle_index": cycle_index, "symbol": symbol, "net_pnl": trade_net})
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

                decision = decision_engine.evaluate_symbol(snapshot, symbol)
                decision_count += 1
                if decision.reason == "WARMUP_NOT_READY":
                    skipped_warmup += 1

                cycle_decisions.append({
                    "symbol": decision.symbol, "action": decision.action, "side": decision.side,
                    "reason": decision.reason, "score": decision.score, "confidence": decision.confidence,
                    "reason_tags": decision.reason_tags, "debug": decision.debug,
                })

                if symbol in open_positions:
                    continue

                plan = build_entry_plan(snapshot, decision, equity, config["risk_per_trade_pct"])
                if not plan:
                    continue

                entry, side, qty = plan["entry"], plan["side"], plan["qty"]
                slip = config["slippage_bps"] / 10000
                filled_entry = entry * (1 + slip if side == "long" else 1 - slip)
                planned_notional = abs(filled_entry * qty)

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

                entry_fee = fee_model.fee(planned_notional)

                cash -= entry_fee
                realized_pnl -= entry_fee

                position = {
                    "symbol": symbol, "side": side, "entry_time": snapshot.timestamp,
                    "entry": filled_entry, "stop": plan["stop"], "tp1": plan["tp1"],
                    "tp2": plan["tp2"], "tp3": plan["tp3"], "qty": qty,
                    "fees": entry_fee, "bars": 0, "regime": plan["regime"],
                    "score": plan["score"], "confidence": plan["confidence"],
                    "reason_tags": plan["reason_tags"], "debug": plan["debug"],
                }

                _record_order(
                    run_id,
                    symbol,
                    "buy" if side == "long" else "sell",
                    "market_entry",
                    entry,
                    filled_entry,
                    qty,
                    entry_fee,
                    "STRATEGY_ENTRY",
                    snapshot.timestamp,
                    {
                        "score": plan["score"],
                        "cycle_index": cycle_index,
                        "decision": decision.reason,
                        "guardian": guard.to_dict(),
                        "fee_model": fee_model.to_dict(),
                        "planned_notional": planned_notional,
                    },
                )

                _open_position(run_id, position)
                open_positions[symbol] = position
                _log(run_id, "POSITION_OPENED", f"{symbol} {side} opened.", {"cycle_index": cycle_index, "entry": filled_entry, "quantity": qty, "score": plan["score"], "lookahead_guard": snapshot.lookahead_guard})

            if cycle_index < 3 or cycle_index % max(1, config["cycle_decision_log_interval"]) == 0:
                _log(run_id, "CYCLE_DECISIONS", "Cycle decisions recorded.", {
                    "cycle_index": cycle_index, "timestamp": snapshot.timestamp.isoformat(),
                    "equity": equity, "open_positions": list(open_positions.keys()),
                    "snapshot": snapshot.to_log_dict(), "decisions": cycle_decisions,
                })

        # 4) Close remaining positions at final snapshot close.
        if last_snapshot is not None:
            for symbol, position in list(open_positions.items()):
                if symbol not in last_snapshot.closes:
                    continue
                requested_exit = last_snapshot.closes[symbol]
                slip = config["slippage_bps"] / 10000
                filled_exit = requested_exit * (1 - slip if position["side"] == "long" else 1 + slip)
                gross = _unrealized(position, filled_exit)
                exit_fee = fee_model.fee(abs(filled_exit * position["qty"]))
                cash_delta = gross - exit_fee
                trade_net = gross - position["fees"] - exit_fee
                cash += cash_delta
                realized_pnl += cash_delta
                _record_order(run_id, symbol, "sell" if position["side"] == "long" else "buy", "market_exit", requested_exit, filled_exit, position["qty"], exit_fee, "END_OF_BACKTEST", last_snapshot.timestamp, {"position_id": position["position_id"], "cycle_index": last_snapshot.cycle_index})
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
        }
        _log(run_id, "BACKTEST_COMPLETED", "Phase 14C completed.", {**summary, **diagnostics})
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
