from __future__ import annotations

from urllib.parse import parse_qs

from strategy_analytics_v2 import (
    STRATEGY_ANALYTICS_V2_VERSION,
    get_strategy_analytics_v2_bundle,
    get_strategy_analytics_v2_regimes,
    get_strategy_analytics_v2_risk_rejections,
    get_strategy_analytics_v2_score_buckets,
    get_strategy_analytics_v2_score_components,
    get_strategy_analytics_v2_setups,
    get_strategy_analytics_v2_summary,
    get_strategy_analytics_v2_symbols,
)

STRATEGY_ANALYTICS_V2_ROUTES = {
    "/strategy-analytics/v2",
    "/strategy-analytics/v2/summary",
    "/strategy-analytics/v2/regimes",
    "/strategy-analytics/v2/setups",
    "/strategy-analytics/v2/score-buckets",
    "/strategy-analytics/v2/symbols",
    "/strategy-analytics/v2/score-components",
    "/strategy-analytics/v2/risk-rejections",
}


def handle_strategy_analytics_v2_get(handler, parsed) -> bool:
    if parsed.path not in STRATEGY_ANALYTICS_V2_ROUTES:
        return False

    query = parse_qs(parsed.query)
    account_id = int(query.get("account_id", ["1"])[0])
    raw_limit = query.get("limit", [None])[0]
    limit = int(raw_limit) if raw_limit is not None else None
    cycle_limit = int(query.get("cycle_limit", ["100"])[0])

    if parsed.path == "/strategy-analytics/v2":
        handler._send_json(get_strategy_analytics_v2_bundle(account_id, limit, cycle_limit))
        return True
    if parsed.path == "/strategy-analytics/v2/summary":
        handler._send_json(get_strategy_analytics_v2_summary(account_id, limit))
        return True
    if parsed.path == "/strategy-analytics/v2/regimes":
        handler._send_json(get_strategy_analytics_v2_regimes(account_id, limit))
        return True
    if parsed.path == "/strategy-analytics/v2/setups":
        handler._send_json(get_strategy_analytics_v2_setups(account_id, limit))
        return True
    if parsed.path == "/strategy-analytics/v2/score-buckets":
        handler._send_json(get_strategy_analytics_v2_score_buckets(account_id, limit))
        return True
    if parsed.path == "/strategy-analytics/v2/symbols":
        handler._send_json(get_strategy_analytics_v2_symbols(account_id, limit))
        return True
    if parsed.path == "/strategy-analytics/v2/score-components":
        handler._send_json(get_strategy_analytics_v2_score_components(account_id, cycle_limit))
        return True
    if parsed.path == "/strategy-analytics/v2/risk-rejections":
        handler._send_json(get_strategy_analytics_v2_risk_rejections(account_id, cycle_limit))
        return True

    handler._send_json({
        "ok": False,
        "error": "unknown_strategy_analytics_v2_route",
        "strategy_analytics_v2_version": STRATEGY_ANALYTICS_V2_VERSION,
    }, status=404)
    return True
