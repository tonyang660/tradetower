from __future__ import annotations
from parity.snapshot_v1_adapter import direction_bias,get_bos_for_direction,get_indicator,get_mean_reversion_range,get_volatility_value,latest_close,safe_float,validate_snapshot_for_strategy
TREND_ENTRY_VALIDATOR_VERSION='phase16f_v1_entry_validation'
def _res(valid,direction,stype,reason,failed=None,passed=None,details=None): return {'valid':valid,'validator_version':TREND_ENTRY_VALIDATOR_VERSION,'direction':direction,'strategy_type':stype,'reason':reason,'failed_conditions':failed or [],'passed_conditions':passed or [],'details':details or {}}
def check_v1_entry(snapshot,selected_strategy,direction):
    valid,reasons=validate_snapshot_for_strategy(snapshot)
    if not valid: return _res(False,direction,selected_strategy,'SNAPSHOT_NOT_READY_FOR_STRATEGY',reasons)
    if selected_strategy=='trend_following':
        failed=[]; passed=[]; details={}; pb=direction_bias(snapshot,'primary'); hb=direction_bias(snapshot,'htf'); atr=safe_float(get_volatility_value(snapshot,'primary','atr_ratio',1.0),1.0); hist=safe_float(get_indicator(snapshot,'entry','macd_hist',0.0)); slope=safe_float(get_indicator(snapshot,'entry','macd_histogram_slope',0.0)); price=latest_close(snapshot,'entry'); ema=safe_float(get_indicator(snapshot,'entry','ema_fast',get_indicator(snapshot,'entry','ema_21',0.0)))
        passed.append('PRIMARY_TREND_ALIGNED') if pb==direction else failed.append('PRIMARY_TREND_NOT_ALIGNED')
        passed.append('HTF_NOT_OPPOSING') if hb in (direction,'neutral') else failed.append('HTF_OPPOSES_DIRECTION')
        passed.append('VOLATILITY_USABLE') if .7<=atr<=2.0 else failed.append('VOLATILITY_NOT_USABLE')
        macd_ok=(hist>=0 and slope>=0) if direction=='long' else (hist<=0 and slope<=0); ema_ok=bool(price and ema and abs(price-ema)/ema<=0.002)
        passed.append('ENTRY_TRIGGER_PRESENT') if (macd_ok or ema_ok) else failed.append('NO_ENTRY_TRIGGER')
        bos=get_bos_for_direction(snapshot,direction); passed.append('BOS_CONFIRMS_DIRECTION') if bos.get('detected') else None
        details={'atr_ratio':atr,'macd_hist':hist,'macd_slope':slope,'price':price,'ema_fast':ema,'bos':bos}
        return _res(len(failed)==0,direction,'trend_following','ENTRY_VALID' if not failed else failed[0],failed,passed,details)
    if selected_strategy=='mean_reversion':
        rng=get_mean_reversion_range(snapshot,'primary'); pos=float(rng.get('position_pct',.5) or .5); failed=[]; passed=[]
        if not rng.get('valid'): failed.append('MEAN_REVERSION_RANGE_NOT_VALID')
        elif direction=='long' and pos<=.25: passed.append('LOW_RANGE_EXTREMITY')
        elif direction=='short' and pos>=.75: passed.append('HIGH_RANGE_EXTREMITY')
        else: failed.append('NO_MEAN_REVERSION_EXTREMITY')
        return _res(len(failed)==0,direction,'mean_reversion','ENTRY_VALID' if not failed else failed[0],failed,passed,{'range':rng})
    return _res(False,direction,selected_strategy,'UNKNOWN_STRATEGY_TYPE',['UNKNOWN_STRATEGY_TYPE'])
