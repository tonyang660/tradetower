from __future__ import annotations
from typing import Any

from market_snapshot import MarketSnapshot
from parity.feature_factory_v2 import build_market_snapshot_v2
from parity.production_parity import analyze_market_snapshot_v2
from strategies.base import (
    StrategyContext,
    StrategyDecision,
    StrategyMetadata,
    risk_quantity,
    smart_round,
)


class TradeTowerBaselineV1Strategy:
    metadata = StrategyMetadata(
        name='tradetower_baseline_v1',
        version='0.2.0',
        family='production_parity',
        description='Phase 16F Feature Factory + Candidate Filter + Strategy Engine parity layer.',
        required_timeframes=['5m', '15m', '4h'],
        required_indicators=[
            'market_snapshot_v2',
            'candidate_filter_v2',
            'strategy_signal_v2',
        ],
        tags=[
            'phase16f',
            'production_parity',
            'feature_factory',
            'candidate_filter',
            'strategy_engine',
        ],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def _timeframe_rows(self, snapshot: MarketSnapshot, symbol: str):
        # Preferred future shape from cycle simulator: snapshot.timeframe_history[symbol][timeframe]
        data = getattr(snapshot, 'timeframe_history', None)
        if data and symbol in data:
            return data[symbol]

        # Compatibility fallback from existing close_history so system still runs until cycle builder is upgraded.
        hist = (getattr(snapshot, 'close_history', {}) or {}).get(symbol, [])
        rows = []
        for c in hist:
            rows.append({
                'timestamp': snapshot.timestamp.isoformat(),
                'open': c,
                'high': c,
                'low': c,
                'close': c,
                'volume': 0.0,
            })
            
        return {'5m': rows, '15m': rows, '1h': rows, '4h': rows}

    def evaluate_symbol(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
        context: StrategyContext | None = None,
    ) -> StrategyDecision:
        symbol = str(symbol).upper()
        ms = build_market_snapshot_v2(
            symbol,
            self._timeframe_rows(snapshot, symbol),
            timestamp=snapshot.timestamp,
        )
        
        acct = {}
        if context and getattr(context, 'account_context', None):
            acct.update(context.account_context)

        acct.update({
            'strategy_trade_threshold': self.config.get('strategy_trade_threshold', 75),
            'strategy_btc_trade_threshold': self.config.get('strategy_btc_trade_threshold', 80),
            'strategy_observe_threshold': self.config.get('strategy_observe_threshold', 50),
        })

        signal = analyze_market_snapshot_v2(symbol, ms, account_context=acct)
        side = signal.get('decision_side')
        action = (
            'enter'
            if signal.get('decision') == 'trade_candidate' and side in ('long', 'short')
            else 'skip'
        )

        return StrategyDecision(
            symbol=symbol,
            action=action,
            side=side,
            score=signal.get('score'),
            confidence=signal.get('confidence'),
            regime=signal.get('regime', 'unknown'),
            macro_bias=(signal.get('snapshot_refs', {}) or {}).get('primary_regime', 'neutral'),
            selected_strategy=signal.get('selected_strategy', 'none'),
            reason=signal.get('reason', 'UNKNOWN'),
            reason_tags=signal.get('reason_tags', []),
            debug={
                'strategy_signal': signal,
                'market_snapshot_v2': ms,
                'candidate_filter_context': signal.get('candidate_filter_context'),
                'production_parity_version': 'phase16f_feature_candidate_strategy_parity',
            },
        )

    def build_entry_plan(
        self,
        snapshot: MarketSnapshot,
        decision: StrategyDecision,
        equity: float,
        risk_per_trade_pct: float,
    ):
        if decision.action != 'enter' or decision.side not in {'long', 'short'}:
            return None

        trade = (decision.debug.get('strategy_signal', {}) or {}).get('proposed_trade') or {}
        if not trade.get('valid'):
            return None

        entry = float(trade['entry_price'])
        stop = float(trade['stop_loss'])
        qty = risk_quantity(entry, stop, equity, risk_per_trade_pct)
        if qty <= 0:
            return None

        tps = trade.get('take_profits') or []
        tp1 = float(tps[0]['price']) if len(tps) > 0 else entry
        tp2 = float(tps[1]['price']) if len(tps) > 1 else tp1
        tp3 = float(tps[2]['price']) if len(tps) > 2 else tp2

        return {
            'symbol': decision.symbol,
            'side': decision.side,
            'entry': smart_round(entry),
            'stop': smart_round(stop),
            'tp1': smart_round(tp1),
            'tp2': smart_round(tp2),
            'tp3': smart_round(tp3),
            'qty': qty,
            'regime': decision.regime,
            'score': decision.score or 0.0,
            'confidence': decision.confidence or 0.0,
            'reason_tags': decision.reason_tags,
            'debug': {
                **decision.debug,
                'cycle_index': snapshot.cycle_index,
                'timestamp': snapshot.timestamp.isoformat(),
            },
        }