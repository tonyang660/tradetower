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
CANDIDATE_FILTER_RUNTIME_VERSION = "phase3_5_step2_data_quality"


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


def determine_bias(snapshot: dict) -> str:
    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")

    pa1 = safe_get_price_action(snapshot, "1h")
    pa15 = safe_get_price_action(snapshot, "15m")
    i15 = safe_get_indicators(snapshot, "15m")

    bull = 0.0
    bear = 0.0

    if s4.get("swing_bias") == "bullish" or s4.get("v1_trend_direction") == "bullish":
        bull += 12
    elif s4.get("swing_bias") == "bearish" or s4.get("v1_trend_direction") == "bearish":
        bear += 12

    if s1.get("swing_bias") == "bullish" or s1.get("v1_trend_direction") == "bullish":
        bull += 10
    elif s1.get("swing_bias") == "bearish" or s1.get("v1_trend_direction") == "bearish":
        bear += 10

    if s4.get("swing_bias") == "bullish":
        bull += score_linear(safe_float(s4.get("trend_consistency_score", 0.0)), 20, 70, 4)
    elif s4.get("swing_bias") == "bearish":
        bear += score_linear(safe_float(s4.get("trend_consistency_score", 0.0)), 20, 70, 4)

    if s1.get("swing_bias") == "bullish":
        bull += score_linear(safe_float(s1.get("trend_consistency_score", 0.0)), 15, 60, 4)
    elif s1.get("swing_bias") == "bearish":
        bear += score_linear(safe_float(s1.get("trend_consistency_score", 0.0)), 15, 60, 4)

    if pa1.get("recent_bos_direction") == "bullish" and not pa1.get("recent_bos_failed", False):
        bull += 3
    elif pa1.get("recent_bos_direction") == "bearish" and not pa1.get("recent_bos_failed", False):
        bear += 3

    if pa15.get("recent_bos_direction") == "bullish" and not pa15.get("recent_bos_failed", False):
        bull += 2
    elif pa15.get("recent_bos_direction") == "bearish" and not pa15.get("recent_bos_failed", False):
        bear += 2

    if abs(bull - bear) < 5:
        dist_high = safe_float(s15.get("distance_to_range_high_pct", 50.0), 50.0)
        dist_low = safe_float(s15.get("distance_to_range_low_pct", 50.0), 50.0)
        rsi = safe_float(i15.get("rsi", 50.0), 50.0)
        market_type_1h = s1.get("market_type")
        market_type_15m = s15.get("market_type")
        mean_reversion_range = s15.get("mean_reversion_range", {}) or {}

        range_like = (
            market_type_1h in ("range", "transition")
            or market_type_15m in ("range", "transition")
            or mean_reversion_range.get("valid") is True
        )

        if range_like:
            if dist_low <= 25 and rsi <= 48:
                bull += 6
            elif dist_high <= 25 and rsi >= 52:
                bear += 6

    if bull >= bear + 5 and bull >= 12:
        return "long"
    if bear >= bull + 5 and bear >= 12:
        return "short"
    return "neutral"


def score_bias_alignment(snapshot: dict, bias: str):
    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")

    if bias == "neutral":
        return 0.0, "HTF_BIAS_CONFLICT"

    points = 0.0
    if bias == "long":
        if s4.get("swing_bias") == "bullish" or s4.get("v1_trend_direction") == "bullish":
            points += 12
        if s1.get("swing_bias") == "bullish" or s1.get("v1_trend_direction") == "bullish":
            points += 9
        if s15.get("swing_bias") == "bullish" or s15.get("v1_trend_direction") == "bullish":
            points += 4
    else:
        if s4.get("swing_bias") == "bearish" or s4.get("v1_trend_direction") == "bearish":
            points += 12
        if s1.get("swing_bias") == "bearish" or s1.get("v1_trend_direction") == "bearish":
            points += 9
        if s15.get("swing_bias") == "bearish" or s15.get("v1_trend_direction") == "bearish":
            points += 4

    return clamp(points, 0.0, 25.0), "HTF_BIAS_ALIGN" if points >= 12 else "HTF_BIAS_PARTIAL"


def score_momentum(snapshot: dict, bias: str):
    i1 = safe_get_indicators(snapshot, "1h")
    i15 = safe_get_indicators(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")

    if bias == "neutral":
        return 0.0, "MOMENTUM_WEAK"

    points = 0.0
    if bias == "long":
        if safe_float(i1.get("macd_histogram", i1.get("macd_hist", 0.0))) > 0:
            points += 8
        if safe_float(i15.get("macd_histogram", i15.get("macd_hist", 0.0))) > 0:
            points += 6
        if safe_float(i1.get("macd_histogram_slope", 0.0)) > 0:
            points += 4
        if safe_float(i15.get("macd_histogram_slope", 0.0)) > 0:
            points += 3
        if pa15.get("recent_bos_direction") == "bullish" and not pa15.get("recent_bos_failed", False):
            points += 4
    else:
        if safe_float(i1.get("macd_histogram", i1.get("macd_hist", 0.0))) < 0:
            points += 8
        if safe_float(i15.get("macd_histogram", i15.get("macd_hist", 0.0))) < 0:
            points += 6
        if safe_float(i1.get("macd_histogram_slope", 0.0)) < 0:
            points += 4
        if safe_float(i15.get("macd_histogram_slope", 0.0)) < 0:
            points += 3
        if pa15.get("recent_bos_direction") == "bearish" and not pa15.get("recent_bos_failed", False):
            points += 4

    points = clamp(points, 0.0, 25.0)
    return points, "MOMENTUM_SUPPORT" if points >= 12 else "MOMENTUM_WEAK"


def score_setup(snapshot: dict, bias: str):
    s15 = safe_get_structure(snapshot, "15m")
    i15 = safe_get_indicators(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")

    if bias == "neutral":
        return 0.0, "SETUP_QUALITY_WEAK"

    points = 0.0
    structure_state = s15.get("structure_state")
    if structure_state == "clean_trend":
        points += 8
    elif structure_state in ("weak_trend", "range", "transition"):
        points += 4

    points += score_linear(safe_float(pa15.get("pullback_quality_score", 0.0)), 20, 80, 8)

    pullback_state = pa15.get("pullback_state")
    if pullback_state in ("shallow_pullback", "active_pullback"):
        points += 5
    elif pullback_state == "no_pullback":
        points += 2
    elif pullback_state == "deep_pullback":
        points += 1

    mean_reversion_range = s15.get("mean_reversion_range", {}) or {}
    if mean_reversion_range.get("valid"):
        points += 4

    rsi_state = i15.get("rsi_state", "neutral")
    if bias == "long":
        if rsi_state in ("neutral", "bullish_but_not_overextended", "bearish_but_not_oversold"):
            points += 4
    else:
        if rsi_state in ("neutral", "bearish_but_not_oversold", "bullish_but_not_overextended"):
            points += 4

    if pa15.get("recent_bos_failed", False):
        points -= 3

    points = clamp(points, 0.0, 25.0)
    return points, "SETUP_QUALITY_OK" if points >= 12 else "SETUP_QUALITY_WEAK"


def score_execution(snapshot: dict, bias: str):
    s5 = safe_get_structure(snapshot, "5m")
    i5 = safe_get_indicators(snapshot, "5m")
    pa5 = safe_get_price_action(snapshot, "5m")
    pa15 = safe_get_price_action(snapshot, "15m")

    if bias == "neutral":
        return 0.0, "EXECUTION_CONFLICT"

    points = 0.0
    if bias == "long":
        if s5.get("swing_bias") == "bullish" or s5.get("v1_trend_direction") == "bullish":
            points += 4
        if safe_float(i5.get("price_vs_ema_fast_pct", 0.0)) >= -0.25:
            points += 4
        if pa5.get("wick_rejection_bias") == "bullish":
            points += 3
        if pa5.get("recent_bos_direction") == "bullish" and not pa5.get("recent_bos_failed", False):
            points += 2
        if int(pa15.get("pullback_bars_ago", 999)) <= 4:
            points += 2
    else:
        if s5.get("swing_bias") == "bearish" or s5.get("v1_trend_direction") == "bearish":
            points += 4
        if safe_float(i5.get("price_vs_ema_fast_pct", 0.0)) <= 0.25:
            points += 4
        if pa5.get("wick_rejection_bias") == "bearish":
            points += 3
        if pa5.get("recent_bos_direction") == "bearish" and not pa5.get("recent_bos_failed", False):
            points += 2
        if int(pa15.get("pullback_bars_ago", 999)) <= 4:
            points += 2

    if pa5.get("recent_bos_failed", False):
        points -= 2

    points = clamp(points, 0.0, 15.0)
    return points, "EXECUTION_ALIGN" if points >= 7 else "EXECUTION_CONFLICT"


def score_volatility(snapshot: dict):
    v15 = safe_get_volatility(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")

    vol_state = v15.get("volatility_state", "medium")
    expansion_state = pa15.get("expansion_state", "none")

    if vol_state == "medium" or vol_state == "normal":
        points = 10.0
        reason = "VOLATILITY_OK"
    elif vol_state == "low":
        points = 6.0
        reason = "VOLATILITY_LOW_BUT_USABLE"
    elif vol_state == "extreme":
        points = 2.0
        reason = "VOLATILITY_EXTREME"
    else:
        points = 7.0
        reason = "VOLATILITY_HIGH_BUT_USABLE"

    if expansion_state == "overextended_expansion":
        points -= 2.0
        reason = "VOLATILITY_OVEREXTENDED"
    elif expansion_state == "healthy_expansion":
        points += 0.5

    return clamp(points, 0.0, 10.0), reason


def infer_strategy_path_hints(snapshot: dict, bias: str) -> dict:
    mtf = snapshot.get("multi_timeframe_context", {}) or {}
    alignment = mtf.get("alignment", {}) or {}
    primary = safe_get_tf(snapshot, "15m")
    primary_regime = (primary.get("regime_inputs", {}) or {}).get("v1_regime")
    s15 = safe_get_structure(snapshot, "15m")
    pa15 = safe_get_price_action(snapshot, "15m")

    trend_possible = (
        bias in ("long", "short")
        or alignment.get("consensus") in ("long", "short")
        or primary_regime in ("Uptrend", "Downtrend")
    )

    mean_reversion_possible = (
        primary_regime == "Sideways"
        or (s15.get("mean_reversion_range", {}) or {}).get("valid") is True
        or s15.get("market_type") in ("range", "transition")
    )

    if pa15.get("recent_bos_failed", False) and mean_reversion_possible:
        mean_reversion_possible = True

    return {
        "trend_following_possible": bool(trend_possible),
        "mean_reversion_possible": bool(mean_reversion_possible),
        "source": "market_snapshot_v2",
    }


def score_snapshot(snapshot: dict):
    bias = determine_bias(snapshot)

    sub_scores = {
        "bias_alignment": 0.0,
        "momentum": 0.0,
        "setup": 0.0,
        "execution": 0.0,
        "volatility": 0.0,
    }
    reasons = []

    bias_points, bias_reason = score_bias_alignment(snapshot, bias)
    sub_scores["bias_alignment"] = round(bias_points, 2)
    reasons.append(bias_reason)

    momentum_points, momentum_reason = score_momentum(snapshot, bias)
    sub_scores["momentum"] = round(momentum_points, 2)
    reasons.append(momentum_reason)

    setup_points, setup_reason = score_setup(snapshot, bias)
    sub_scores["setup"] = round(setup_points, 2)
    reasons.append(setup_reason)

    execution_points, execution_reason = score_execution(snapshot, bias)
    sub_scores["execution"] = round(execution_points, 2)
    reasons.append(execution_reason)

    volatility_points, volatility_reason = score_volatility(snapshot)
    sub_scores["volatility"] = round(volatility_points, 2)
    reasons.append(volatility_reason)

    total_score = round(sum(sub_scores.values()), 2)
    if total_score < MIN_SCORE:
        reasons.append("LOW_CONVICTION")

    return total_score, bias, reasons, sub_scores


def build_candidate_item(symbol: str, score: float, bias: str, reasons: list[str], sub_scores: dict, snapshot: dict):
    path_hints = infer_strategy_path_hints(snapshot, bias)
    if path_hints.get("trend_following_possible"):
        reasons.append("TREND_PATH_POSSIBLE")
    if path_hints.get("mean_reversion_possible"):
        reasons.append("MEAN_REVERSION_PATH_POSSIBLE")

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

        score, bias, reasons, sub_scores = score_snapshot(snapshot)
        item = build_candidate_item(symbol, score, bias, reasons, sub_scores, snapshot)

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
