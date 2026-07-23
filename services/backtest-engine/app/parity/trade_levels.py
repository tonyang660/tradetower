from __future__ import annotations
from parity.snapshot_v1_adapter import get_indicator,get_structure_value,latest_close,safe_float
TRADE_LEVELS_VERSION='phase16f_v1_trade_levels'; STOP_ATR_MULTIPLIER=2.5; TP_RATIOS=[1.5,2.5,3.5]; TP_CLOSE_PCTS=[50,30,20]
def build_proposed_trade(snapshot,*,symbol,direction,selected_strategy,regime,score,entry_order_type='limit'):
    entry=latest_close(snapshot,'entry') or latest_close(snapshot,'primary'); atr=safe_float(get_indicator(snapshot,'primary','atr_14',get_indicator(snapshot,'primary','atr',0.0)),0.0) or entry*.01
    if direction=='long': swing=safe_float(get_structure_value(snapshot,'primary','swing_low',0),0); stop=min(entry-atr*STOP_ATR_MULTIPLIER,swing) if swing>0 else entry-atr*STOP_ATR_MULTIPLIER; risk=entry-stop; tps=[entry+risk*r for r in TP_RATIOS]
    else: swing=safe_float(get_structure_value(snapshot,'primary','swing_high',0),0); stop=max(entry+atr*STOP_ATR_MULTIPLIER,swing) if swing>0 else entry+atr*STOP_ATR_MULTIPLIER; risk=stop-entry; tps=[entry-risk*r for r in TP_RATIOS]
    if entry<=0 or risk<=0: return {'valid':False,'reason':'INVALID_ENTRY_OR_RISK'}
    return {'valid':True,'levels_version':TRADE_LEVELS_VERSION,'symbol':symbol,'direction':direction,'selected_strategy':selected_strategy,'regime':regime,'score':score,'entry_order_type':entry_order_type,'entry_price':entry,'stop_loss':stop,'risk_per_unit':risk,'take_profits':[{'label':f'TP{i+1}','price':tps[i],'r_multiple':TP_RATIOS[i],'close_percent':TP_CLOSE_PCTS[i]} for i in range(3)],'details':{'atr':atr,'stop_atr_multiplier':STOP_ATR_MULTIPLIER,'swing_reference':swing}}
