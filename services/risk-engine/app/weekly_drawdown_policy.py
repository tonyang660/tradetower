"""
Phase 5 Step 8 — weekly drawdown score-threshold penalty.

Minimal scope by design:
- No daily kill switch changes.
- No weekly kill switch changes.
- No hot streak logic.
- No risk-size multiplier.
- No BTC macro changes.

Trade Guardian remains the owner of account/risk state and kill switches.
Risk Engine only consumes Guardian-provided weekly PnL/drawdown context and
requires a stricter Strategy score during weekly drawdown.
"""

from __future__ import annotations

from typing import Any

WEEKLY_DRAWDOWN_POLICY_VERSION = "phase5_step8_weekly_drawdown_threshold_penalty"

DEFAULT_WEEKLY_DRAWDOWN_THRESHOLD_PCT = 3.0
DEFAULT_WEEKLY_DRAWDOWN_SCORE_PENALTY = 10
DEFAULT_BASE_TRADE_SCORE_THRESHOLD = 75


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def extract_weekly_pnl(account_state: dict[str, Any] | None) -> float:
    state = account_state or {}

    for key in (
        "weekly_pnl",
        "week_pnl",
        "weekly_realized_pnl",
        "weekly_net_pnl",
        "risk_weekly_pnl",
    ):
        if state.get(key) is not None:
            return safe_float(state.get(key))

    risk_state = state.get("risk_state") or {}
    if isinstance(risk_state, dict):
        return extract_weekly_pnl(risk_state)

    return 0.0


def extract_equity(account_state: dict[str, Any] | None, fallback_equity: float = 0.0) -> float:
    state = account_state or {}

    for key in ("equity", "account_equity", "current_equity", "balance_equity"):
        if state.get(key) is not None:
            return safe_float(state.get(key), fallback_equity)

    risk_state = state.get("risk_state") or {}
    if isinstance(risk_state, dict):
        return extract_equity(risk_state, fallback_equity)

    return safe_float(fallback_equity)


def extract_strategy_score(strategy_context: dict[str, Any] | None) -> float | None:
    context = strategy_context or {}
    for key in ("score", "confidence", "strategy_score"):
        if context.get(key) is not None:
            return safe_float(context.get(key))
    return None


def calculate_weekly_pnl_pct(weekly_pnl: float, equity: float) -> float:
    equity = safe_float(equity)
    if equity <= 0:
        return 0.0
    return (safe_float(weekly_pnl) / equity) * 100.0


def evaluate_weekly_drawdown_threshold(
    *,
    account_state: dict[str, Any] | None,
    strategy_context: dict[str, Any] | None,
    fallback_equity: float,
    weekly_drawdown_threshold_pct: float = DEFAULT_WEEKLY_DRAWDOWN_THRESHOLD_PCT,
    weekly_drawdown_score_penalty: int = DEFAULT_WEEKLY_DRAWDOWN_SCORE_PENALTY,
    base_trade_score_threshold: int = DEFAULT_BASE_TRADE_SCORE_THRESHOLD,
) -> dict[str, Any]:
    weekly_pnl = extract_weekly_pnl(account_state)
    equity = extract_equity(account_state, fallback_equity)
    weekly_pnl_pct = calculate_weekly_pnl_pct(weekly_pnl, equity)

    threshold_pct = abs(safe_float(weekly_drawdown_threshold_pct))
    score_penalty = safe_int(weekly_drawdown_score_penalty)
    base_threshold = safe_int(base_trade_score_threshold)

    active = weekly_pnl_pct <= -threshold_pct
    required_score = base_threshold + score_penalty if active else base_threshold
    strategy_score = extract_strategy_score(strategy_context)

    reason_codes: list[str] = []
    if active:
        reason_codes.append("WEEKLY_DRAWDOWN_THRESHOLD_PENALTY_ACTIVE")

    allowed = True
    if active and strategy_score is not None and strategy_score < required_score:
        allowed = False
        reason_codes.append("SCORE_BELOW_WEEKLY_DRAWDOWN_THRESHOLD")

    if active and strategy_score is None:
        allowed = False
        reason_codes.append("MISSING_STRATEGY_SCORE_FOR_WEEKLY_DRAWDOWN_CHECK")

    return {
        "ok": allowed,
        "weekly_drawdown_policy_version": WEEKLY_DRAWDOWN_POLICY_VERSION,
        "active": active,
        "weekly_pnl": round(weekly_pnl, 8),
        "equity": round(equity, 8),
        "weekly_pnl_pct": round(weekly_pnl_pct, 6),
        "weekly_drawdown_threshold_pct": threshold_pct,
        "base_trade_score_threshold": base_threshold,
        "score_penalty": score_penalty if active else 0,
        "required_score": required_score,
        "strategy_score": strategy_score,
        "reason_codes": reason_codes,
        "clears_when": (
            "weekly_pnl_pct rises above negative weekly_drawdown_threshold_pct "
            "or weekly state resets at the start of a new week"
        ),
    }


def build_weekly_drawdown_policy_contract() -> dict[str, Any]:
    return {
        "weekly_drawdown_policy_version": WEEKLY_DRAWDOWN_POLICY_VERSION,
        "default_weekly_drawdown_threshold_pct": DEFAULT_WEEKLY_DRAWDOWN_THRESHOLD_PCT,
        "default_weekly_drawdown_score_penalty": DEFAULT_WEEKLY_DRAWDOWN_SCORE_PENALTY,
        "default_base_trade_score_threshold": DEFAULT_BASE_TRADE_SCORE_THRESHOLD,
        "owner_of_state": "trade_guardian",
        "risk_engine_behavior": (
            "Risk Engine consumes Guardian-provided weekly PnL/equity state and "
            "requires score >= base threshold + penalty while weekly drawdown is active."
        ),
        "not_in_scope": [
            "daily pnl kill switch",
            "weekly pnl kill switch",
            "48h cooldown",
            "stop trading for the day",
            "hot streak",
            "risk size multiplier",
            "BTC macro multiplier",
        ],
        "reason_codes": [
            "WEEKLY_DRAWDOWN_THRESHOLD_PENALTY_ACTIVE",
            "SCORE_BELOW_WEEKLY_DRAWDOWN_THRESHOLD",
            "MISSING_STRATEGY_SCORE_FOR_WEEKLY_DRAWDOWN_CHECK",
        ],
    }
