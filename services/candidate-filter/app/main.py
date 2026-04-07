from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import json
import os

import requests


SERVICE_NAME = "candidate-filter"
PORT = int(os.getenv("PORT", "8080"))
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
FEATURE_FACTORY_BASE_URL = os.getenv("FEATURE_FACTORY_BASE_URL", "http://feature-factory:8080")
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "25"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "40"))


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


def fetch_snapshot(symbol: str):
    try:
        r = requests.get(
            f"{FEATURE_FACTORY_BASE_URL}/snapshot",
            params={"symbol": symbol},
            timeout=20
        )
        payload = r.json()
    except Exception as e:
        return None, f"feature_factory_request_failed: {str(e)}"

    if r.status_code != 200:
        return None, payload.get("error", "feature_factory_error")

    if payload.get("schema_version") != "market_snapshot_v2":
        return None, "unexpected_snapshot_schema_version"

    return payload, None


def has_open_position(account_id: int, symbol: str):
    try:
        response = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/position/open",
            params={"account_id": account_id, "symbol": symbol},
            timeout=10
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
    """
    Candidate Filter should remain permissive, but it should not be directionally blind.
    It now uses v2 structural fields and can also surface mean-reversion style bias.
    """
    s4 = safe_get_structure(snapshot, "4h")
    s1 = safe_get_structure(snapshot, "1h")
    s15 = safe_get_structure(snapshot, "15m")

    pa4 = safe_get_price_action(snapshot, "4h")
    pa1 = safe_get_price_action(snapshot, "1h")
    pa15 = safe_get_price_action(snapshot, "15m")

    i15 = safe_get_indicators(snapshot, "15m")

    bull = 0.0
    bear = 0.0

    # Higher-timeframe structural bias is the main directional anchor
    if s4.get("swing_bias") == "bullish":
        bull += 12
    elif s4.get("swing_bias") == "bearish":
        bear += 12

    if s1.get("swing_bias") == "bullish":
        bull += 10
    elif s1.get("swing_bias") == "bearish":
        bear += 10

    # Trend consistency contributes, but only moderately
    if s4.get("swing_bias") == "bullish":
        bull += score_linear(float(s4.get("trend_consistency_score", 0.0)), 20, 70, 4)
    elif s4.get("swing_bias") == "bearish":
        bear += score_linear(float(s4.get("trend_consistency_score", 0.0)), 20, 70, 4)

    if s1.get("swing_bias") == "bullish":
        bull += score_linear(float(s1.get("trend_consistency_score", 0.0)), 15, 60, 4)
    elif s1.get("swing_bias") == "bearish":
        bear += score_linear(float(s1.get("trend_consistency_score", 0.0)), 15, 60, 4)

    # BOS can reinforce, but should not dominate
    if pa1.get("recent_bos_direction") == "bullish" and not pa1.get("recent_bos_failed", False):
        bull += 3
    elif pa1.get("recent_bos_direction") == "bearish" and not pa1.get("recent_bos_failed", False):
        bear += 3

    if pa15.get("recent_bos_direction") == "bullish" and not pa15.get("recent_bos_failed", False):
        bull += 2
    elif pa15.get("recent_bos_direction") == "bearish" and not pa15.get("recent_bos_failed", False):
        bear += 2

    # If no clear trend bias, allow range-style directional inference
    # so the symbol can still reach Strategy Engine for mean-reversion evaluation.
    if abs(bull - bear) < 5:
        dist_high = float(s15.get("distance_to_range_high_pct", 50.0))
        dist_low = float(s15.get("distance_to_range_low_pct", 50.0))
        rsi = float(i15.get("rsi", 50.0))
        market_type_1h = s1.get("market_type")
        market_type_15m = s15.get("market_type")

        if market_type_1h in ("range", "transition") or market_type_15m in ("range", "transition"):
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
        if s4.get("swing_bias") == "bullish":
            points += 12
        if s1.get("swing_bias") == "bullish":
            points += 9
        if s15.get("swing_bias") == "bullish":
            points += 4
    else:
        if s4.get("swing_bias") == "bearish":
            points += 12
        if s1.get("swing_bias") == "bearish":
            points += 9
        if s15.get("swing_bias") == "bearish":
            points += 4

    return clamp(points, 0.0, 25.0), "HTF_BIAS_ALIGN" if points >= 12 else "HTF_BIAS_PARTIAL"


def score_momentum(snapshot: dict, bias: str):
    i1 = safe_get_indicators(snapshot, "1h")
    i15 = safe_get_indicators(snapshot, "15m")
    pa1 = safe_get_price_action(snapshot, "1h")
    pa15 = safe_get_price_action(snapshot, "15m")

    if bias == "neutral":
        return 0.0, "MOMENTUM_WEAK"

    points = 0.0

    if bias == "long":
        if float(i1.get("macd_histogram", 0.0)) > 0:
            points += 8
        if float(i15.get("macd_histogram", 0.0)) > 0:
            points += 6
        if float(i1.get("macd_histogram_slope", 0.0)) > 0:
            points += 4
        if float(i15.get("macd_histogram_slope", 0.0)) > 0:
            points += 3
        if pa15.get("recent_bos_direction") == "bullish" and not pa15.get("recent_bos_failed", False):
            points += 4
    else:
        if float(i1.get("macd_histogram", 0.0)) < 0:
            points += 8
        if float(i15.get("macd_histogram", 0.0)) < 0:
            points += 6
        if float(i1.get("macd_histogram_slope", 0.0)) < 0:
            points += 4
        if float(i15.get("macd_histogram_slope", 0.0)) < 0:
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

    # Pullback quality should help surface promising names,
    # but should not become a hard gate.
    points += score_linear(float(pa15.get("pullback_quality_score", 0.0)), 20, 80, 8)

    pullback_state = pa15.get("pullback_state")
    if pullback_state in ("shallow_pullback", "active_pullback"):
        points += 5
    elif pullback_state == "no_pullback":
        points += 2
    elif pullback_state == "deep_pullback":
        points += 1

    # RSI regime-aware permissive scoring
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
        if s5.get("swing_bias") == "bullish":
            points += 4
        if float(i5.get("price_vs_ema_fast_pct", 0.0)) >= -0.25:
            points += 4
        if pa5.get("wick_rejection_bias") == "bullish":
            points += 3
        if pa5.get("recent_bos_direction") == "bullish" and not pa5.get("recent_bos_failed", False):
            points += 2
        if int(pa15.get("pullback_bars_ago", 999)) <= 4:
            points += 2
    else:
        if s5.get("swing_bias") == "bearish":
            points += 4
        if float(i5.get("price_vs_ema_fast_pct", 0.0)) <= 0.25:
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

    points = 0.0
    reason = "VOLATILITY_OK"

    if vol_state == "medium":
        points = 10.0
    elif vol_state == "low":
        points = 6.0
        reason = "VOLATILITY_LOW_BUT_USABLE"
    else:
        points = 7.0
        reason = "VOLATILITY_HIGH_BUT_USABLE"

    if expansion_state == "overextended_expansion":
        points -= 2.0
        reason = "VOLATILITY_OVEREXTENDED"
    elif expansion_state == "healthy_expansion":
        points += 0.5

    return clamp(points, 0.0, 10.0), reason


def score_snapshot(snapshot: dict):
    total_score = 0.0
    reasons = []

    bias = determine_bias(snapshot)

    sub_scores = {
        "bias_alignment": 0.0,
        "momentum": 0.0,
        "setup": 0.0,
        "execution": 0.0,
        "volatility": 0.0,
    }

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


def rank_symbols(account_id: int, symbols: list[str]):
    candidates = []
    rejected = []

    zero_sub_scores = {
        "bias_alignment": 0.0,
        "momentum": 0.0,
        "setup": 0.0,
        "execution": 0.0,
        "volatility": 0.0,
    }

    for symbol in symbols:
        open_pos, tg_error = has_open_position(account_id, symbol)
        if tg_error:
            rejected.append({
                "symbol": symbol,
                "score": 0.0,
                "bias": "neutral",
                "sub_scores": zero_sub_scores,
                "reasons": ["TRADE_GUARDIAN_UNAVAILABLE"]
            })
            continue

        if open_pos:
            rejected.append({
                "symbol": symbol,
                "score": 0.0,
                "bias": "neutral",
                "sub_scores": zero_sub_scores,
                "reasons": ["SYMBOL_ALREADY_HAS_OPEN_POSITION"]
            })
            continue

        snapshot, error = fetch_snapshot(symbol)
        if error:
            rejected.append({
                "symbol": symbol,
                "score": 0.0,
                "bias": "neutral",
                "sub_scores": zero_sub_scores,
                "reasons": ["SNAPSHOT_UNAVAILABLE"]
            })
            continue

        score, bias, reasons, sub_scores = score_snapshot(snapshot)

        item = {
            "symbol": symbol,
            "score": score,
            "bias": bias,
            "sub_scores": sub_scores,
            "reasons": reasons
        }

        if score >= MIN_SCORE:
            candidates.append(item)
        else:
            rejected.append(item)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    rejected.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:MAX_CANDIDATES], rejected


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
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
                "min_score": MIN_SCORE
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
                        "required": ["symbols"]
                    }, status=400)
                    return

                symbols = [s.strip().upper() for s in symbols_param.split(",") if s.strip()]
                if not symbols:
                    self._send_json({
                        "ok": False,
                        "error": "no_symbols_provided"
                    }, status=400)
                    return

                candidates, rejected = rank_symbols(account_id, symbols)

                self._send_json({
                    "ok": True,
                    "generated_at": iso_now(),
                    "account_id": account_id,
                    "max_candidates": MAX_CANDIDATES,
                    "min_score": MIN_SCORE,
                    "candidates": candidates,
                    "rejected": rejected
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()