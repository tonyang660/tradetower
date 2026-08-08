from __future__ import annotations

from typing import Any

from production_runtime import load_production_module


BACKTEST_PRODUCTION_RISK_VERSION = "backtest_production_risk_adapter_v1"


def dynamic_risk_pct(equity: float, ceiling: float = 1.0) -> float:
    policy = load_production_module("risk_engine", "risk_policy")
    return float(policy.calculate_base_risk_amount(equity, max_risk_pct_ceiling=ceiling)["risk_pct"])


def _open_items(open_positions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "symbol": symbol,
        "position_side": position.get("side"),
        "remaining_size": float(position.get("qty", 0.0)),
        "entry_price": float(position.get("entry", 0.0)),
        "mark_price": float(position.get("mark_price", position.get("entry", 0.0))),
        "notional": abs(float(position.get("qty", 0.0)) * float(position.get("entry", 0.0))),
        "margin_used": float(position.get("margin_used", 0.0)),
    } for symbol, position in open_positions.items()]


def _pending_items(pending_entries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "symbol": symbol,
        "position_side": order.get("side"),
        "requested_size": float(order.get("requested_size", 0.0)),
        "requested_price": float((order.get("plan") or {}).get("entry", 0.0)),
        "notional": abs(float(order.get("requested_size", 0.0)) * float((order.get("plan") or {}).get("entry", 0.0))),
        "margin_required": float(order.get("margin_required", 0.0)),
    } for symbol, order in pending_entries.items()]


def evaluate_production_risk(
    *,
    plan: dict[str, Any],
    strategy_signal: dict[str, Any],
    equity: float,
    cash_balance: float,
    open_positions: dict[str, dict[str, Any]],
    pending_entries: dict[str, dict[str, Any]],
    guardian_state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    risk_policy = load_production_module("risk_engine", "risk_policy")
    btc_policy = load_production_module("risk_engine", "btc_macro_policy")
    leverage_policy = load_production_module("risk_engine", "leverage_policy")
    portfolio_policy = load_production_module("risk_engine", "portfolio_policy")
    correlation_policy = load_production_module("risk_engine", "correlation_policy")
    weekly_policy = load_production_module("risk_engine", "weekly_drawdown_policy")

    entry = float(plan["entry"])
    stop = float(plan["stop"])
    side = str(plan["side"])
    stop_distance = entry - stop if side == "long" else stop - entry
    if stop_distance <= 0:
        return {"ok": False, "reason_codes": ["INVALID_STOP_DISTANCE"]}

    weekly = weekly_policy.evaluate_weekly_drawdown_threshold(
        account_state=guardian_state,
        strategy_context=strategy_signal,
        fallback_equity=equity,
        weekly_drawdown_threshold_pct=float(config.get("risk_weekly_drawdown_threshold_pct", 5.0)),
        weekly_drawdown_score_penalty=int(config.get("risk_weekly_drawdown_score_penalty", 10)),
        base_trade_score_threshold=int(config.get("risk_base_trade_score_threshold", 75)),
    )
    if not weekly.get("ok"):
        return {"ok": False, "reason_codes": weekly.get("reason_codes", []), "weekly": weekly}

    base = risk_policy.calculate_base_risk_amount(
        equity,
        max_risk_pct_ceiling=float(config.get("risk_max_risk_pct", 1.0)),
    )
    btc = btc_policy.evaluate_btc_macro_risk_adjustment(
        payload=strategy_signal,
        base_risk_amount=float(base["risk_amount"]),
    )
    risk_amount = float(btc["adjusted_risk_amount"])
    quantity = risk_amount / stop_distance
    notional = quantity * entry
    minimum_notional = equity * float(config.get("risk_max_leverage", 15.0)) * (
        float(config.get("risk_min_notional_pct_of_max_deployable", 1.0)) / 100.0
    )
    if quantity <= 0:
        return {"ok": False, "reason_codes": ["SIZE_NON_POSITIVE"], "base_risk": base, "btc_macro": btc}
    if notional < minimum_notional:
        return {"ok": False, "reason_codes": ["NOTIONAL_BELOW_MINIMUM"], "notional": notional, "minimum_notional": minimum_notional}

    leverage = leverage_policy.select_safe_leverage(
        side=side,
        entry=entry,
        stop=stop,
        notional=notional,
        cash_balance=cash_balance,
        max_leverage=float(config.get("risk_max_leverage", 15.0)),
        min_liquidation_buffer_pct=float(config.get("risk_min_liquidation_buffer_pct", 0.35)),
        leverage_sequence=config.get("risk_leverage_sequence") or [15, 14, 13, 12, 11, 10, 9, 8, 7],
    )
    if not leverage.get("ok"):
        return {"ok": False, "reason_codes": [leverage.get("reason", "NO_VALID_LEVERAGE_FOUND")], "leverage": leverage}

    open_items = _open_items(open_positions)
    pending_items = _pending_items(pending_entries)
    portfolio = portfolio_policy.evaluate_portfolio_constraints(
        symbol=plan["symbol"],
        side=side,
        new_notional=notional,
        new_margin_required=float(leverage["margin_required"]),
        equity=equity,
        cash_balance=cash_balance,
        open_positions=open_items,
        pending_entries=pending_items,
        max_open_positions=int(config.get("risk_max_open_positions", 5)),
        max_pending_entries=int(config.get("risk_max_pending_entries", 5)),
        max_total_entries=int(config.get("risk_max_total_active_entries", 5)),
        max_directional_entries=int(config.get("risk_max_directional_entries", 4)),
        max_portfolio_notional_multiple=float(config.get("risk_max_portfolio_notional_multiple", 10.0)),
        max_margin_usage_pct=float(config.get("risk_max_margin_usage_pct", 80.0)),
    )
    if not portfolio.get("ok"):
        return {"ok": False, "reason_codes": portfolio.get("reason_codes", []), "portfolio": portfolio}

    correlation = correlation_policy.evaluate_correlation_constraints(
        symbol=plan["symbol"],
        side=side,
        open_positions=open_items,
        pending_entries=pending_items,
        symbol_universe=None,
        max_correlated_entries=int(config.get("risk_max_correlated_entries", 2)),
    )
    if not correlation.get("ok"):
        return {"ok": False, "reason_codes": correlation.get("reason_codes", []), "correlation": correlation}

    return {
        "ok": True,
        "version": BACKTEST_PRODUCTION_RISK_VERSION,
        "quantity": round(quantity, 8),
        "notional": round(notional, 8),
        "risk_amount": round(risk_amount, 8),
        "risk_pct": float(base["risk_pct"]),
        "leverage": float(leverage["chosen_leverage"]),
        "margin_required": float(leverage["margin_required"]),
        "liquidation_price_estimate": leverage["liquidation_price_estimate"],
        "base_risk": base,
        "btc_macro": btc,
        "weekly_drawdown": weekly,
        "portfolio": portfolio,
        "correlation": correlation,
    }
