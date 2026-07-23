from __future__ import annotations
from parity.snapshot_v1_adapter import (
    get_indicator,
    get_mtf_alignment,
    get_volatility_value,
    latest_close,
    safe_float,
)

SIGNAL_SCORER_VERSION = 'phase16f_v1_signal_scorer'


def score_v1_signal(snapshot, direction, selected_strategy, symbol):
    mtf = get_mtf_alignment(snapshot)
    consensus = mtf.get('consensus')
    atr = safe_float(get_volatility_value(snapshot, 'primary', 'atr_ratio', 1.0), 1.0)
    rsi = safe_float(get_indicator(snapshot, 'primary', 'rsi_14', 50), 50)
    hist = safe_float(get_indicator(snapshot, 'primary', 'macd_hist', 0), 0)
    close = latest_close(snapshot, 'primary')
    ema = safe_float(get_indicator(snapshot, 'primary', 'ema_21', 0), 0)
    br = {}

    if selected_strategy == 'trend_following':
        br = {
            'mtf_alignment': 25 if consensus == direction else 12 if consensus == 'mixed' else 0,
            'momentum': 25 if (hist >= 0 and direction == 'long') or (hist <= 0 and direction == 'short') else 10,
            'ema_location': 20 if (close >= ema and direction == 'long') or (close <= ema and direction == 'short') else 8,
            'rsi_room': 15 if (direction == 'long' and rsi < 75) or (direction == 'short' and rsi > 25) else 5,
            'volatility': 15 if 0.7 <= atr <= 2.0 else 5,
        }
    elif selected_strategy == 'mean_reversion':
        pos = (
            ((snapshot.get('timeframes', {}) or {}).get('15m', {}) or {})
            .get('structure', {})
            .get('mean_reversion_range', {})
            .get('position_pct', 0.5)
        )
        br = {
            'range_extremity': 35 if (direction == 'long' and pos <= 0.25) or (direction == 'short' and pos >= 0.75) else 10,
            'mtf_not_trending': 20 if consensus in ('mixed', 'neutral', None) else 8,
            'rsi_reversion': 20 if (direction == 'long' and rsi < 45) or (direction == 'short' and rsi > 55) else 8,
            'volatility': 15 if 0.7 <= atr <= 2.0 else 5,
            'structure': 10,
        }

    score = round(max(0, min(100, sum(float(v) for v in br.values()))), 2)

    return {
        'ok': score > 0,
        'scorer_version': SIGNAL_SCORER_VERSION,
        'symbol': symbol,
        'direction': direction,
        'strategy_type': selected_strategy,
        'score': score,
        'max_score': 100,
        'breakdown': br,
        'reason_tags': [
            f'SCORE_{selected_strategy.upper()}',
            f'DIRECTION_{direction.upper()}',
        ],
        'details': {
            'rsi_14': rsi,
            'macd_hist': hist,
            'atr_ratio': atr,
            'mtf_consensus': consensus,
        },
    }