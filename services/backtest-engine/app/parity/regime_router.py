from __future__ import annotations
from typing import Any
from parity.snapshot_v1_adapter import (
    direction_bias,
    get_mtf_alignment,
    primary_regime,
    primary_regime_strategy,
    validate_snapshot_for_strategy,
)

REGIME_ROUTER_VERSION = 'phase16f_regime_routing_parity'


def normalize_regime(v: Any):
    raw = str(v or '').strip()
    aliases = {
        'up': 'Uptrend',
        'uptrend': 'Uptrend',
        'bullish': 'Uptrend',
        'down': 'Downtrend',
        'downtrend': 'Downtrend',
        'bearish': 'Downtrend',
        'sideways': 'Sideways',
        'range': 'Sideways',
        'ranging': 'Sideways',
        'chop': 'Sideways',
        'neutral': 'Sideways',
    }
    return aliases.get(raw.lower(), raw if raw in ('Uptrend', 'Downtrend', 'Sideways') else 'unknown')


def route_regime(snapshot):
    valid, reasons = validate_snapshot_for_strategy(snapshot)
    if not valid:
        return {
            'valid': False,
            'router_version': REGIME_ROUTER_VERSION,
            'regime': 'unknown',
            'selected_strategy': 'none',
            'direction_hint': 'neutral',
            'confidence': 0,
            'reason_tags': ['SNAPSHOT_NOT_READY_FOR_STRATEGY'] + reasons,
            'details': {'validation_reasons': reasons},
        }

    regime = normalize_regime(primary_regime(snapshot))
    selected = (
        'trend_following' if regime in ('Uptrend', 'Downtrend')
        else 'mean_reversion' if regime == 'Sideways'
        else 'none'
    )
    hint = 'long' if regime == 'Uptrend' else 'short' if regime == 'Downtrend' else 'neutral'
    label = (
        'Trend-Following' if selected == 'trend_following'
        else 'Mean-Reversion' if selected == 'mean_reversion'
        else 'unknown'
    )
    
    mtf = get_mtf_alignment(snapshot)
    conf = 0.55
    tags = []

    if primary_regime_strategy(snapshot) == label:
        conf += 0.15
        tags.append('PRIMARY_REGIME_STRATEGY_MATCHES_ROUTE')

    if selected == 'trend_following' and mtf.get('consensus') == hint:
        conf += 0.15
        tags.append('MTF_CONSENSUS_SUPPORTS_TREND_ROUTE')

    base = [
        'REGIME_' + regime.upper() if regime != 'unknown' else 'REGIME_UNKNOWN',
        (
            'ROUTE_TREND_FOLLOWING' if selected == 'trend_following'
            else 'ROUTE_MEAN_REVERSION' if selected == 'mean_reversion'
            else 'ROUTE_NONE'
        ),
    ]

    return {
        'valid': selected != 'none',
        'router_version': REGIME_ROUTER_VERSION,
        'regime': regime,
        'regime_strategy': label,
        'selected_strategy': selected,
        'direction_hint': hint,
        'confidence': round(min(conf, 1), 2),
        'reason_tags': sorted(set(base + tags)),
        'source': 'primary_15m_regime_inputs',
        'details': {
            'primary_direction_bias': direction_bias(snapshot, 'primary'),
            'htf_direction_bias': direction_bias(snapshot, 'htf'),
            'mtf_consensus': mtf.get('consensus'),
            'v1_rule': 'Sideways -> mean_reversion; Uptrend/Downtrend -> trend_following',
        },
    }