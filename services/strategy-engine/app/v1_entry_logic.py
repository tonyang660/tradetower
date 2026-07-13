"""
Phase 4 Step 5 — v1 trend-following and mean-reversion entry validation.

This module ports v1 trend-following long/short entry checks to the
MarketSnapshot v2 adapter layer.

It does not score signals, calculate SL/TP, size positions, or execute trades.
Mean-reversion validation is included as of Phase 4 Step 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from v1_history_access import get_history_values, is_decreasing, is_increasing, latest_from_history

from snapshot_v1_adapter import (
    direction_bias,
    get_bos_for_direction,
    get_indicator,
    get_mean_reversion_range,
    get_regime_value,
    get_structure_value,
    get_volatility_value,
    latest_close,
    safe_float,
    validate_snapshot_for_strategy,
    v1_trend_direction,
)

TREND_ENTRY_VALIDATOR_VERSION = "phase4_step11_v1_entry_validation_history"

VOLATILITY_MIN_RATIO = 0.7
VOLATILITY_MAX_RATIO = 2.0
PRICE_NEAR_EMA_FAST_PCT = 0.002
SWING_PROXIMITY_ATR_MULTIPLIER = 0.5


@dataclass(frozen=True)
class EntryValidationResult:
    valid: bool
    direction: str
    strategy_type: str
    reason: str
    failed_conditions: list[str]
    passed_conditions: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "validator_version": TREND_ENTRY_VALIDATOR_VERSION,
            "direction": self.direction,
            "strategy_type": self.strategy_type,
            "reason": self.reason,
            "failed_conditions": self.failed_conditions,
            "passed_conditions": self.passed_conditions,
            "details": self.details,
        }


def _result(
    valid: bool,
    direction: str,
    reason: str,
    failed_conditions: list[str] | None = None,
    passed_conditions: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return EntryValidationResult(
        valid=valid,
        direction=direction,
        strategy_type="trend_following",
        reason=reason,
        failed_conditions=failed_conditions or [],
        passed_conditions=passed_conditions or [],
        details=details or {},
    ).to_dict()


def _trend_to_v1(value: str | None) -> str:
    value = str(value or "").lower()
    if value in ("bullish", "up", "long"):
        return "bullish"
    if value in ("bearish", "down", "short"):
        return "bearish"
    return "neutral"


def _macd_hist(snapshot: dict[str, Any], role: str) -> float:
    return safe_float(
        get_indicator(
            snapshot,
            role,
            "macd_hist",
            get_indicator(snapshot, role, "macd_histogram", 0.0),
        )
    )


def _macd_slope(snapshot: dict[str, Any], role: str) -> float:
    return safe_float(get_indicator(snapshot, role, "macd_histogram_slope", 0.0))


def _atr_ratio(snapshot: dict[str, Any]) -> float:
    ratio = get_volatility_value(snapshot, "primary", "atr_ratio")
    if ratio is not None:
        return safe_float(ratio, 0.0)

    atr = safe_float(get_indicator(snapshot, "primary", "atr_14", get_indicator(snapshot, "primary", "atr", 0.0)))
    atr_sma = safe_float(get_indicator(snapshot, "primary", "atr_sma_20", get_indicator(snapshot, "primary", "atr_sma", 0.0)))
    if atr_sma == 0:
        return 0.0
    return atr / atr_sma


def _primary_atr(snapshot: dict[str, Any]) -> float:
    return safe_float(
        get_indicator(
            snapshot,
            "primary",
            "atr_14",
            get_indicator(snapshot, "primary", "atr", get_volatility_value(snapshot, "primary", "atr", 0.0)),
        )
    )


def _entry_price_near_ema_fast(snapshot: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    current_price = latest_close(snapshot, "entry")
    ema_fast = safe_float(
        get_indicator(
            snapshot,
            "entry",
            "ema_fast",
            get_indicator(snapshot, "entry", "ema_21", 0.0),
        )
    )

    if current_price <= 0 or ema_fast <= 0:
        return False, {
            "current_price": current_price,
            "ema_fast": ema_fast,
            "distance_pct": None,
        }

    distance_pct = abs(current_price - ema_fast) / ema_fast
    return distance_pct <= PRICE_NEAR_EMA_FAST_PCT, {
        "current_price": current_price,
        "ema_fast": ema_fast,
        "distance_pct": round(distance_pct, 6),
        "max_distance_pct": PRICE_NEAR_EMA_FAST_PCT,
    }


def _fast_rally_override(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    key = "fast_rally_long" if direction == "long" else "fast_rally_short"
    rally = get_regime_value(snapshot, "primary", key, {}) or {}

    detected = bool(rally.get("detected", False))
    strength = str(rally.get("strength", "none"))

    velocity = get_regime_value(snapshot, "primary", "price_velocity", {}) or {}
    velocity_short = safe_float(rally.get("velocity_short", velocity.get("short_6_bars", 0.0)))
    velocity_medium = safe_float(rally.get("velocity_medium", velocity.get("medium_12_bars", 0.0)))

    primary_trend = _trend_to_v1(v1_trend_direction(snapshot, "primary"))
    strong_primary = (
        primary_trend == "bullish" if direction == "long" else primary_trend == "bearish"
    )

    return detected and strong_primary, {
        "detected": detected,
        "strength": strength,
        "velocity_short": velocity_short,
        "velocity_medium": velocity_medium,
        "primary_trend": primary_trend,
        "strong_primary": strong_primary,
    }


def _is_too_close_to_swing(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    current_price = latest_close(snapshot, "entry")
    atr = _primary_atr(snapshot)

    if current_price <= 0 or atr <= 0:
        return False, {
            "current_price": current_price,
            "atr": atr,
            "swing_level": None,
            "distance": None,
        }

    if direction == "long":
        swing_level = safe_float(get_structure_value(snapshot, "primary", "swing_low", 0.0))
        label = "swing_low"
    else:
        swing_level = safe_float(get_structure_value(snapshot, "primary", "swing_high", 0.0))
        label = "swing_high"

    if swing_level <= 0:
        return False, {
            "current_price": current_price,
            "atr": atr,
            "swing_level": None,
            "swing_label": label,
            "distance": None,
        }

    distance = abs(current_price - swing_level)
    threshold = SWING_PROXIMITY_ATR_MULTIPLIER * atr

    return distance < threshold, {
        "current_price": current_price,
        "atr": atr,
        "swing_level": swing_level,
        "swing_label": label,
        "distance": round(distance, 8),
        "threshold": round(threshold, 8),
    }


def _entry_macd_turns(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    macd_tail = get_history_values(snapshot, "entry", "macd_hist", tail_size=2)
    hist = macd_tail[-1] if macd_tail else _macd_hist(snapshot, "entry")
    prev = macd_tail[-2] if len(macd_tail) >= 2 else hist - _macd_slope(snapshot, "entry")

    if direction == "long":
        ok = hist > prev
        reason = "5M_MACD_TURNING_UP" if ok else "5M_MACD_NOT_TURNING_UP"
    else:
        ok = hist < prev
        reason = "5M_MACD_TURNING_DOWN" if ok else "5M_MACD_NOT_TURNING_DOWN"

    return ok, {
        "macd_hist": hist,
        "macd_hist_prev": prev,
        "macd_hist_tail": macd_tail,
        "reason": reason,
    }

def _primary_macd_strength(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    macd_tail = get_history_values(snapshot, "primary", "macd_hist", tail_size=3)
    hist = macd_tail[-1] if macd_tail else _macd_hist(snapshot, "primary")
    slope = hist - macd_tail[-2] if len(macd_tail) >= 2 else _macd_slope(snapshot, "primary")

    if direction == "long":
        if hist <= 0:
            return False, {"reason": "MACD_HISTOGRAM_NOT_POSITIVE", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
        if len(macd_tail) >= 3 and macd_tail[-1] < macd_tail[-2]:
            return False, {"reason": "MACD_MOMENTUM_DECLINING", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
        if len(macd_tail) >= 3 and abs(macd_tail[-1]) < abs(macd_tail[-3]) * 0.5:
            return False, {"reason": "MACD_MOMENTUM_TOO_WEAK", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
        return True, {"reason": "MACD_MOMENTUM_SUPPORTS_LONG", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}

    if hist >= 0:
        return False, {"reason": "MACD_HISTOGRAM_NOT_NEGATIVE", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
    if len(macd_tail) >= 3 and macd_tail[-1] > macd_tail[-2]:
        return False, {"reason": "MACD_MOMENTUM_NOT_DECLINING", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
    if len(macd_tail) >= 3 and abs(macd_tail[-1]) < abs(macd_tail[-3]) * 0.5:
        return False, {"reason": "MACD_MOMENTUM_TOO_WEAK", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}
    return True, {"reason": "MACD_MOMENTUM_SUPPORTS_SHORT", "macd_hist": hist, "slope": slope, "macd_hist_tail": macd_tail}

def _check_common_trend_conditions(snapshot: dict[str, Any], direction: str) -> tuple[list[str], list[str], dict[str, Any]]:
    failed: list[str] = []
    passed: list[str] = []
    details: dict[str, Any] = {}

    valid_snapshot, snapshot_reasons = validate_snapshot_for_strategy(snapshot)
    details["snapshot_validation"] = {
        "valid": valid_snapshot,
        "reasons": snapshot_reasons,
    }
    if not valid_snapshot:
        failed.extend(snapshot_reasons)
        return failed, passed, details
    passed.append("SNAPSHOT_READY_FOR_STRATEGY")

    htf_trend = _trend_to_v1(v1_trend_direction(snapshot, "htf"))
    primary_trend = _trend_to_v1(v1_trend_direction(snapshot, "primary"))
    details["htf_trend"] = htf_trend
    details["primary_trend"] = primary_trend

    if direction == "long":
        if htf_trend == "bearish":
            failed.append("HTF_TREND_BEARISH_OPPOSES_LONG")
        elif htf_trend == "neutral":
            override_ok, override_details = _fast_rally_override(snapshot, direction)
            details["fast_rally_override"] = override_details
            if not override_ok:
                failed.append("HTF_NEUTRAL_WITHOUT_FAST_RALLY_CONFIRMATION")
            else:
                passed.append("HTF_NEUTRAL_FAST_RALLY_OVERRIDE")
        else:
            passed.append("HTF_BULLISH_OR_ACCEPTABLE")

        if primary_trend != "bullish":
            failed.append(f"PRIMARY_TREND_NOT_BULLISH:{primary_trend}")
        else:
            passed.append("PRIMARY_TREND_BULLISH")

    else:
        if htf_trend == "bullish":
            failed.append("HTF_TREND_BULLISH_OPPOSES_SHORT")
        elif htf_trend == "neutral":
            override_ok, override_details = _fast_rally_override(snapshot, direction)
            details["fast_correction_override"] = override_details
            if not override_ok:
                failed.append("HTF_NEUTRAL_WITHOUT_FAST_CORRECTION_CONFIRMATION")
            else:
                passed.append("HTF_NEUTRAL_FAST_CORRECTION_OVERRIDE")
        else:
            passed.append("HTF_BEARISH_OR_ACCEPTABLE")

        if primary_trend != "bearish":
            failed.append(f"PRIMARY_TREND_NOT_BEARISH:{primary_trend}")
        else:
            passed.append("PRIMARY_TREND_BEARISH")

    atr_ratio = _atr_ratio(snapshot)
    details["atr_ratio"] = atr_ratio
    details["volatility_min_ratio"] = VOLATILITY_MIN_RATIO
    details["volatility_max_ratio"] = VOLATILITY_MAX_RATIO

    if atr_ratio <= 0:
        failed.append("INVALID_ATR_DATA")
    elif atr_ratio < VOLATILITY_MIN_RATIO:
        failed.append(f"ATR_TOO_LOW:{atr_ratio:.2f}")
    elif atr_ratio > VOLATILITY_MAX_RATIO:
        failed.append(f"ATR_TOO_HIGH:{atr_ratio:.2f}")
    else:
        passed.append("ATR_RATIO_WITHIN_V1_LIMITS")

    momentum_ok, momentum_details = _primary_macd_strength(snapshot, direction)
    details["primary_macd"] = momentum_details
    if not momentum_ok:
        failed.append(momentum_details["reason"])
    else:
        passed.append(momentum_details["reason"])

    near_ema_ok, near_ema_details = _entry_price_near_ema_fast(snapshot)
    details["entry_near_ema_fast"] = near_ema_details
    if not near_ema_ok:
        failed.append("PRICE_NOT_NEAR_EMA_FAST")
    else:
        passed.append("PRICE_NEAR_EMA_FAST")

    too_close, swing_details = _is_too_close_to_swing(snapshot, direction)
    details["swing_proximity"] = swing_details
    if too_close:
        if direction == "long":
            failed.append("TOO_CLOSE_TO_SWING_LOW_SUPPORT")
        else:
            failed.append("TOO_CLOSE_TO_SWING_HIGH_RESISTANCE")
    else:
        passed.append("NOT_TOO_CLOSE_TO_INVALIDATING_SWING")

    entry_macd_ok, entry_macd_details = _entry_macd_turns(snapshot, direction)
    details["entry_macd"] = entry_macd_details
    if not entry_macd_ok:
        failed.append(entry_macd_details["reason"])
    else:
        passed.append(entry_macd_details["reason"])

    # Diagnostic only: the v1 trend entry validator does not require BOS, but
    # exposing it helps Step 6 scoring consume the same validation context.
    details["bos"] = get_bos_for_direction(snapshot, direction, "primary")
    details["mean_reversion_range"] = get_mean_reversion_range(snapshot, "primary")
    details["primary_direction_bias"] = direction_bias(snapshot, "primary")
    details["htf_direction_bias"] = direction_bias(snapshot, "htf")

    return failed, passed, details


def check_trend_following_long(snapshot: dict[str, Any]) -> dict[str, Any]:
    failed, passed, details = _check_common_trend_conditions(snapshot, "long")
    if failed:
        return _result(
            valid=False,
            direction="long",
            reason=failed[0],
            failed_conditions=failed,
            passed_conditions=passed,
            details=details,
        )

    return _result(
        valid=True,
        direction="long",
        reason="All v1 trend-following long entry conditions met",
        passed_conditions=passed,
        details=details,
    )


def check_trend_following_short(snapshot: dict[str, Any]) -> dict[str, Any]:
    failed, passed, details = _check_common_trend_conditions(snapshot, "short")
    if failed:
        return _result(
            valid=False,
            direction="short",
            reason=failed[0],
            failed_conditions=failed,
            passed_conditions=passed,
            details=details,
        )

    return _result(
        valid=True,
        direction="short",
        reason="All v1 trend-following short entry conditions met",
        passed_conditions=passed,
        details=details,
    )


def check_trend_following_entry(snapshot: dict[str, Any], direction: str) -> dict[str, Any]:
    direction = str(direction or "").lower()
    if direction == "long":
        return check_trend_following_long(snapshot)
    if direction == "short":
        return check_trend_following_short(snapshot)

    return _result(
        valid=False,
        direction="neutral",
        reason="Invalid trend-following direction",
        failed_conditions=["INVALID_DIRECTION"],
        details={"direction": direction},
    )



def _primary_regime(snapshot: dict[str, Any]) -> str:
    return str(get_regime_value(snapshot, "primary", "v1_regime", "unknown") or "unknown")


def _rsi_confirmation(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    rsi_tail = get_history_values(snapshot, "primary", "rsi", tail_size=2)
    rsi = rsi_tail[-1] if rsi_tail else safe_float(get_indicator(snapshot, "primary", "rsi_14", get_indicator(snapshot, "primary", "rsi", 50.0)), 50.0)
    rsi_prev = rsi_tail[-2] if len(rsi_tail) >= 2 else rsi

    if direction == "long":
        ok = rsi > rsi_prev and rsi <= 48
        reason = "RSI_BULLISH_CONFIRMATION" if ok else "RSI_NOT_BULLISH_CONFIRMATION"
    else:
        ok = rsi < rsi_prev and rsi >= 52
        reason = "RSI_BEARISH_CONFIRMATION" if ok else "RSI_NOT_BEARISH_CONFIRMATION"

    return ok, {
        "rsi": rsi,
        "rsi_prev": rsi_prev,
        "rsi_tail": rsi_tail,
        "reason": reason,
    }

def _mean_reversion_zone(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    current_price = latest_close(snapshot, "entry")
    atr = _primary_atr(snapshot)
    range_info = get_mean_reversion_range(snapshot, "primary") or {}

    support = safe_float(range_info.get("support"), 0.0)
    resistance = safe_float(range_info.get("resistance"), 0.0)
    range_width = resistance - support

    details = {
        "current_price": current_price,
        "atr": atr,
        "range_info": range_info,
        "support": support,
        "resistance": resistance,
        "range_width": range_width,
    }

    if not range_info.get("valid"):
        details["reason"] = range_info.get("reason", "range not safe")
        return False, details

    if current_price <= 0 or atr <= 0 or support <= 0 or resistance <= 0 or range_width <= 0:
        details["reason"] = "invalid_range_or_price_data"
        return False, details

    if direction == "long":
        zone_bottom = support - (0.15 * atr)
        zone_top = support + min(0.25 * range_width, 0.8 * atr)
        ok = zone_bottom <= current_price <= zone_top
        details.update({
            "zone": "support",
            "zone_bottom": zone_bottom,
            "zone_top": zone_top,
            "in_zone": ok,
        })
        return ok, details

    zone_top = resistance + (0.15 * atr)
    zone_bottom = resistance - min(0.25 * range_width, 0.8 * atr)
    ok = zone_bottom <= current_price <= zone_top
    details.update({
        "zone": "resistance",
        "zone_bottom": zone_bottom,
        "zone_top": zone_top,
        "in_zone": ok,
    })
    return ok, details


def _mean_reversion_macd_turn(snapshot: dict[str, Any], direction: str) -> tuple[bool, dict[str, Any]]:
    macd_tail = get_history_values(snapshot, "entry", "macd_hist", tail_size=2)
    hist = macd_tail[-1] if macd_tail else _macd_hist(snapshot, "entry")
    prev = macd_tail[-2] if len(macd_tail) >= 2 else hist - _macd_slope(snapshot, "entry")

    if direction == "long":
        ok = hist > prev
        reason = "MR_5M_MACD_TURNING_UP" if ok else "MR_5M_MACD_NOT_TURNING_UP"
    else:
        ok = hist < prev
        reason = "MR_5M_MACD_TURNING_DOWN" if ok else "MR_5M_MACD_NOT_TURNING_DOWN"

    return ok, {
        "macd_hist": hist,
        "macd_hist_prev": prev,
        "macd_hist_tail": macd_tail,
        "reason": reason,
    }

def _check_common_mean_reversion_conditions(snapshot: dict[str, Any], direction: str) -> tuple[list[str], list[str], dict[str, Any]]:
    failed: list[str] = []
    passed: list[str] = []
    details: dict[str, Any] = {}

    valid_snapshot, snapshot_reasons = validate_snapshot_for_strategy(snapshot)
    details["snapshot_validation"] = {
        "valid": valid_snapshot,
        "reasons": snapshot_reasons,
    }
    if not valid_snapshot:
        failed.extend(snapshot_reasons)
        return failed, passed, details
    passed.append("SNAPSHOT_READY_FOR_STRATEGY")

    regime = _primary_regime(snapshot)
    details["primary_regime"] = regime
    if regime != "Sideways":
        failed.append("MR_NOT_SIDEWAYS_REGIME")
    else:
        passed.append("MR_SIDEWAYS_REGIME_CONFIRMED")

    zone_ok, zone_details = _mean_reversion_zone(snapshot, direction)
    details["mean_reversion_zone"] = zone_details
    if not zone_ok:
        if not zone_details.get("range_info", {}).get("valid"):
            failed.append("MR_BREAKOUT_RISK_TOO_HIGH")
        elif direction == "long":
            failed.append("MR_PRICE_NOT_IN_SUPPORT_ZONE")
        else:
            failed.append("MR_PRICE_NOT_IN_RESISTANCE_ZONE")
    else:
        if direction == "long":
            passed.append("MR_PRICE_IN_SUPPORT_ZONE")
        else:
            passed.append("MR_PRICE_IN_RESISTANCE_ZONE")

    rsi_ok, rsi_details = _rsi_confirmation(snapshot, direction)
    details["rsi_confirmation"] = rsi_details
    if not rsi_ok:
        failed.append(rsi_details["reason"])
    else:
        passed.append(rsi_details["reason"])

    macd_ok, macd_details = _mean_reversion_macd_turn(snapshot, direction)
    details["entry_macd"] = macd_details
    if not macd_ok:
        failed.append(macd_details["reason"])
    else:
        passed.append(macd_details["reason"])

    details["primary_direction_bias"] = direction_bias(snapshot, "primary")
    details["htf_direction_bias"] = direction_bias(snapshot, "htf")

    return failed, passed, details


def check_mean_reversion_long(snapshot: dict[str, Any]) -> dict[str, Any]:
    failed, passed, details = _check_common_mean_reversion_conditions(snapshot, "long")
    if failed:
        return EntryValidationResult(
            valid=False,
            direction="long",
            strategy_type="mean_reversion",
            reason=failed[0],
            failed_conditions=failed,
            passed_conditions=passed,
            details=details,
        ).to_dict()

    support = details.get("mean_reversion_zone", {}).get("support")
    return EntryValidationResult(
        valid=True,
        direction="long",
        strategy_type="mean_reversion",
        reason=f"Mean-reversion long triggered near contained support {support}",
        failed_conditions=[],
        passed_conditions=passed,
        details=details,
    ).to_dict()


def check_mean_reversion_short(snapshot: dict[str, Any]) -> dict[str, Any]:
    failed, passed, details = _check_common_mean_reversion_conditions(snapshot, "short")
    if failed:
        return EntryValidationResult(
            valid=False,
            direction="short",
            strategy_type="mean_reversion",
            reason=failed[0],
            failed_conditions=failed,
            passed_conditions=passed,
            details=details,
        ).to_dict()

    resistance = details.get("mean_reversion_zone", {}).get("resistance")
    return EntryValidationResult(
        valid=True,
        direction="short",
        strategy_type="mean_reversion",
        reason=f"Mean-reversion short triggered near contained resistance {resistance}",
        failed_conditions=[],
        passed_conditions=passed,
        details=details,
    ).to_dict()


def check_mean_reversion_entry(snapshot: dict[str, Any], direction: str) -> dict[str, Any]:
    direction = str(direction or "").lower()
    if direction == "long":
        return check_mean_reversion_long(snapshot)
    if direction == "short":
        return check_mean_reversion_short(snapshot)

    return EntryValidationResult(
        valid=False,
        direction="neutral",
        strategy_type="mean_reversion",
        reason="Invalid mean-reversion direction",
        failed_conditions=["INVALID_DIRECTION"],
        passed_conditions=[],
        details={"direction": direction},
    ).to_dict()


def check_v1_entry(snapshot: dict[str, Any], strategy_type: str, direction: str) -> dict[str, Any]:
    strategy_type = str(strategy_type or "").lower()
    if strategy_type == "trend_following":
        return check_trend_following_entry(snapshot, direction)
    if strategy_type == "mean_reversion":
        return check_mean_reversion_entry(snapshot, direction)

    return EntryValidationResult(
        valid=False,
        direction=str(direction or "neutral").lower(),
        strategy_type=strategy_type or "none",
        reason="Invalid strategy type",
        failed_conditions=["INVALID_STRATEGY_TYPE"],
        passed_conditions=[],
        details={"strategy_type": strategy_type, "direction": direction},
    ).to_dict()

def build_entry_validation_contract() -> dict[str, Any]:
    return {
        "validator_version": TREND_ENTRY_VALIDATOR_VERSION,
        "strategy_types": ["trend_following", "mean_reversion"],
        "v1_source": "src/strategy/entry_logic.py",
        "ported_trend_conditions": [
            "HTF bias filter with neutral fast-rally/correction override",
            "ATR ratio min/max filter",
            "15m primary trend alignment",
            "15m MACD histogram direction and momentum",
            "5m price near EMA fast",
            "not too close to primary swing invalidation level",
            "5m MACD turn confirmation",
        ],
        "ported_mean_reversion_conditions": [
            "15m Sideways regime confirmation",
            "valid contained mean-reversion range",
            "price inside support/resistance zone",
            "RSI reversal confirmation",
            "5m MACD turn confirmation",
        ],
        "history_parity": "uses v1_history_access tails computed from MarketSnapshot v2 candles",
        "does_not_score": True,
        "does_not_execute": True,
    }


def build_trend_entry_validation_contract() -> dict[str, Any]:
    # Backward-compatible alias from Step 4.
    return build_entry_validation_contract()
