from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import sqrt
from typing import Any

from db import get_conn


def _to_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _first(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return default


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _metric(name: str, value: Any, *, available: bool = True, unit: str | None = None) -> dict[str, Any]:
    return {"name": name, "value": value, "available": bool(available), "unit": unit}


def _fetch_run(run_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(r) FROM backtest_runs r WHERE run_id=%s", (run_id,))
        row = cur.fetchone()
        return row[0] if row else None


def _fetch_all(table: str, run_id: int, order_by: str) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT row_to_json(t)
            FROM (
                SELECT *
                FROM {table}
                WHERE run_id=%s
                ORDER BY {order_by}
            ) t
            """,
            (run_id,),
        )
        return [row[0] for row in cur.fetchall()]


def _trade_fees(trade: dict[str, Any]) -> float:
    if trade.get("fees") is not None:
        return abs(float(trade.get("fees") or 0))
    if trade.get("total_fees") is not None:
        return abs(float(trade.get("total_fees") or 0))
    return abs(float(trade.get("entry_fee") or 0)) + abs(float(trade.get("exit_fee") or 0))


def _trade_net(trade: dict[str, Any]) -> float:
    return float(_first(trade, ["net_pnl", "pnl_net", "realized_pnl", "pnl", "profit_loss"], 0) or 0)


def _trade_gross(trade: dict[str, Any]) -> float:
    gross = _first(trade, ["gross_pnl", "pnl_gross"], None)
    if gross is not None:
        return float(gross or 0)
    return _trade_net(trade) + _trade_fees(trade)


def _trade_r(trade: dict[str, Any]) -> float | None:
    value = _first(trade, ["r_multiple", "r", "risk_reward", "rr"], None)
    return _to_float(value, None)


def _trade_hold_seconds(trade: dict[str, Any]) -> float | None:
    value = _first(trade, ["hold_seconds", "holding_seconds", "duration_seconds"], None)
    if value is not None:
        return max(0.0, float(value or 0))
    entry = _parse_dt(_first(trade, ["entry_time", "opened_at", "created_at", "entry_timestamp"], None))
    exit_ = _parse_dt(_first(trade, ["exit_time", "closed_at", "completed_at", "exit_timestamp"], None))
    if entry and exit_:
        return max(0.0, (exit_ - entry).total_seconds())
    bars = _first(trade, ["hold_bars", "bars_held"], None)
    if bars is not None:
        return max(0.0, float(bars or 0)) * 15 * 60
    return None


def _group(trades: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups = defaultdict(lambda: {"trades": 0, "gross_pnl": 0.0, "net_pnl": 0.0, "fees": 0.0, "wins": 0})
    for trade in trades:
        key = str(_first(trade, keys, "unknown") or "unknown")
        net = _trade_net(trade)
        groups[key]["trades"] += 1
        groups[key]["gross_pnl"] += _trade_gross(trade)
        groups[key]["net_pnl"] += net
        groups[key]["fees"] += _trade_fees(trade)
        groups[key]["wins"] += 1 if net > 0 else 0
    rows = []
    for key, group in groups.items():
        count = max(1, int(group["trades"]))
        rows.append({
            "key": key,
            "trades": int(group["trades"]),
            "gross_pnl": group["gross_pnl"],
            "net_pnl": group["net_pnl"],
            "fees": group["fees"],
            "win_rate": group["wins"] / count,
        })
    rows.sort(key=lambda item: item["net_pnl"], reverse=True)
    return rows


def _daily_returns(equity: list[dict[str, Any]]) -> list[float]:
    daily: dict[str, tuple[datetime, float]] = {}
    for point in equity:
        ts = _parse_dt(_first(point, ["timestamp", "created_at"], None))
        value = _to_float(_first(point, ["equity", "equity_value", "balance"], None), None)
        if ts is None or value is None:
            continue
        key = ts.date().isoformat()
        if key not in daily or ts > daily[key][0]:
            daily[key] = (ts, value)
    values = [item[1] for item in sorted(daily.values(), key=lambda item: item[0])]
    return [(curr - prev) / prev for prev, curr in zip(values, values[1:]) if prev]


def _sharpe_sortino(equity: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    returns = _daily_returns(equity)
    if len(returns) < 2:
        return None, None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = sqrt(variance)
    sharpe = (mean / std) * sqrt(365) if std > 0 else None
    downside = [min(0.0, r) for r in returns]
    downside_std = sqrt(sum(r * r for r in downside) / max(1, len(downside) - 1))
    sortino = (mean / downside_std) * sqrt(365) if downside_std > 0 else None
    return sharpe, sortino


def fetch_backtest_analytics(run_id: int) -> dict[str, Any]:
    run = _fetch_run(run_id)
    if not run:
        return {"ok": False, "error": "run_not_found", "run_id": run_id}

    trades = _fetch_all("backtest_trades", run_id, "trade_id")
    equity = _fetch_all("backtest_equity_curve", run_id, "timestamp")

    gross_pnl = _to_float(_first(run, ["gross_pnl"], None), None)
    net_pnl = _to_float(_first(run, ["net_pnl"], None), None)
    if gross_pnl is None:
        gross_pnl = sum(_trade_gross(trade) for trade in trades)
    if net_pnl is None:
        net_pnl = sum(_trade_net(trade) for trade in trades)

    total_fees = sum(_trade_fees(trade) for trade in trades)
    if total_fees == 0 and gross_pnl != net_pnl:
        total_fees = abs(gross_pnl - net_pnl)

    trade_count = len(trades)
    net_values = [_trade_net(trade) for trade in trades]
    wins = [v for v in net_values if v > 0]
    losses = [v for v in net_values if v < 0]
    win_rate = len(wins) / trade_count if trade_count else None
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    expectancy = net_pnl / trade_count if trade_count else None
    r_values = [value for value in (_trade_r(trade) for trade in trades) if value is not None]
    average_r = sum(r_values) / len(r_values) if r_values else None
    hold_values = [value for value in (_trade_hold_seconds(trade) for trade in trades) if value is not None]
    average_hold_seconds = sum(hold_values) / len(hold_values) if hold_values else None
    exposure_time_seconds = sum(hold_values) if hold_values else None
    fees_gross_ratio = total_fees / abs(gross_pnl) if gross_pnl else None
    sharpe, sortino = _sharpe_sortino(equity)

    symbols = _group(trades, ["symbol", "asset", "market"])
    regimes = _group(trades, ["regime", "market_regime", "regime_name", "strategy_route"])
    exits = _group(trades, ["exit_reason", "reason", "close_reason"])
    scores = _group(trades, ["score_bucket", "candidate_tier", "signal_bucket"])

    best_symbol = symbols[0] if symbols else None
    worst_symbol = symbols[-1] if symbols else None
    best_regime = regimes[0] if regimes else None
    worst_regime = regimes[-1] if regimes else None

    metrics = [
        _metric("Gross PnL", gross_pnl, unit="currency"),
        _metric("Net PnL", net_pnl, unit="currency"),
        _metric("Total fees", total_fees, unit="currency"),
        _metric("Max drawdown", _to_float(_first(run, ["max_drawdown_pct"], None), None), unit="percent", available=_first(run, ["max_drawdown_pct"], None) is not None),
        _metric("Sharpe ratio", sharpe, available=sharpe is not None),
        _metric("Sortino ratio", sortino, available=sortino is not None),
        _metric("Profit factor", profit_factor, available=profit_factor is not None),
        _metric("Win rate", win_rate, unit="ratio", available=win_rate is not None),
        _metric("Expectancy", expectancy, unit="currency_per_trade", available=expectancy is not None),
        _metric("Average R", average_r, available=average_r is not None),
        _metric("Best symbol", best_symbol["key"] if best_symbol else None, available=best_symbol is not None),
        _metric("Worst symbol", worst_symbol["key"] if worst_symbol else None, available=worst_symbol is not None),
        _metric("Best regime", best_regime["key"] if best_regime else None, available=best_regime is not None),
        _metric("Worst regime", worst_regime["key"] if worst_regime else None, available=worst_regime is not None),
        _metric("Fees / gross ratio", fees_gross_ratio, unit="ratio", available=fees_gross_ratio is not None),
        _metric("Average hold time", average_hold_seconds, unit="seconds", available=average_hold_seconds is not None),
        _metric("Exposure time", exposure_time_seconds, unit="seconds", available=exposure_time_seconds is not None),
    ]

    return {
        "ok": True,
        "run_id": run_id,
        "run": run,
        "metrics": metrics,
        "summary": {
            "trade_count": trade_count,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "total_fees": total_fees,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "average_r": average_r,
            "sharpe": sharpe,
            "sortino": sortino,
            "fees_gross_ratio": fees_gross_ratio,
            "average_hold_seconds": average_hold_seconds,
            "exposure_time_seconds": exposure_time_seconds,
            "best_symbol": best_symbol,
            "worst_symbol": worst_symbol,
            "best_regime": best_regime,
            "worst_regime": worst_regime,
        },
        "breakdowns": {
            "symbols": symbols,
            "regimes": regimes,
            "exit_reasons": exits,
            "score_buckets": scores,
        },
        "availability": {
            "average_r": bool(r_values),
            "hold_time": bool(hold_values),
            "sharpe_sortino": len(_daily_returns(equity)) >= 2,
            "regime_breakdown": bool(regimes),
            "score_bucket_breakdown": bool(scores),
        },
    }
