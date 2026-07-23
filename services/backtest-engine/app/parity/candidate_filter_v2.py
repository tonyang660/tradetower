from __future__ import annotations
from typing import Any
from parity.snapshot_v1_adapter import direction_bias,get_mean_reversion_range,get_mtf_alignment,get_primary,get_volatility_value,latest_close,validate_snapshot_for_strategy
CANDIDATE_FILTER_VERSION='phase16f_candidate_filter_v2'; CANDIDATE_FILTER_MODE='lenient_screener'
def _tier(score,rejected=False,unavailable=False):
    if unavailable: return 'unavailable'
    if rejected or score<35: return 'rejected'
    if score>=70: return 'strong_candidate'
    if score>=50: return 'candidate'
    return 'weak_candidate'
def evaluate_candidate(snapshot:dict[str,Any],*,account_context:dict[str,Any]|None=None):
    account_context=account_context or {}; valid,reasons=validate_snapshot_for_strategy(snapshot); symbol=str(snapshot.get('symbol') or '').upper()
    if not valid: return {'candidate_filter_version':CANDIDATE_FILTER_VERSION,'candidate_filter_mode':CANDIDATE_FILTER_MODE,'symbol':symbol,'passed':False,'tier':'unavailable','score':0,'reason_codes':['SNAPSHOT_UNAVAILABLE']+reasons,'strategy_path_hints':{'trend_following_possible':False,'mean_reversion_possible':False}}
    if symbol in {str(s).upper() for s in account_context.get('open_symbols',[])}: return {'candidate_filter_version':CANDIDATE_FILTER_VERSION,'candidate_filter_mode':CANDIDATE_FILTER_MODE,'symbol':symbol,'passed':False,'tier':'rejected','score':0,'reason_codes':['SYMBOL_ALREADY_HAS_OPEN_POSITION'],'strategy_path_hints':{}}
    primary=get_primary(snapshot); regime=primary.regime_inputs.get('v1_regime'); regime_strategy=primary.regime_inputs.get('v1_regime_strategy'); mtf=get_mtf_alignment(snapshot); consensus=mtf.get('consensus'); pb=direction_bias(snapshot,'primary'); hb=direction_bias(snapshot,'htf'); atr=float(get_volatility_value(snapshot,'primary','atr_ratio',1.0) or 1.0); rng=get_mean_reversion_range(snapshot); price=latest_close(snapshot); ema=float(primary.indicators.get('ema_fast') or primary.indicators.get('ema_21') or 0.0); macd=abs(float(primary.indicators.get('macd_hist') or 0.0))
    sub={'mtf_context':20 if consensus in ('long','short') and pb==hb and pb!='neutral' else 12 if consensus=='mixed' else 8,'regime_usability':20 if regime in ('Uptrend','Downtrend','Sideways') else 0,'momentum_activity':20 if macd>0 else 10,'setup_location':20 if rng.get('valid') or (price and ema and abs(price-ema)/ema<0.01) else 10,'volatility_usability':20 if 0.7<=atr<=2.0 else 8}
    score=sum(sub.values()); rejected=atr>3.0; tier=_tier(score,rejected=rejected); reasons=[]
    if sub['mtf_context']>=12: reasons.append('MTF_CONTEXT_OK' if sub['mtf_context']==20 else 'MTF_CONTEXT_MIXED')
    if regime_strategy=='Trend-Following': reasons.append('TREND_PATH_POSSIBLE')
    if regime_strategy=='Mean-Reversion' or rng.get('valid'): reasons.append('MEAN_REVERSION_PATH_POSSIBLE')
    reasons += ['MOMENTUM_ACTIVITY_PRESENT','SETUP_LOCATION_USABLE']
    if sub['volatility_usability']>=20: reasons.append('VOLATILITY_USABLE')
    if rejected: reasons.append('EXTREME_VOLATILITY_DEFER')
    return {'schema_version':'candidate_filter_v2','candidate_filter_version':CANDIDATE_FILTER_VERSION,'candidate_filter_mode':CANDIDATE_FILTER_MODE,'symbol':symbol,'passed':tier!='rejected','tier':tier,'score':round(score,2),'sub_scores':sub,'reason_codes':reasons,'strategy_path_hints':{'trend_following_possible':regime_strategy=='Trend-Following' or pb in ('long','short'),'mean_reversion_possible':regime_strategy=='Mean-Reversion' or bool(rng.get('valid'))},'policy_note':'lenient pre-screen only; Strategy Engine makes final decision'}
