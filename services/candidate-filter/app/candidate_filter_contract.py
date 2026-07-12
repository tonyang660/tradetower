"""
Phase 3.5 Step 1 — Candidate Filter v2 contract constants.

This module is contract-only. It defines Candidate Filter's intended role as a
lenient pre-screen between Feature Factory and Strategy Engine.

Candidate Filter must not become the main strategy decision maker.
"""

CANDIDATE_FILTER_SCHEMA_VERSION = "candidate_filter_v2"
CANDIDATE_FILTER_VERSION = "v2"
CANDIDATE_FILTER_CONTRACT_VERSION = "phase3_5_step1"
CANDIDATE_FILTER_MODE = "lenient_screener"

CANDIDATE_TIERS = {
    "strong_candidate": {"min_score": 70, "meaning": "Clearly worth Strategy Engine review."},
    "candidate": {"min_score": 50, "meaning": "Worth Strategy Engine review."},
    "weak_candidate": {"min_score": 35, "meaning": "Marginal but still can pass when capacity allows."},
    "rejected": {"min_score": None, "meaning": "Clearly poor setup or blocked symbol."},
    "unavailable": {"min_score": None, "meaning": "Cannot evaluate due to missing snapshot, bad data, or dependency failure."},
}

LENIENT_SCREENER_POLICY = {
    "primary_role": "Remove clearly bad symbols before Strategy Engine.",
    "not_allowed_to_decide": [
        "final trade/no-trade decision",
        "final long/short decision",
        "final signal score",
        "entry validity",
        "position size",
        "stop loss",
        "take profit",
        "execution routing",
    ],
    "should_pass": [
        "strong trend setups",
        "early trend setups",
        "reasonable mean-reversion setups",
        "neutral but active symbols",
        "developing setups worth deeper Strategy Engine review",
    ],
    "should_reject_or_defer": [
        "stale or gapped market data",
        "missing required timeframe data",
        "symbol already has an open position",
        "flat/dead symbols with no activity",
        "extreme volatility/news-spike conditions",
        "directionally incoherent chop with no range edge",
        "low activity with no structure",
    ],
}

DEFAULT_SUB_SCORE_BUCKETS = {
    "mtf_context": 20,
    "regime_usability": 20,
    "momentum_activity": 20,
    "setup_location": 20,
    "volatility_usability": 20,
}

HARD_REJECT_REASON_CODES = [
    "SNAPSHOT_UNAVAILABLE",
    "MARKET_DATA_UNHEALTHY",
    "MISSING_REQUIRED_TIMEFRAME",
    "SYMBOL_ALREADY_HAS_OPEN_POSITION",
    "TRADE_GUARDIAN_UNAVAILABLE",
]

SOFT_REASON_CODES = [
    "MTF_CONTEXT_OK",
    "MTF_CONTEXT_MIXED",
    "TREND_PATH_POSSIBLE",
    "MEAN_REVERSION_PATH_POSSIBLE",
    "MOMENTUM_ACTIVITY_PRESENT",
    "SETUP_LOCATION_USABLE",
    "VOLATILITY_USABLE",
    "LOW_CONVICTION_BUT_REVIEWABLE",
]


def build_candidate_filter_contract() -> dict:
    return {
        "schema_version": CANDIDATE_FILTER_SCHEMA_VERSION,
        "candidate_filter_version": CANDIDATE_FILTER_VERSION,
        "contract_version": CANDIDATE_FILTER_CONTRACT_VERSION,
        "candidate_filter_mode": CANDIDATE_FILTER_MODE,
        "policy": LENIENT_SCREENER_POLICY,
        "candidate_tiers": CANDIDATE_TIERS,
        "default_sub_score_buckets": DEFAULT_SUB_SCORE_BUCKETS,
        "hard_reject_reason_codes": HARD_REJECT_REASON_CODES,
        "soft_reason_codes": SOFT_REASON_CODES,
        "strategy_path_hint_policy": {
            "trend_following_possible": "True when structure/regime/momentum indicate Strategy Engine should evaluate v1 trend-following logic.",
            "mean_reversion_possible": "True when Sideways/range/edge conditions indicate Strategy Engine should evaluate v1 mean-reversion logic.",
            "important": "Preserve both possible paths when uncertain. Do not reject because one path looks weak if the other may still be valid.",
        },
    }
