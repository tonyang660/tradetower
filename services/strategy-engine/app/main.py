from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os

import requests


SERVICE_NAME = "strategy-engine"
PORT = int(os.getenv("PORT", "8080"))

FEATURE_FACTORY_BASE_URL = os.getenv("FEATURE_FACTORY_BASE_URL", "http://feature-factory:8080")
STRICT_SCORE_THRESHOLD = float(os.getenv("STRICT_SCORE_THRESHOLD", "75"))


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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

    if not payload.get("ok"):
        return None, payload.get("error", "feature_factory_error")

    return payload, None


def safe_get_tf(snapshot: dict, tf: str):
    return snapshot.get("timeframes", {}).get(tf, {})


def derive_macro_bias(snapshot: dict):
    """
    v1 macro bias = higher timeframe directional bias only.
    """
    tf_4h = safe_get_tf(snapshot, "4h")
    tf_1h = safe_get_tf(snapshot, "1h")

    score_bull = 0
    score_bear = 0
    reasons = []

    for tf_name, tf in [("4h", tf_4h), ("1h", tf_1h)]:
        indicators = tf.get("indicators", {})
        structure = tf.get("structure", {})

        if indicators.get("ema_fast", 0) > indicators.get("ema_slow", 0):
            score_bull += 1
            reasons.append(f"{tf_name}_EMA_BULL")
        elif indicators.get("ema_fast", 0) < indicators.get("ema_slow", 0):
            score_bear += 1
            reasons.append(f"{tf_name}_EMA_BEAR")

        if indicators.get("macd", 0) > indicators.get("macd_signal", 0):
            score_bull += 1
            reasons.append(f"{tf_name}_MACD_BULL")
        elif indicators.get("macd", 0) < indicators.get("macd_signal", 0):
            score_bear += 1
            reasons.append(f"{tf_name}_MACD_BEAR")

        if structure.get("higher_highs") and structure.get("higher_lows"):
            score_bull += 2
            reasons.append(f"{tf_name}_HH_HL")
        elif structure.get("lower_highs") and structure.get("lower_lows"):
            score_bear += 2
            reasons.append(f"{tf_name}_LH_LL")

    if score_bull >= 5 and score_bear == 0:
        return "bullish", min(95, 50 + score_bull * 8), reasons
    if score_bear >= 5 and score_bull == 0:
        return "bearish", min(95, 50 + score_bear * 8), reasons

    return "transition", 55, reasons


def detect_price_action_state(tf: dict):
    structure = tf.get("structure", {})
    indicators = tf.get("indicators", {})

    higher_highs = structure.get("higher_highs", False)
    higher_lows = structure.get("higher_lows", False)
    lower_highs = structure.get("lower_highs", False)
    lower_lows = structure.get("lower_lows", False)

    ema_fast = indicators.get("ema_fast", 0)
    ema_slow = indicators.get("ema_slow", 0)
    price_vs_fast = indicators.get("price_vs_ema_fast_pct", 0)
    price_vs_slow = indicators.get("price_vs_ema_slow_pct", 0)
    macd = indicators.get("macd", 0)
    macd_signal = indicators.get("macd_signal", 0)

    bullish_structure = higher_highs and higher_lows
    bearish_structure = lower_highs and lower_lows

    bullish_trend_confirm = (
        ema_fast > ema_slow and
        price_vs_fast > 0 and
        price_vs_slow > 0 and
        macd > macd_signal
    )

    bearish_trend_confirm = (
        ema_fast < ema_slow and
        price_vs_fast < 0 and
        price_vs_slow < 0 and
        macd < macd_signal
    )

    if bullish_structure and bullish_trend_confirm:
        return "bullish"
    if bearish_structure and bearish_trend_confirm:
        return "bearish"
    if bullish_structure or bearish_structure:
        return "mixed"

    return "neutral"


def detect_bos(snapshot: dict):
    """
    v1 BOS proxy:
    We approximate BOS from structure/trend alignment and range-edge context
    because explicit swing-break fields are not yet in the snapshot.
    """
    tf_15m = safe_get_tf(snapshot, "15m")
    tf_5m = safe_get_tf(snapshot, "5m")

    s15 = tf_15m.get("structure", {})
    s5 = tf_5m.get("structure", {})
    i15 = tf_15m.get("indicators", {})
    i5 = tf_5m.get("indicators", {})

    bullish_15 = s15.get("higher_highs") and s15.get("higher_lows") and i15.get("macd", 0) > i15.get("macd_signal", 0)
    bearish_15 = s15.get("lower_highs") and s15.get("lower_lows") and i15.get("macd", 0) < i15.get("macd_signal", 0)

    bullish_5 = s5.get("higher_highs") and s5.get("higher_lows") and i5.get("price_vs_ema_fast_pct", 0) > 0
    bearish_5 = s5.get("lower_highs") and s5.get("lower_lows") and i5.get("price_vs_ema_fast_pct", 0) < 0

    if bullish_15 and bullish_5:
        return "bullish"
    if bearish_15 and bearish_5:
        return "bearish"
    return "none"


def detect_regime(snapshot: dict, macro_bias: str):
    tf_4h = safe_get_tf(snapshot, "4h")
    tf_1h = safe_get_tf(snapshot, "1h")
    tf_15m = safe_get_tf(snapshot, "15m")

    pa_4h = detect_price_action_state(tf_4h)
    pa_1h = detect_price_action_state(tf_1h)
    pa_15m = detect_price_action_state(tf_15m)
    bos = detect_bos(snapshot)

    reasons = []

    # Hard transition / chop logic
    if macro_bias == "transition":
        reasons.append("MACRO_BIAS_TRANSITION")
        return "transition", 60, reasons

    # Trend up
    if macro_bias == "bullish" and pa_4h in ("bullish", "mixed") and pa_1h == "bullish":
        if bos == "bullish":
            reasons.extend(["BULLISH_MACRO", "HTF_BULLISH", "BOS_BULLISH"])
            return "trend_up", 85, reasons
        reasons.extend(["BULLISH_MACRO", "HTF_BULLISH"])
        return "trend_up", 78, reasons

    # Trend down
    if macro_bias == "bearish" and pa_4h in ("bearish", "mixed") and pa_1h == "bearish":
        if bos == "bearish":
            reasons.extend(["BEARISH_MACRO", "HTF_BEARISH", "BOS_BEARISH"])
            return "trend_down", 85, reasons
        reasons.extend(["BEARISH_MACRO", "HTF_BEARISH"])
        return "trend_down", 78, reasons

    # Range
    structure_15 = tf_15m.get("structure", {})
    market_type_15 = structure_15.get("market_type", "")
    if market_type_15 in ("range", "ranging") or (
        pa_4h == "neutral" and pa_1h == "neutral" and bos == "none"
    ):
        reasons.append("RANGE_BEHAVIOR")
        return "range", 72, reasons

    # Chop
    if pa_4h == "neutral" and pa_1h == "neutral" and pa_15m == "neutral":
        reasons.append("CHOPPY_BEHAVIOR")
        return "chop", 65, reasons

    reasons.append("MIXED_STRUCTURE")
    return "transition", 62, reasons


def score_trend_following(snapshot: dict, regime: str, macro_bias: str):
    score = 0.0
    reasons = []

    if regime not in ("trend_up", "trend_down"):
        return 0.0, ["REGIME_NOT_TREND"]

    tf_4h = safe_get_tf(snapshot, "4h")
    tf_1h = safe_get_tf(snapshot, "1h")
    tf_15m = safe_get_tf(snapshot, "15m")
    tf_5m = safe_get_tf(snapshot, "5m")

    i4 = tf_4h.get("indicators", {})
    i1 = tf_1h.get("indicators", {})
    i15 = tf_15m.get("indicators", {})
    i5 = tf_5m.get("indicators", {})
    s4 = tf_4h.get("structure", {})
    s1 = tf_1h.get("structure", {})
    s15 = tf_15m.get("structure", {})
    s5 = tf_5m.get("structure", {})

    bos = detect_bos(snapshot)

    # Macro bias
    if (regime == "trend_up" and macro_bias == "bullish") or (regime == "trend_down" and macro_bias == "bearish"):
        score += 15
        reasons.append("MACRO_ALIGN")

    # EMA alignment
    ema_align_4h = i4.get("ema_fast", 0) > i4.get("ema_slow", 0) if regime == "trend_up" else i4.get("ema_fast", 0) < i4.get("ema_slow", 0)
    ema_align_1h = i1.get("ema_fast", 0) > i1.get("ema_slow", 0) if regime == "trend_up" else i1.get("ema_fast", 0) < i1.get("ema_slow", 0)
    if ema_align_4h and ema_align_1h:
        score += 20
        reasons.append("EMA_ALIGN")

    # Structure quality
    if regime == "trend_up":
        if s4.get("higher_highs") and s4.get("higher_lows"):
            score += 10
            reasons.append("4H_HH_HL")
        if s1.get("higher_highs") and s1.get("higher_lows"):
            score += 10
            reasons.append("1H_HH_HL")
        if s15.get("higher_lows"):
            score += 8
            reasons.append("15M_PULLBACK_VALID")
    else:
        if s4.get("lower_highs") and s4.get("lower_lows"):
            score += 10
            reasons.append("4H_LH_LL")
        if s1.get("lower_highs") and s1.get("lower_lows"):
            score += 10
            reasons.append("1H_LH_LL")
        if s15.get("lower_highs"):
            score += 8
            reasons.append("15M_PULLBACK_VALID")

    # BOS
    if (regime == "trend_up" and bos == "bullish") or (regime == "trend_down" and bos == "bearish"):
        score += 12
        reasons.append("BOS_ALIGN")
    elif bos != "none":
        score -= 12
        reasons.append("BOS_CONFLICT")

    # Momentum
    macd_good = i1.get("macd", 0) > i1.get("macd_signal", 0) if regime == "trend_up" else i1.get("macd", 0) < i1.get("macd_signal", 0)
    if macd_good:
        score += 8
        reasons.append("MACD_CONFIRM")

    # Price action / pullback quality
    if regime == "trend_up":
        if i5.get("price_vs_ema_fast_pct", 0) >= -0.5 and i15.get("price_vs_ema_fast_pct", 0) > 0:
            score += 10
            reasons.append("PULLBACK_NEAR_FAST_EMA")
    else:
        if i5.get("price_vs_ema_fast_pct", 0) <= 0.5 and i15.get("price_vs_ema_fast_pct", 0) < 0:
            score += 10
            reasons.append("PULLBACK_NEAR_FAST_EMA")

    # Volatility suitability
    atr = i1.get("atr", 0)
    if atr > 0:
        score += 7
        reasons.append("VOLATILITY_OK")

    return max(0.0, min(100.0, score)), reasons


def score_mean_reversion(snapshot: dict, regime: str):
    score = 0.0
    reasons = []

    if regime != "range":
        return 0.0, ["REGIME_NOT_RANGE"]

    tf_1h = safe_get_tf(snapshot, "1h")
    tf_15m = safe_get_tf(snapshot, "15m")
    tf_5m = safe_get_tf(snapshot, "5m")

    i1 = tf_1h.get("indicators", {})
    i15 = tf_15m.get("indicators", {})
    s15 = tf_15m.get("structure", {})
    s5 = tf_5m.get("structure", {})

    bos = detect_bos(snapshot)

    # Range quality
    if s15.get("market_type") in ("range", "ranging", "sideways"):
        score += 25
        reasons.append("RANGE_QUALITY_OK")
    else:
        score += 12
        reasons.append("RANGE_QUALITY_PARTIAL")

    # Distance to range edge
    dist_high = s15.get("distance_to_range_high_pct", 50)
    dist_low = s15.get("distance_to_range_low_pct", 50)
    rsi = i15.get("rsi", 50)

    # Long mean reversion candidate near range low
    if dist_low <= 20 and rsi <= 40:
        score += 20
        reasons.append("NEAR_RANGE_LOW")
        score += 15
        reasons.append("RSI_STRETCH_LONG")
    # Short mean reversion candidate near range high
    elif dist_high <= 20 and rsi >= 60:
        score += 20
        reasons.append("NEAR_RANGE_HIGH")
        score += 15
        reasons.append("RSI_STRETCH_SHORT")

    # Trend weakness requirement
    if abs(i1.get("price_vs_ema_slow_pct", 0)) < 1.5:
        score += 15
        reasons.append("LOW_TREND_STRENGTH")

    # No fresh directional BOS
    if bos == "none":
        score += 10
        reasons.append("NO_FRESH_BOS")
    else:
        score -= 20
        reasons.append("BOS_BREAKS_RANGE")

    # Volatility suitability
    atr = i15.get("atr", 0)
    if atr > 0:
        score += 5
        reasons.append("VOLATILITY_ACCEPTABLE")

    # Clean invalidation via range edges
    if s15.get("range_high") and s15.get("range_low"):
        score += 10
        reasons.append("CLEAR_RANGE_INVALIDATION")

    return max(0.0, min(100.0, score)), reasons


def build_trend_following_proposal(symbol: str, snapshot: dict, regime: str, score: float, reasons: list[str]):
    tf_15m = safe_get_tf(snapshot, "15m")
    tf_1h = safe_get_tf(snapshot, "1h")

    s15 = tf_15m.get("structure", {})
    i15 = tf_15m.get("indicators", {})
    i1 = tf_1h.get("indicators", {})

    if regime == "trend_up":
        decision = "long"
        entry_price = float(i15.get("ema_fast", 0))
        stop_loss = float(s15.get("range_low", 0) or (entry_price * 0.985))
        tp1 = float(s15.get("range_high", 0) or (entry_price * 1.01))
        tp2 = float(tp1 * 1.02)
        tp3 = float(tp2 * 1.04)
    else:
        decision = "short"
        entry_price = float(i15.get("ema_fast", 0))
        stop_loss = float(s15.get("range_high", 0) or (entry_price * 1.015))
        tp1 = float(s15.get("range_low", 0) or (entry_price * 0.99))
        tp2 = float(tp1 * 0.98)
        tp3 = float(tp2 * 0.96)

    return {
        "ok": True,
        "symbol": symbol,
        "regime": regime,
        "selected_strategy": "trend_following",
        "decision": decision,
        "confidence": round(score, 2),
        "entry_order_type": "limit",
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "tp1_price": round(tp1, 8),
        "tp2_price": round(tp2, 8),
        "tp3_price": round(tp3, 8),
        "reason_tags": reasons
    }


def build_mean_reversion_proposal(symbol: str, snapshot: dict, score: float, reasons: list[str]):
    tf_15m = safe_get_tf(snapshot, "15m")
    s15 = tf_15m.get("structure", {})
    i15 = tf_15m.get("indicators", {})

    dist_high = s15.get("distance_to_range_high_pct", 50)
    dist_low = s15.get("distance_to_range_low_pct", 50)

    range_high = float(s15.get("range_high", 0))
    range_low = float(s15.get("range_low", 0))
    mid_range = (range_high + range_low) / 2 if range_high and range_low else 0

    if dist_low <= dist_high:
        decision = "long"
        entry_price = max(float(i15.get("ema_fast", range_low)), range_low)
        stop_loss = round(range_low * 0.997, 8)
        tp1 = round(mid_range, 8)
        tp2 = round(range_high, 8)
        tp3 = round(range_high * 1.005, 8)
    else:
        decision = "short"
        entry_price = min(float(i15.get("ema_fast", range_high)), range_high)
        stop_loss = round(range_high * 1.003, 8)
        tp1 = round(mid_range, 8)
        tp2 = round(range_low, 8)
        tp3 = round(range_low * 0.995, 8)

    return {
        "ok": True,
        "symbol": symbol,
        "regime": "range",
        "selected_strategy": "mean_reversion",
        "decision": decision,
        "confidence": round(score, 2),
        "entry_order_type": "limit",
        "entry_price": round(entry_price, 8),
        "stop_loss": round(stop_loss, 8),
        "tp1_price": round(tp1, 8),
        "tp2_price": round(tp2, 8),
        "tp3_price": round(tp3, 8),
        "reason_tags": reasons
    }


def analyze_symbol(symbol: str):
    snapshot_payload, error = fetch_snapshot(symbol)
    if error:
        return {
            "ok": False,
            "error": error,
            "symbol": symbol
        }

    macro_bias, macro_conf, macro_reasons = derive_macro_bias(snapshot_payload)
    regime, regime_conf, regime_reasons = detect_regime(snapshot_payload, macro_bias)

    if regime in ("transition", "chop"):
        return {
            "ok": True,
            "symbol": symbol,
            "macro_bias": macro_bias,
            "macro_confidence": macro_conf,
            "regime": regime,
            "regime_confidence": regime_conf,
            "strategy_scores": {
                "trend_following": 0.0,
                "mean_reversion": 0.0
            },
            "selected_strategy": "none",
            "decision": "no_trade",
            "confidence": 0.0,
            "reason_tags": macro_reasons + regime_reasons + ["HARD_BLOCK_REGIME"]
        }

    trend_score, trend_reasons = score_trend_following(snapshot_payload, regime, macro_bias)
    mean_score, mean_reasons = score_mean_reversion(snapshot_payload, regime)

    if trend_score >= mean_score and trend_score >= STRICT_SCORE_THRESHOLD:
        proposal = build_trend_following_proposal(
            symbol, snapshot_payload, regime, trend_score,
            macro_reasons + regime_reasons + trend_reasons
        )
    elif mean_score > trend_score and mean_score >= STRICT_SCORE_THRESHOLD:
        proposal = build_mean_reversion_proposal(
            symbol, snapshot_payload, mean_score,
            macro_reasons + regime_reasons + mean_reasons
        )
    else:
        proposal = {
            "ok": True,
            "symbol": symbol,
            "macro_bias": macro_bias,
            "macro_confidence": macro_conf,
            "regime": regime,
            "regime_confidence": regime_conf,
            "strategy_scores": {
                "trend_following": round(trend_score, 2),
                "mean_reversion": round(mean_score, 2)
            },
            "selected_strategy": "none",
            "decision": "no_trade",
            "confidence": 0.0,
            "reason_tags": (
                macro_reasons + regime_reasons +
                ["STRICT_THRESHOLD_NOT_MET"]
            )
        }
        return proposal

    proposal["macro_bias"] = macro_bias
    proposal["macro_confidence"] = macro_conf
    proposal["regime_confidence"] = regime_conf
    proposal["strategy_scores"] = {
        "trend_following": round(trend_score, 2),
        "mean_reversion": round(mean_score, 2)
    }
    return proposal


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
                "timestamp": iso_now(),
                "strict_score_threshold": STRICT_SCORE_THRESHOLD
            })
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/analyze":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                symbol = payload.get("symbol")
                if not symbol:
                    self._send_json({
                        "ok": False,
                        "error": "missing_symbol"
                    }, status=400)
                    return

                result = analyze_symbol(symbol.upper())
                self._send_json(result, status=200 if result.get("ok") else 400)
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