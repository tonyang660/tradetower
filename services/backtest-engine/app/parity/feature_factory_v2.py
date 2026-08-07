from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

FEATURE_FACTORY_VERSION = 'backtest_feature_factory_v2_bounded_history_v1'
MARKET_SNAPSHOT_SCHEMA_VERSION = 'market_snapshot_v2'
ROLES = ('5m', '15m', '1h', '4h')
FEATURE_LOOKBACK_ROWS = 250


def _asdict(c):
    if isinstance(c, dict):
        return c
    if all(hasattr(c, key) for key in ('open', 'high', 'low', 'close')):
        return {
            'timestamp': getattr(c, 'timestamp', None),
            'open': getattr(c, 'open'),
            'high': getattr(c, 'high'),
            'low': getattr(c, 'low'),
            'close': getattr(c, 'close'),
            'volume': getattr(c, 'volume', 0.0),
        }
    if hasattr(c, 'to_dict'):
        return c.to_dict()
    return dict(getattr(c, '__dict__', {}))


def _ts(v):
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, (int, float)):
        dt = datetime.fromtimestamp(float(v) / 1000, tz=timezone.utc)
    else:
        s = str(v)
        if s.isdigit():
            dt = datetime.fromtimestamp(float(s) / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _col(r, k, alt=None, default=0.0):
    return float(r.get(k, r.get(alt, default)) or default)


def _ema(vals, p):
    if not vals:
        return 0.0
    k = 2 / (p + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _sma(vals, p):
    d = vals[-p:]
    return sum(d) / len(d) if d else 0.0


def _rsi(vals, p=14):
    if len(vals) < p + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(-p, 0):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(abs(min(d, 0)))
    ag = sum(gains) / p
    al = sum(losses) / p
    return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))


def _true_ranges(rows):
    if len(rows) < 2:
        return []
    values = []
    for i in range(1, len(rows)):
        h = _col(rows[i], 'high', 'h')
        l = _col(rows[i], 'low', 'l')
        pc = _col(rows[i - 1], 'close', 'c')
        values.append(max(h - l, abs(h - pc), abs(l - pc)))
    return values


def _block(rows, tf):
    source_row_count = len(rows)
    rows = [_asdict(r) for r in rows[-FEATURE_LOOKBACK_ROWS:]]
    if not rows:
        return {
            'indicators': {},
            'structure': {},
            'volatility': {},
            'regime_inputs': {
                'v1_regime': 'unknown',
                'v1_regime_strategy': 'unknown',
            },
            'latest': {},
            'data_quality': {'healthy': False, 'reason': 'NO_ROWS'},
        }

    closes = [_col(r, 'close', 'c') for r in rows]
    highs = [_col(r, 'high', 'h') for r in rows]
    lows = [_col(r, 'low', 'l') for r in rows]

    c = closes[-1]
    true_ranges = _true_ranges(rows)
    atr_sample = true_ranges[-14:]
    atr = sum(atr_sample) / len(atr_sample) if atr_sample else 0.0
    atr_vals = []
    for row_count in range(max(15, len(rows) - 20), len(rows) + 1):
        tr_count = max(0, row_count - 1)
        sample = true_ranges[max(0, tr_count - 14):tr_count]
        if sample:
            atr_vals.append(sum(sample) / len(sample))
    atr_sma = sum(atr_vals) / len(atr_vals) if atr_vals else atr
    atr_ratio = atr / atr_sma if atr_sma else 1.0

    ema_12 = _ema(closes, 12)
    ema_21 = _ema(closes, 21)
    ema_26 = _ema(closes, 26)
    ema_50 = _ema(closes, 50)
    ema_200 = _ema(closes, 200)
    macd = ema_12 - ema_26 if len(closes) >= 35 else 0.0
    signal = macd * 0.8
    hist = macd - signal
    if len(closes) < 50:
        tr = 'neutral'
    elif c > ema_21 > ema_50:
        tr = 'bullish'
    elif c < ema_21 < ema_50:
        tr = 'bearish'
    else:
        tr = 'neutral'

    regime = (
        'Uptrend' if tr == 'bullish' and atr_ratio <= 2
        else 'Downtrend' if tr == 'bearish' and atr_ratio <= 2
        else 'Sideways'
    )
    strat = 'Trend-Following' if regime in ('Uptrend', 'Downtrend') else 'Mean-Reversion'

    sh = max(highs[-20:])
    sl = min(lows[-20:])
    mean = _sma(closes, 20)
    pos = (c - sl) / (sh - sl) if sh > sl else 0.5

    latest = rows[-1]
    ts = latest.get('timestamp') or latest.get('open_time') or latest.get('time')

    return {
        'indicators': {
            'close': c,
            'ema_fast': ema_21,
            'ema_21': ema_21,
            'ema_50': ema_50,
            'ema_200': ema_200,
            'rsi_14': _rsi(closes),
            'atr_14': atr,
            'atr': atr,
            'atr_sma_20': atr_sma,
            'macd': macd,
            'macd_signal': signal,
            'macd_hist': hist,
            'macd_histogram': hist,
            'macd_histogram_slope': hist,
        },
        'structure': {
            'v1_trend_direction': tr,
            'trend_direction': tr,
            'swing_high': sh,
            'swing_low': sl,
            'mean_reversion_range': {
                'valid': sh > sl,
                'mid': mean,
                'upper': sh,
                'lower': sl,
                'position_pct': pos,
            },
            'break_of_structure': {
                'bullish': {'detected': c >= sh, 'level': sh},
                'bearish': {'detected': c <= sl, 'level': sl},
            },
        },
        'volatility': {
            'atr': atr,
            'atr_ratio': atr_ratio,
            'volatility_regime': (
                'high' if atr_ratio > 1.5 else 'low' if atr_ratio < 0.7 else 'normal'
            ),
        },
        'regime_inputs': {
            'v1_regime': regime,
            'v1_regime_strategy': strat,
            'trend_direction': tr,
            'price_velocity': {
                'short_6_bars': (c - closes[-7]) / closes[-7] if len(closes) >= 7 and closes[-7] else 0,
                'medium_12_bars': (c - closes[-13]) / closes[-13] if len(closes) >= 13 and closes[-13] else 0,
            },
        },
        'price_action': {'range_position_pct': pos},
        'latest': {
            'timestamp': _ts(ts).isoformat(),
            'open': _col(latest, 'open', 'o', c),
            'high': _col(latest, 'high', 'h', c),
            'low': _col(latest, 'low', 'l', c),
            'close': c,
            'volume': _col(latest, 'volume', 'v', 0),
        },
        'data_quality': {
            'healthy': True,
            'rows': len(rows),
            'source_rows': source_row_count,
            'lookback_limit': FEATURE_LOOKBACK_ROWS,
            'last_timestamp': _ts(ts).isoformat(),
        },
        'history': {'close': closes[-250:]},
    }


def build_market_snapshot_v2(
    symbol: str,
    timeframe_rows: dict[str, list[Any]],
    timestamp=None,
):
    tfs = {tf: _block(timeframe_rows.get(tf, []), tf) for tf in ROLES}
    biases = [tfs[tf]['structure'].get('v1_trend_direction') for tf in ('5m', '15m', '4h')]

    bull = sum(1 for b in biases if b == 'bullish')
    bear = sum(1 for b in biases if b == 'bearish')
    consensus = 'long' if bull >= 2 else 'short' if bear >= 2 else 'mixed'

    return {
        'schema_version': MARKET_SNAPSHOT_SCHEMA_VERSION,
        'contract_version': 'phase16f_backtest_market_snapshot_contract',
        'symbol': symbol.upper(),
        'timestamp': (timestamp or datetime.now(timezone.utc)).isoformat(),
        'versions': {'feature_factory_version': FEATURE_FACTORY_VERSION},
        'timeframes': tfs,
        'multi_timeframe_context': {
            'alignment': {
                'consensus': consensus,
                'alignment_score': max(bull, bear) / 3,
                'entry_bias': biases[0],
                'primary_bias': biases[1],
                'htf_bias': biases[2],
            },
            'btc_macro_policy': {
                'enabled': symbol.upper() != 'BTCUSDT',
                'mode': 'proxy_from_htf_alignment',
            },
        },
        'data_quality': {
            'healthy': all(tfs[tf]['data_quality'].get('healthy') for tf in tfs),
            'required_timeframes': ['5m', '15m', '4h'],
        },
    }