from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (
    DEFAULT_FEE_BPS,
    DEFAULT_MAX_CYCLES,
    DEFAULT_RISK_PER_TRADE_PCT,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_STARTING_CAPITAL,
)
from db import get_conn


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _parse_time(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return fallback


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
        "start_time": _parse_time(payload.get("start_time"), datetime(2024, 1, 1, tzinfo=timezone.utc)),
        "end_time": payload.get("end_time"),
        "starting_capital": float(payload.get("starting_capital", DEFAULT_STARTING_CAPITAL)),
        "max_cycles": int(payload.get("max_cycles", DEFAULT_MAX_CYCLES)),
        "risk_per_trade_pct": float(payload.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT)),
        "fee_bps": float(payload.get("fee_bps", DEFAULT_FEE_BPS)),
        "slippage_bps": float(payload.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)),
        "data_mode": "phase14a_sample_stream",
        "execution_model": "market_with_fee_slippage_bps",
    }


def _sample_price(symbol_index: int, cycle_index: int) -> float:
    return (
        100
        + symbol_index * 35
        + cycle_index * (0.015 + symbol_index * 0.002)
        + math.sin(cycle_index / 9 + symbol_index) * 1.25
        + math.sin(cycle_index / 29 + symbol_index * 3) * 0.75
    )


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
                config["strategy_name"],
                config["strategy_version"],
                config["symbols"],
                config["timeframes"],
                config["start_time"],
                config.get("end_time"),
                config["cycle_timeframe"],
                config["starting_capital"],
                _json(config),
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
            "run_id": run_id,
            "final_equity": final_equity,
            "return_pct": return_pct,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "max_drawdown_pct": max_drawdown_pct,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
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
    _log(run_id, "BACKTEST_STARTED", "Phase 14A event-driven backtest started.", config)

    cash = config["starting_capital"]
    realized_pnl = 0.0
    peak_equity = cash
    max_drawdown_pct = 0.0
    open_positions: dict[str, dict[str, Any]] = {}
    history = {symbol: [] for symbol in config["symbols"]}
    minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}.get(config["cycle_timeframe"], 15)

    try:
        for i in range(config["max_cycles"]):
            timestamp = config["start_time"] + timedelta(minutes=minutes * i)
            closes = {symbol: _sample_price(idx, i) for idx, symbol in enumerate(config["symbols"])}
            highs = {symbol: price + 0.6 for symbol, price in closes.items()}
            lows = {symbol: price - 0.6 for symbol, price in closes.items()}

            for symbol, position in list(open_positions.items()):
                position["bars"] += 1
                requested_exit = closes[symbol]
                exit_reason = None
                if position["side"] == "long":
                    if lows[symbol] <= position["stop"]:
                        exit_reason, requested_exit = "STOP_LOSS", position["stop"]
                    elif highs[symbol] >= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]
                else:
                    if highs[symbol] >= position["stop"]:
                        exit_reason, requested_exit = "STOP_LOSS", position["stop"]
                    elif lows[symbol] <= position["tp3"]:
                        exit_reason, requested_exit = "TP3", position["tp3"]
                if position["bars"] >= 48 and not exit_reason:
                    exit_reason = "TIMEOUT_CLOSE"

                if exit_reason:
                    slip = config["slippage_bps"] / 10000
                    filled_exit = requested_exit * (1 - slip if position["side"] == "long" else 1 + slip)
                    gross = _unrealized(position, filled_exit)
                    exit_fee = abs(filled_exit * position["qty"]) * config["fee_bps"] / 10000
                    cash_delta = gross - exit_fee
                    trade_net = gross - position["fees"] - exit_fee

                    cash += cash_delta
                    realized_pnl += cash_delta

                    _record_order(
                        run_id,
                        symbol,
                        "sell" if position["side"] == "long" else "buy",
                        "market_exit",
                        requested_exit,
                        filled_exit,
                        position["qty"],
                        exit_fee,
                        exit_reason,
                        timestamp,
                        {"position_id": position["position_id"]},
                    )

                    _close_position(
                        run_id,
                        position,
                        timestamp,
                        filled_exit,
                        gross,
                        exit_fee,
                        trade_net,
                        exit_reason,
                    )

                    del open_positions[symbol]

            unrealized = sum(_unrealized(p, closes[s]) for s, p in open_positions.items())
            equity = cash + unrealized
            peak_equity = max(peak_equity, equity)
            drawdown_pct = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity else 0.0
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            _record_equity(run_id, timestamp, equity, cash, realized_pnl, unrealized, drawdown_pct)

            for symbol_index, symbol in enumerate(config["symbols"]):
                history[symbol].append(closes[symbol])
                if symbol in open_positions or len(history[symbol]) < 8:
                    continue
                m3 = (history[symbol][-1] - history[symbol][-4]) / history[symbol][-4]
                m7 = (history[symbol][-1] - history[symbol][-8]) / history[symbol][-8]
                side = None
                if m3 > 0.003 and m7 > 0.001:
                    side = "long"
                elif m3 < -0.003 and m7 < -0.001:
                    side = "short"
                if not side:
                    continue

                entry = closes[symbol]
                stop = entry * (0.985 if side == "long" else 1.015)
                risk = equity * config["risk_per_trade_pct"] / 100
                qty = risk / abs(entry - stop) if abs(entry - stop) > 0 else 0
                if qty <= 0:
                    continue
                slip = config["slippage_bps"] / 10000
                filled_entry = entry * (1 + slip if side == "long" else 1 - slip)
                entry_fee = abs(filled_entry * qty) * config["fee_bps"] / 10000
                cash -= entry_fee
                realized_pnl -= entry_fee
                position = {
                    "symbol": symbol,
                    "side": side,
                    "entry_time": timestamp,
                    "entry": filled_entry,
                    "stop": stop,
                    "tp1": entry * (1.012 if side == "long" else 0.988),
                    "tp2": entry * (1.020 if side == "long" else 0.980),
                    "tp3": entry * (1.032 if side == "long" else 0.968),
                    "qty": qty,
                    "fees": entry_fee,
                    "bars": 0,
                    "regime": "sample_trend" if side == "long" else "sample_downtrend",
                    "score": 70.0,
                    "confidence": 0.70,
                    "reason_tags": ["PHASE14A_BASELINE", "EVENT_DRIVEN_TEST"],
                    "debug": {"m3": m3, "m7": m7},
                }
                _record_order(run_id, symbol, "buy" if side == "long" else "sell", "market_entry", entry, filled_entry, qty, entry_fee, "STRATEGY_ENTRY", timestamp, {"score": 70})
                _open_position(run_id, position)
                open_positions[symbol] = position

        if config["max_cycles"] > 0:
            timestamp = config["start_time"] + timedelta(minutes=minutes * (config["max_cycles"] - 1))
            for symbol, position in list(open_positions.items()):
                requested_exit = _sample_price(config["symbols"].index(symbol), config["max_cycles"] - 1)
                slip = config["slippage_bps"] / 10000
                filled_exit = requested_exit * (1 - slip if position["side"] == "long" else 1 + slip)
                gross = _unrealized(position, filled_exit)
                exit_fee = abs(filled_exit * position["qty"]) * config["fee_bps"] / 10000
                cash_delta = gross - exit_fee
                trade_net = gross - position["fees"] - exit_fee

                cash += cash_delta
                realized_pnl += cash_delta

                _record_order(
                    run_id,
                    symbol,
                    "sell" if position["side"] == "long" else "buy",
                    "market_exit",
                    requested_exit,
                    filled_exit,
                    position["qty"],
                    exit_fee,
                    "END_OF_BACKTEST",
                    timestamp,
                    {"position_id": position["position_id"]},
                )

                _close_position(
                    run_id,
                    position,
                    timestamp,
                    filled_exit,
                    gross,
                    exit_fee,
                    trade_net,
                    "END_OF_BACKTEST",
                )

        summary = _finalize_run(run_id, cash, config["starting_capital"], max_drawdown_pct)
        _log(run_id, "BACKTEST_COMPLETED", "Phase 14A completed.", summary)
        return {"ok": True, "run_id": run_id, "summary": summary, "config": config}
    except Exception as exc:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backtest_runs SET status='failed', completed_at=NOW(), error=%s WHERE run_id=%s", (str(exc), run_id))
        _log(run_id, "BACKTEST_FAILED", str(exc), config, "ERROR")
        return {"ok": False, "run_id": run_id, "error": str(exc), "config": config}


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
