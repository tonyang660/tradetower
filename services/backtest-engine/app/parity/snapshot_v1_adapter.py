from __future__ import annotations
from typing import Any
ENTRY_TIMEFRAME='5m'; PRIMARY_TIMEFRAME='15m'; OPTIONAL_CONTEXT_TIMEFRAME='1h'; HTF_TIMEFRAME='4h'
MARKET_SNAPSHOT_SCHEMA_VERSION='market_snapshot_v2'; SNAPSHOT_ADAPTER_VERSION='phase16f_backtest_snapshot_v1_adapter'
ROLE_TO_TIMEFRAME={'entry':ENTRY_TIMEFRAME,'primary':PRIMARY_TIMEFRAME,'context':OPTIONAL_CONTEXT_TIMEFRAME,'htf':HTF_TIMEFRAME,'higher_timeframe':HTF_TIMEFRAME}
REQUIRED_TIMEFRAMES=(ENTRY_TIMEFRAME,PRIMARY_TIMEFRAME,HTF_TIMEFRAME)
def safe_float(v:Any,default:float=0.0)->float:
    try: return default if v is None else float(v)
    except Exception: return default
def normalize_symbol(s:Any)->str: return str(s or '').replace('-','').replace('/','').upper()
def get_timeframes(snapshot): return snapshot.get('timeframes',{}) or {}
def get_timeframe(snapshot,tf): return get_timeframes(snapshot).get(tf,{}) or {}
def get_role_block(snapshot,role): return get_timeframe(snapshot,ROLE_TO_TIMEFRAME[role])
def _block(snapshot,role,name): return get_role_block(snapshot,role).get(name,{}) or {}
def get_indicator(snapshot,role,name,default=None): return _block(snapshot,role,'indicators').get(name,default)
def get_structure_value(snapshot,role,name,default=None): return _block(snapshot,role,'structure').get(name,default)
def get_volatility_value(snapshot,role,name,default=None): return _block(snapshot,role,'volatility').get(name,default)
def get_regime_value(snapshot,role,name,default=None): return _block(snapshot,role,'regime_inputs').get(name,default)
def latest_close(snapshot,role='primary'):
    latest=_block(snapshot,role,'latest'); inds=_block(snapshot,role,'indicators')
    return safe_float(latest.get('close',latest.get('last',inds.get('close',0.0))))
def v1_trend_direction(snapshot,role='primary'):
    st=_block(snapshot,role,'structure'); rg=_block(snapshot,role,'regime_inputs')
    return st.get('v1_trend_direction') or rg.get('trend_direction') or st.get('trend_direction') or 'neutral'
def direction_bias(snapshot,role='primary'):
    t=str(v1_trend_direction(snapshot,role)).lower()
    if t in ('bullish','up','long'): return 'long'
    if t in ('bearish','down','short'): return 'short'
    return 'neutral'
def primary_regime(snapshot): return str(get_regime_value(snapshot,'primary','v1_regime','unknown'))
def primary_regime_strategy(snapshot): return str(get_regime_value(snapshot,'primary','v1_regime_strategy','unknown'))
def get_mean_reversion_range(snapshot,role='primary'): return get_structure_value(snapshot,role,'mean_reversion_range',{}) or {}
def get_break_of_structure(snapshot,role='primary'): return get_structure_value(snapshot,role,'break_of_structure',{}) or {}
def get_bos_for_direction(snapshot,direction,role='primary'):
    bos=get_break_of_structure(snapshot,role); return bos.get('bullish' if direction=='long' else 'bearish',{}) or {}
def get_mtf_context(snapshot): return snapshot.get('multi_timeframe_context',{}) or {}
def get_mtf_alignment(snapshot): return get_mtf_context(snapshot).get('alignment',{}) or {}
def get_data_quality(snapshot): return snapshot.get('data_quality',{}) or {}
def validate_snapshot_for_strategy(snapshot):
    reasons=[]
    if not isinstance(snapshot,dict): return False,['SNAPSHOT_NOT_OBJECT']
    if snapshot.get('schema_version')!=MARKET_SNAPSHOT_SCHEMA_VERSION: reasons.append('UNEXPECTED_MARKET_SNAPSHOT_SCHEMA')
    tfs=get_timeframes(snapshot)
    for tf in REQUIRED_TIMEFRAMES:
        if tf not in tfs: reasons.append(f'MISSING_TIMEFRAME:{tf}'); continue
        for b in ('indicators','structure','volatility','regime_inputs'):
            if b not in (tfs.get(tf,{}) or {}): reasons.append(f'MISSING_{tf}_{b}'.upper())
    if get_data_quality(snapshot).get('healthy') is False: reasons.append('MARKET_DATA_UNHEALTHY')
    return len(reasons)==0,reasons
def snapshot_is_data_healthy(snapshot): return validate_snapshot_for_strategy(snapshot)[0]
def build_snapshot_refs(snapshot):
    return {'adapter_version':SNAPSHOT_ADAPTER_VERSION,'market_snapshot_schema_version':snapshot.get('schema_version'),'feature_factory_version':(snapshot.get('versions',{}) or {}).get('feature_factory_version'),'symbol':normalize_symbol(snapshot.get('symbol')),'timeframe_roles':{'entry':ENTRY_TIMEFRAME,'primary':PRIMARY_TIMEFRAME,'context_1h':OPTIONAL_CONTEXT_TIMEFRAME,'htf':HTF_TIMEFRAME},'data_quality_healthy':snapshot_is_data_healthy(snapshot),'primary_regime':primary_regime(snapshot) if get_timeframe(snapshot,PRIMARY_TIMEFRAME) else 'unknown','primary_regime_strategy':primary_regime_strategy(snapshot) if get_timeframe(snapshot,PRIMARY_TIMEFRAME) else 'unknown'}
