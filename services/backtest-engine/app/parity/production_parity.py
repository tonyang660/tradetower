from __future__ import annotations
from parity.candidate_filter_v2 import evaluate_candidate
from parity.decision_policy import decide_strategy_signal
from parity.entry_logic import check_v1_entry
from parity.feature_factory_v2 import build_market_snapshot_v2
from parity.regime_router import route_regime
from parity.scorer import score_v1_signal
from parity.snapshot_v1_adapter import (
    build_snapshot_refs,
    validate_snapshot_for_strategy,
)
from parity.trade_levels import build_proposed_trade

PRODUCTION_PARITY_VERSION = 'phase16f_feature_candidate_strategy_parity'


def _directions(route):
    if route.get('selected_strategy') == 'trend_following':
        return [route.get('direction_hint')] if route.get('direction_hint') in ('long', 'short') else []
    if route.get('selected_strategy') == 'mean_reversion':
        return ['long', 'short']
    return []


def _rank(x):
    return (
        1 if x.get('entry_validation', {}).get('valid') else 0,
        float(x.get('score_result', {}).get('score', 0) or 0),
    )


def analyze_market_snapshot_v2(symbol, snapshot, *, account_context=None):
    symbol = symbol.upper()
    account_context = account_context or {}
    candidate = evaluate_candidate(snapshot, account_context=account_context)

    refs = build_snapshot_refs(snapshot)
    refs['production_parity_version'] = PRODUCTION_PARITY_VERSION

    valid, reasons = validate_snapshot_for_strategy(snapshot)
    if not valid:
        route = {
            'valid': False,
            'regime': 'unknown',
            'selected_strategy': 'none',
            'direction_hint': 'neutral',
            'reason_tags': ['SNAPSHOT_NOT_READY_FOR_STRATEGY'] + reasons,
        }
        entry = {
            'valid': False,
            'direction': 'neutral',
            'strategy_type': 'none',
            'reason': 'SNAPSHOT_NOT_READY_FOR_STRATEGY',
            'failed_conditions': reasons,
            'passed_conditions': [],
            'details': {},
        }
        score = {
            'ok': False,
            'score': 0,
            'reason_tags': ['SNAPSHOT_NOT_READY_FOR_STRATEGY'],
        }
        return decide_strategy_signal(
            symbol=symbol,
            regime_route=route,
            entry_validation=entry,
            score_result=score,
            account_context=account_context,
            snapshot_refs=refs,
            candidate_filter_context=candidate,
            proposed_trade=None,
        )

    route = route_regime(snapshot)
    evaluated = []

    for direction in _directions(route):
        entry = check_v1_entry(snapshot, route.get('selected_strategy'), direction)
        score = score_v1_signal(snapshot, direction, route.get('selected_strategy'), symbol)
        
        proposed = (
            build_proposed_trade(
                snapshot,
                symbol=symbol,
                direction=direction,
                selected_strategy=route.get('selected_strategy'),
                regime=route.get('regime'),
                score=score.get('score'),
            )
            if entry.get('valid')
            else None
        )
        evaluated.append({
            'direction': direction,
            'entry_validation': entry,
            'score_result': score,
            'proposed_trade': proposed,
        })

    best = sorted(evaluated, key=_rank, reverse=True)[0] if evaluated else None

    if best:
        entry, score, proposed = best['entry_validation'], best['score_result'], best['proposed_trade']
    else:
        entry = {
            'valid': False,
            'direction': 'neutral',
            'strategy_type': route.get('selected_strategy'),
            'reason': 'NO_DIRECTION_CANDIDATE',
            'failed_conditions': ['NO_DIRECTION_CANDIDATE'],
            'passed_conditions': [],
            'details': {},
        }
        score = {'ok': False, 'score': 0, 'reason_tags': ['NO_DIRECTION_CANDIDATE']}
        proposed = None

    signal = decide_strategy_signal(
        symbol=symbol,
        regime_route=route,
        entry_validation=entry,
        score_result=score,
        account_context=account_context,
        snapshot_refs=refs,
        candidate_filter_context=candidate,
        proposed_trade=proposed,
    )

    signal['direction_evaluation'] = [
        {
            'direction': x['direction'],
            'entry_valid': x['entry_validation'].get('valid'),
            'entry_reason': x['entry_validation'].get('reason'),
            'score': x['score_result'].get('score'),
            'proposed_trade_valid': bool(x.get('proposed_trade')),
        }
        for x in evaluated
    ]
    return signal


def build_snapshot_from_timeframe_rows(symbol, timeframe_rows, timestamp=None):
    return build_market_snapshot_v2(symbol, timeframe_rows, timestamp=timestamp)