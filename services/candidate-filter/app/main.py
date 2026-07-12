from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import json
import os

import requests

try:
    from candidate_filter_contract import (
        CANDIDATE_FILTER_SCHEMA_VERSION,
        CANDIDATE_FILTER_VERSION,
        CANDIDATE_FILTER_CONTRACT_VERSION,
        CANDIDATE_FILTER_MODE,
        build_candidate_filter_contract,
    )
except Exception:
    CANDIDATE_FILTER_SCHEMA_VERSION = "candidate_filter_v2"
    CANDIDATE_FILTER_VERSION = "v2"
    CANDIDATE_FILTER_CONTRACT_VERSION = "phase3_5_step1"
    CANDIDATE_FILTER_MODE = "lenient_screener"

    def build_candidate_filter_contract() -> dict:
        return {
            "schema_version": CANDIDATE_FILTER_SCHEMA_VERSION,
            "candidate_filter_version": CANDIDATE_FILTER_VERSION,
            "contract_version": CANDIDATE_FILTER_CONTRACT_VERSION,
            "candidate_filter_mode": CANDIDATE_FILTER_MODE,
            "policy": {
                "primary_role": "Remove clearly bad symbols before Strategy Engine.",
            },
        }


SERVICE_NAME = "candidate-filter"
PORT = int(os.getenv("PORT", "8080"))
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
FEATURE_FACTORY_BASE_URL = os.getenv("FEATURE_FACTORY_BASE_URL", "http://feature-factory:8080")
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "25"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "40"))
REQUIRED_TIMEFRAMES = [
    tf.strip()
    for tf in os.getenv("CANDIDATE_FILTER_REQUIRED_TIMEFRAMES", "5m,15m,1h,4h").split(",")
    if tf.strip()
]
CANDIDATE_FILTER_RUNTIME_VERSION = "phase3_5_step3_lenient_v2_scoring"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_linear(value: float, low: float, high: float, max_points: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return max_points
    return ((value - low) / (high - low)) * max_points


def score_inverse(value: float, best_low: float, worst_high: float, max_points: float) -> float:
    if value <= best_low:
        return max_points
    if value >= worst_high:
        return 0.0
    return ((worst_high - value) / (worst_high - best_low)) * max_points


def zero_sub_scores() -> dict:
    return {
        "bias_alignment": 0.0,
        "momentum": 0.0,
        "setup": 0.0,
        "execution": 0.0,
        "volatility": 0.0,
    }


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_get_tf(snapshot: dict, tf: str):
    return snapshot.get("timeframes", {}).get(tf, {})


def safe_get_indicators(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("indicators", {})


def safe_get_structure(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("structure", {})


def safe_get_price_action(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("price_action", {})


def safe_get_volatility(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("volatility", {})


def build_versions_payload() -> dict:
    return {
        "schema_version": CANDIDATE_FILTER_SCHEMA_VERSION,
        "candidate_filter_version": CANDIDATE_FILTER_VERSION,
        "contract_version": CANDIDATE_FILTER_CONTRACT_VERSION,
        "runtime_version": CANDIDATE_FILTER_RUNTIME_VERSION,
        "candidate_filter_mode": CANDIDATE_FILTER_MODE,
        "required_timeframes": REQUIRED_TIMEFRAMES,
        "scoring_model": "market_snapshot_v2_lenient_step3",
        "score_buckets": {
            "mtf_context": 20,
            "regime_usability": 20,
            "momentum_activity": 20,
            "setup_location": 20,
            "volatility_usability": 20,
        },
        "contract": build_candidate_filter_contract(),
    }


def build_unavailable_item(
    symbol: str,
    reason: str,
    details=None,
    snapshot_data_quality: dict | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "candidate_score": 0.0,
        "candidate_tier": "unavailable",
        "candidate_bias": "neutral",
        "candidate_status": "unavailable",
        "reject_reason": reason,
        "sub_scores": zero_sub_scores(),
        "reason_tags": [reason],
        "strategy_path_hints": {
            "trend_following_possible": False,
            "mean_reversion_possible": False,
        },
        "snapshot_refs": {
            "snapshot_schema_version": None,
            "data_quality": snapshot_data_quality or {},
        },
        "details": details or {},
    }


def build_rejected_item(
    symbol: str,
    reason: str,
    score: float = 0.0,
    bias: str = "neutral",
    sub_scores: dict | None = None,
    extra_reasons: list[str] | None = None,
) -> dict:
    reasons = [reason]
    if extra_reasons:
        reasons.extend(extra_reasons)

    return {
        "symbol": symbol,
        "candidate_score": score,
        "candidate_tier": "rejected",
        "candidate_bias": bias,
        "candidate_status": "rejected",
        "reject_reason": reason,
        "sub_scores": sub_scores or zero_sub_scores(),
        "reason_tags": reasons,
        "strategy_path_hints": {
            "trend_following_possible": False,
            "mean_reversion_possible": False,
        },
        "snapshot_refs": {},
    }


def tier_for_score(score: float) -> str:
    if score >= 70:
        return "strong_candidate"
    if score >= 50:
        return "candidate"
    return "weak_candidate"


def fetch_snapshot(symbol: str):
    try:
        response = requests.get(
            f"{FEATURE_FACTORY_BASE_URL}/snapshot",
            params={"symbol": symbol},
            timeout=20,
        )
        payload = response.json()
    except Exception as e:
        return None, {
            "reason": "SNAPSHOT_UNAVAILABLE",
            "details": {"error": f"feature_factory_request_failed: {str(e)}"},
        }

    if response.status_code != 200:
        return None, {
            "reason": "SNAPSHOT_UNAVAILABLE",
            "details": {
                "http_status": response.status_code,
                "feature_factory_error": payload.get("error", "feature_factory_error"),
                "feature_factory_reason_codes": payload.get("reason_codes", []),
                "data_quality": payload.get("data_quality", {}),
            },
        }

    return payload, None


def validate_snapshot_data_quality(snapshot: dict) -> dict | None:
    if snapshot.get("schema_version") != "market_snapshot_v2":
        return {
            "reason": "UNEXPECTED_SNAPSHOT_SCHEMA_VERSION",
            "details": {
                "actual_schema_version": snapshot.get("schema_version"),
                "expected_schema_version": "market_snapshot_v2",
            },
        }

    top_quality = snapshot.get("data_quality", {}) or {}
    if top_quality.get("healthy") is False:
        return {
            "reason": "MARKET_DATA_UNHEALTHY",
            "details": {
                "reason_codes": top_quality.get("reason_codes", []),
                "data_quality": top_quality,
            },
        }

    timeframes = snapshot.get("timeframes", {}) or {}
    missing = [tf for tf in REQUIRED_TIMEFRAMES if tf not in timeframes]
    if missing:
        return {
            "reason": "MISSING_REQUIRED_TIMEFRAME",
            "details": {
                "missing_timeframes": missing,
                "required_timeframes": REQUIRED_TIMEFRAMES,
            },
        }

    unhealthy_timeframes = []
    for tf in REQUIRED_TIMEFRAMES:
        tf_quality = timeframes.get(tf, {}).get("data_quality", {}) or {}
        if tf_quality.get("healthy") is False:
            unhealthy_timeframes.append({
                "timeframe": tf,
                "reason_codes": tf_quality.get("reason_codes", []),
                "data_quality": tf_quality,
            })

    if unhealthy_timeframes:
        return {
            "reason": "MARKET_DATA_UNHEALTHY",
            "details": {
                "unhealthy_timeframes": unhealthy_timeframes,
            },
        }

    return None


def has_open_position(account_id: int, symbol: str):
    try:
        response = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/position/open",
            params={"account_id": account_id, "symbol": symbol},
            timeout=10,
        )
        payload = response.json()
    except Exception:
        return False, "trade_guardian_request_failed"

    if payload.get("ok"):
        return True, None

    if payload.get("error") == "open_position_not_found":
        return False, None

    return False, payload.get("error", "trade_guardian_error")


def safe_get_regime_inputs(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("regime_inputs", {})


def safe_get_mtf_context(snapshot: dict):
    return snapshot.get("multi_timeframe_context", {}) or {}


def safe_get_latest(snapshot: dict, tf: str):
    return safe_get_tf(snapshot, tf).get("latest", {})


def v1_trend_to_bias(value: str | None) -> str:
    if value in ("bullish", "up", "long"):
        return "long"
    if value in ("bearish", "down", "short"):
        return "short"
    return "neutral"


def determine_bias(snapshot: dict) -> str:
    """
    V2 lenient bias inference.

    This is not final long/short decision logic. It simply gives Strategy Engine
    a candidate-side hint when the snapshot has enough contextual evidence.
    """
    mtf = safe_get_mtf_context(snapshot)
    alignment = mtf.get("alignment", {}) or {}
    consensus = alignment.get("consensus")
    if consensus in ("long", "short"):
        return consensus

    role_context = mtf.get("role_context", {}) or {}
    primary_role = role_context.get("primary", {}) or {}
    htf_role = role_context.get("higher_timeframe", {}) or {}

    primary_bias = primary_role.get("direction_bias")
    htf_bias = htf_role.get("direction_bias")
    if primary_bias in ("long", "short") and primary_bias == htf_bias:
        return primary_bias

    s15 = safe_get_structure(snapshot, "15m")
    i15 = safe_get_indicators(snapshot, "15m")
    regime15 = safe_get_regime_inputs(snapshot, "15m")

    range_info = s15.get("mean_reversion_range", {}) or {}
    if range_info.get("valid"):
        position = safe_float(range_info.get("position"), 0.5)
        rsi = safe_float(i15.get("rsi"), 50.0)

        if position <= 0.30 and rsi <= 52:
            return "long"
        if position >= 0.70 and rsi >= 48:
            return "short"

    trend = (
        s15.get("v1_trend_direction")
        or regime15.get("trend_direction")
        or s15.get("trend_direction")
    )
    return v1_trend_to_bias(trend)


def score_mtf_context(snapshot: dict) -> tuple[float, str]:
    mtf = safe_get_mtf_context(snapshot)
    alignment = mtf.get("alignment", {}) or {}

    score = 0.0
    reasons = []

    alignment_score = safe_float(alignment.get("alignment_score"), 0.0)
    score += score_linear(alignment_score, 20, 90, 12)

    consensus = alignment.get("consensus")
    if consensus in ("long", "short"):
        score += 4
        reasons.append("MTF_CONSENSUS_DIRECTION")
    elif consensus == "mixed":
        score += 2
        reasons.append("MTF_MIXED_BUT_REVIEWABLE")
    else:
        reasons.append("MTF_NEUTRAL")

    if alignment.get("entry_primary_aligned"):
        score += 2
    if alignment.get("primary_htf_aligned"):
        score += 2

    conflict_flags = alignment.get("conflict_flags", []) or []
    if "ENTRY_CONFLICTS_WITH_HTF" in conflict_flags:
        score -= 3
        reasons.append("ENTRY_CONFLICTS_WITH_HTF")

    score = clamp(score, 0.0, 20.0)
    return score, "MTF_CONTEXT_OK" if score >= 10 else reasons[0] if reasons else "MTF_CONTEXT_WEAK"


def score_regime_usability(snapshot: dict) -> tuple[float, str]:
    primary = safe_get_regime_inputs(snapshot, "15m")
    htf = safe_get_regime_inputs(snapshot, "4h")
    s15 = safe_get_structure(snapshot, "15m")

    score = 0.0
    regime = primary.get("v1_regime")
    strategy = primary.get("v1_regime_strategy")

    if regime in ("Uptrend", "Downtrend"):
        score += 8
    elif regime == "Sideways":
        score += 7
    else:
        score += 4

    if strategy in ("Trend-Following", "Mean-Reversion"):
        score += 4

    if htf.get("v1_regime") == regime and regime in ("Uptrend", "Downtrend"):
        score += 3

    range_info = s15.get("mean_reversion_range", {}) or {}
    if range_info.get("valid"):
        score += 5

    # Candidate Filter is lenient: non-ideal regimes are lower score, not hard rejects.
    score = clamp(score, 0.0, 20.0)
    return score, "REGIME_USABLE" if score >= 10 else "REGIME_WEAK_BUT_REVIEWABLE"


def score_momentum_activity(snapshot: dict, bias: str) -> tuple[float, str]:
    i15 = safe_get_indicators(snapshot, "15m")
    i5 = safe_get_indicators(snapshot, "5m")
    pa15 = safe_get_price_action(snapshot, "15m")
    regime15 = safe_get_regime_inputs(snapshot, "15m")

    score = 0.0

    macd15 = safe_float(i15.get("macd_histogram", i15.get("macd_hist", 0.0)))
    macd15_slope = safe_float(i15.get("macd_histogram_slope", 0.0))
    macd5 = safe_float(i5.get("macd_histogram", i5.get("macd_hist", 0.0)))
    macd5_slope = safe_float(i5.get("macd_histogram_slope", 0.0))

    if bias == "long":
        if macd15 > 0:
            score += 5
        if macd15_slope > 0:
            score += 4
        if macd5 > 0:
            score += 3
        if macd5_slope > 0:
            score += 3
    elif bias == "short":
        if macd15 < 0:
            score += 5
        if macd15_slope < 0:
            score += 4
        if macd5 < 0:
            score += 3
        if macd5_slope < 0:
            score += 3
    else:
        # Neutral symbols can still be active enough for mean reversion review.
        if abs(macd15_slope) > 0:
            score += 3
        if abs(macd5_slope) > 0:
            score += 3

    velocity = regime15.get("price_velocity", {}) or {}
    if abs(safe_float(velocity.get("short_6_bars"), 0.0)) >= 0.004:
        score += 2
    if abs(safe_float(velocity.get("medium_12_bars"), 0.0)) >= 0.008:
        score += 2

    bos_direction = pa15.get("recent_bos_direction")
    if bos_direction in ("bullish", "bearish") and not pa15.get("recent_bos_failed", False):
        score += 2

    score = clamp(score, 0.0, 20.0)
    return score, "MOMENTUM_ACTIVITY_PRESENT" if score >= 9 else "MOMENTUM_ACTIVITY_LOW"


def score_setup_location(snapshot: dict, bias: str) -> tuple[float, str]:
    s15 = safe_get_structure(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")
    i15 = safe_get_indicators(snapshot, "15m")

    score = 0.0
    reason = "SETUP_LOCATION_WEAK"

    structure_state = s15.get("structure_state")
    if structure_state == "clean_trend":
        score += 5
    elif structure_state in ("range", "transition", "chop", "weak_trend"):
        score += 3

    pullback_quality = safe_float(pa15.get("pullback_quality_score"), 0.0)
    score += score_linear(pullback_quality, 20, 80, 5)

    if pa15.get("pullback_state") in ("shallow_pullback", "active_pullback"):
        score += 3
    elif pa15.get("pullback_state") == "no_pullback":
        score += 1

    range_info = s15.get("mean_reversion_range", {}) or {}
    if range_info.get("valid"):
        position = safe_float(range_info.get("position"), 0.5)
        if bias == "long" and position <= 0.35:
            score += 6
            reason = "NEAR_RANGE_SUPPORT"
        elif bias == "short" and position >= 0.65:
            score += 6
            reason = "NEAR_RANGE_RESISTANCE"
        elif abs(position - 0.5) >= 0.25:
            score += 4
            reason = "NEAR_RANGE_EDGE"
        else:
            score += 2
            reason = "VALID_RANGE_MID_BOX"

    rsi = safe_float(i15.get("rsi"), 50.0)
    if 35 <= rsi <= 65:
        score += 2
    elif bias == "long" and rsi < 45:
        score += 2
    elif bias == "short" and rsi > 55:
        score += 2

    if pa15.get("recent_bos_failed", False):
        score -= 2

    score = clamp(score, 0.0, 20.0)
    if score >= 10 and reason == "SETUP_LOCATION_WEAK":
        reason = "SETUP_LOCATION_USABLE"
    return score, reason


def score_volatility_usability(snapshot: dict) -> tuple[float, str]:
    v15 = safe_get_volatility(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")
    regime15 = safe_get_regime_inputs(snapshot, "15m")

    score = 0.0
    reason = "VOLATILITY_USABLE"

    atr_ratio = safe_float(v15.get("atr_ratio", regime15.get("atr_ratio", 1.0)), 1.0)
    vol_state = v15.get("volatility_state", regime15.get("volatility_state", "normal"))
    expansion = pa15.get("expansion_state", "none")

    if 0.8 <= atr_ratio <= 1.8:
        score += 12
    elif 0.6 <= atr_ratio < 0.8 or 1.8 < atr_ratio <= 2.3:
        score += 8
        reason = "VOLATILITY_ACCEPTABLE"
    elif atr_ratio > 3.0 or vol_state == "extreme":
        score += 2
        reason = "VOLATILITY_EXTREME"
    else:
        score += 5
        reason = "VOLATILITY_WEAK_BUT_REVIEWABLE"

    if expansion == "healthy_expansion":
        score += 4
    elif expansion == "overextended_expansion":
        score -= 3
        reason = "VOLATILITY_OVEREXTENDED"

    # Low-volatility ranges can still be useful for mean-reversion.
    if vol_state == "low":
        score += 2

    score = clamp(score, 0.0, 20.0)
    return score, reason if score < 10 else "VOLATILITY_USABLE"


def infer_strategy_path_hints(snapshot: dict, bias: str) -> dict:
    mtf = safe_get_mtf_context(snapshot)
    alignment = mtf.get("alignment", {}) or {}
    primary = safe_get_tf(snapshot, "15m")
    primary_regime = (primary.get("regime_inputs", {}) or {}).get("v1_regime")
    s15 = safe_get_structure(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")

    trend_following_possible = (
        bias in ("long", "short")
        or alignment.get("consensus") in ("long", "short")
        or primary_regime in ("Uptrend", "Downtrend")
    )

    mean_reversion_possible = (
        primary_regime == "Sideways"
        or (s15.get("mean_reversion_range", {}) or {}).get("valid") is True
        or s15.get("market_type") in ("range", "transition")
        or pa15.get("recent_bos_failed", False)
    )

    # Lenient rule: if both are false but the symbol has usable data, allow
    # Strategy Engine only when score later proves it is still reviewable.
    return {
        "trend_following_possible": bool(trend_following_possible),
        "mean_reversion_possible": bool(mean_reversion_possible),
        "source": "market_snapshot_v2",
        "primary_regime": primary_regime,
        "alignment_consensus": alignment.get("consensus"),
    }


def score_snapshot(snapshot: dict):
    bias = determine_bias(snapshot)

    sub_scores = {
        "mtf_context": 0.0,
        "regime_usability": 0.0,
        "momentum_activity": 0.0,
        "setup_location": 0.0,
        "volatility_usability": 0.0,
    }
    reasons = []

    mtf_points, mtf_reason = score_mtf_context(snapshot)
    sub_scores["mtf_context"] = round(mtf_points, 2)
    reasons.append(mtf_reason)

    regime_points, regime_reason = score_regime_usability(snapshot)
    sub_scores["regime_usability"] = round(regime_points, 2)
    reasons.append(regime_reason)

    momentum_points, momentum_reason = score_momentum_activity(snapshot, bias)
    sub_scores["momentum_activity"] = round(momentum_points, 2)
    reasons.append(momentum_reason)

    setup_points, setup_reason = score_setup_location(snapshot, bias)
    sub_scores["setup_location"] = round(setup_points, 2)
    reasons.append(setup_reason)

    volatility_points, volatility_reason = score_volatility_usability(snapshot)
    sub_scores["volatility_usability"] = round(volatility_points, 2)
    reasons.append(volatility_reason)

    path_hints = infer_strategy_path_hints(snapshot, bias)
    if path_hints.get("trend_following_possible"):
        reasons.append("TREND_PATH_POSSIBLE")
    if path_hints.get("mean_reversion_possible"):
        reasons.append("MEAN_REVERSION_PATH_POSSIBLE")

    total_score = round(sum(sub_scores.values()), 2)

    # Preserve leniency: a valid mean-reversion path or clear MTF direction should
    # keep marginal setups reviewable unless the score is truly low.
    if total_score < MIN_SCORE:
        reasons.append("LOW_CONVICTION")

    return total_score, bias, sorted(set(reasons)), sub_scores, path_hints


def build_candidate_item(
    symbol: str,
    score: float,
    bias: str,
    reasons: list[str],
    sub_scores: dict,
    snapshot: dict,
    path_hints: dict,
):
    return {
        "symbol": symbol,
        "candidate_score": score,
        "score": score,  # backward compatibility
        "candidate_tier": tier_for_score(score),
        "candidate_bias": bias,
        "bias": bias,  # backward compatibility
        "candidate_status": "passed",
        "reject_reason": None,
        "sub_scores": sub_scores,
        "reason_tags": sorted(set(reasons)),
        "reasons": sorted(set(reasons)),  # backward compatibility
        "strategy_path_hints": path_hints,
        "snapshot_refs": {
            "snapshot_schema_version": snapshot.get("schema_version"),
            "snapshot_timestamp": snapshot.get("snapshot_timestamp"),
            "data_quality_healthy": (snapshot.get("data_quality", {}) or {}).get("healthy"),
            "required_timeframes": REQUIRED_TIMEFRAMES,
            "candidate_scoring_model": "market_snapshot_v2_lenient_step3",
        },
    }


def rank_symbols(account_id: int, symbols: list[str]):
    candidates = []
    rejected = []
    unavailable = []

    for symbol in symbols:
        open_pos, tg_error = has_open_position(account_id, symbol)
        if tg_error:
            unavailable.append(build_unavailable_item(
                symbol=symbol,
                reason="TRADE_GUARDIAN_UNAVAILABLE",
                details={"error": tg_error},
            ))
            continue

        if open_pos:
            rejected.append(build_rejected_item(
                symbol=symbol,
                reason="SYMBOL_ALREADY_HAS_OPEN_POSITION",
            ))
            continue

        snapshot, fetch_error = fetch_snapshot(symbol)
        if fetch_error:
            unavailable.append(build_unavailable_item(
                symbol=symbol,
                reason=fetch_error.get("reason", "SNAPSHOT_UNAVAILABLE"),
                details=fetch_error.get("details", {}),
                snapshot_data_quality=(fetch_error.get("details", {}) or {}).get("data_quality", {}),
            ))
            continue

        quality_error = validate_snapshot_data_quality(snapshot)
        if quality_error:
            unavailable.append(build_unavailable_item(
                symbol=symbol,
                reason=quality_error.get("reason", "MARKET_DATA_UNHEALTHY"),
                details=quality_error.get("details", {}),
                snapshot_data_quality=(quality_error.get("details", {}) or {}).get("data_quality", snapshot.get("data_quality", {})),
            ))
            continue

        score, bias, reasons, sub_scores, path_hints = score_snapshot(snapshot)
        item = build_candidate_item(symbol, score, bias, reasons, sub_scores, snapshot, path_hints)

        if score >= MIN_SCORE:
            candidates.append(item)
        else:
            item["candidate_status"] = "rejected"
            item["candidate_tier"] = "rejected"
            item["reject_reason"] = "LOW_CONVICTION"
            rejected.append(item)

    candidates.sort(key=lambda x: x["candidate_score"], reverse=True)
    rejected.sort(key=lambda x: x["candidate_score"], reverse=True)

    return candidates[:MAX_CANDIDATES], rejected, unavailable


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "env": os.getenv("APP_ENV", "unknown"),
                "max_candidates": MAX_CANDIDATES,
                "min_score": MIN_SCORE,
                "versions": build_versions_payload(),
            })
            return

        if self.path.startswith("/contract"):
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "versions": build_versions_payload(),
            })
            return

        if self.path.startswith("/candidates"):
            try:
                query = parse_qs(urlparse(self.path).query)
                symbols_param = query.get("symbols", [None])[0]
                account_id = int(query.get("account_id", ["1"])[0])

                if not symbols_param:
                    self._send_json({
                        "ok": False,
                        "error": "missing_parameters",
                        "required": ["symbols"],
                    }, status=400)
                    return

                symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
                if not symbols:
                    self._send_json({
                        "ok": False,
                        "error": "no_symbols_provided",
                    }, status=400)
                    return

                candidates, rejected, unavailable = rank_symbols(account_id, symbols)

                self._send_json({
                    "ok": True,
                    "schema_version": CANDIDATE_FILTER_SCHEMA_VERSION,
                    "candidate_filter_version": CANDIDATE_FILTER_VERSION,
                    "candidate_filter_mode": CANDIDATE_FILTER_MODE,
                    "runtime_version": CANDIDATE_FILTER_RUNTIME_VERSION,
                    "generated_at": iso_now(),
                    "account_id": account_id,
                    "input_symbols_count": len(symbols),
                    "max_candidates": MAX_CANDIDATES,
                    "min_score": MIN_SCORE,
                    "required_timeframes": REQUIRED_TIMEFRAMES,
                    "candidates": candidates,
                    "rejected": rejected,
                    "unavailable": unavailable,
                    "summary": {
                        "candidate_count": len(candidates),
                        "rejected_count": len(rejected),
                        "unavailable_count": len(unavailable),
                        "policy": "Unavailable means dependency/data quality failure; rejected means evaluated but not worth Strategy Engine review.",
                    },
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e),
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()
