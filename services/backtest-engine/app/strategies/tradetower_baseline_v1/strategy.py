from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any

from market_snapshot import MarketSnapshot
from parity.production_candidate_filter import rank_market_snapshots
from parity.production_feature_factory import ProductionFeatureSnapshotCache
from parity.production_strategy_engine import analyze_market_snapshot_v2
from strategies.base import (
    StrategyContext,
    StrategyDecision,
    StrategyMetadata,
    risk_quantity,
    smart_round,
)


def production_take_profit_prices(take_profits: Any, entry_price: float) -> tuple[float, float, float]:
    """Normalize the production keyed TP contract without changing its values."""
    if isinstance(take_profits, dict):
        ordered = [
            take_profits.get('tp1'),
            take_profits.get('tp2'),
            take_profits.get('tp3'),
        ]
    elif isinstance(take_profits, (list, tuple)):
        ordered = list(take_profits[:3])
    else:
        ordered = []

    prices: list[float] = []
    fallback = float(entry_price)
    for item in ordered:
        if isinstance(item, dict) and item.get('price') is not None:
            fallback = float(item['price'])
        prices.append(fallback)

    while len(prices) < 3:
        prices.append(prices[-1] if prices else fallback)
    return prices[0], prices[1], prices[2]


class TradeTowerBaselineV1Strategy:
    metadata = StrategyMetadata(
        name='tradetower_baseline_v1',
        version='1.0.0',
        family='production_parity',
        description='Backtest adapter over exact production Feature Factory, Candidate Filter, and Strategy Engine policies.',
        required_timeframes=['5m', '15m', '1h', '4h'],
        required_indicators=[
            'market_snapshot_v2',
            'candidate_filter_v2',
            'strategy_signal_v2',
        ],
        tags=[
            'production_source_runtime',
            'production_parity',
            'feature_factory',
            'candidate_filter',
            'strategy_engine',
        ],
    )

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._cycle_timestamp = None
        self._market_snapshots: dict[str, dict[str, Any]] = {}
        self._candidate_payload: dict[str, Any] = {"by_symbol": {}}
        self._feature_cache = ProductionFeatureSnapshotCache()
        requested_workers = max(1, int(self.config.get('backtest_feature_workers', 1) or 1))
        symbol_count = max(1, len(self.config.get('symbols', []) or []))
        self._feature_workers = min(8, requested_workers, symbol_count)
        self._feature_executor = (
            ThreadPoolExecutor(
                max_workers=self._feature_workers,
                thread_name_prefix='backtest-production-feature',
            )
            if self._feature_workers > 1
            else None
        )
        self._last_feature_diagnostics: dict[str, Any] = {}

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

    def prepare_features(
        self,
        snapshot: MarketSnapshot,
        *,
        symbols: list[str],
    ) -> dict[str, Any]:
        if self._cycle_timestamp == snapshot.timestamp:
            return {
                'cycle_snapshot_reused': True,
                'symbols': len(self._market_snapshots),
                'workers': self._feature_workers,
                'blocks_built': 0,
                'blocks_reused': 0,
                'compute_seconds': 0.0,
                'wall_seconds': 0.0,
                'by_timeframe': {},
            }

        started_at = time.perf_counter()
        selected_symbols = [
            str(symbol).upper()
            for symbol in symbols
            if str(symbol).upper() in snapshot.closes
        ]

        def build_symbol(symbol: str):
            market_snapshot, diagnostics = self._feature_cache.build_market_snapshot_v2(
                symbol,
                self._timeframe_rows(snapshot, symbol),
                timestamp=snapshot.timestamp,
            )
            return symbol, market_snapshot, diagnostics

        if self._feature_executor is not None and len(selected_symbols) > 1:
            results = list(self._feature_executor.map(build_symbol, selected_symbols))
        else:
            results = [build_symbol(symbol) for symbol in selected_symbols]

        self._cycle_timestamp = snapshot.timestamp
        self._market_snapshots = {
            symbol: market_snapshot
            for symbol, market_snapshot, _ in results
        }

        by_timeframe: dict[str, dict[str, float | int]] = {}
        blocks_built = 0
        blocks_reused = 0
        compute_seconds = 0.0
        for _, _, diagnostics in results:
            blocks_built += int(diagnostics.get('blocks_built', 0))
            blocks_reused += int(diagnostics.get('blocks_reused', 0))
            compute_seconds += float(diagnostics.get('compute_seconds', 0.0))
            for timeframe, values in (diagnostics.get('by_timeframe', {}) or {}).items():
                aggregate = by_timeframe.setdefault(
                    timeframe,
                    {'built': 0, 'reused': 0, 'compute_seconds': 0.0},
                )
                aggregate['built'] += int(values.get('built', 0))
                aggregate['reused'] += int(values.get('reused', 0))
                aggregate['compute_seconds'] += float(values.get('compute_seconds', 0.0))

        self._last_feature_diagnostics = {
            'cycle_snapshot_reused': False,
            'symbols': len(results),
            'workers': self._feature_workers,
            'blocks_built': blocks_built,
            'blocks_reused': blocks_reused,
            'compute_seconds': compute_seconds,
            'wall_seconds': time.perf_counter() - started_at,
            'by_timeframe': by_timeframe,
        }
        return self._last_feature_diagnostics

    def rank_candidates(
        self,
        *,
        excluded_symbols: set[str] | None = None,
    ) -> dict[str, Any]:
        self._candidate_payload = rank_market_snapshots(
            self._market_snapshots,
            excluded_symbols=excluded_symbols,
        )
        return self._candidate_payload

    def prepare_cycle(
        self,
        snapshot: MarketSnapshot,
        *,
        symbols: list[str],
        excluded_symbols: set[str] | None = None,
    ) -> dict[str, Any]:
        """Compatibility entrypoint for callers that do not split the stages."""
        self.prepare_features(snapshot, symbols=symbols)
        return self.rank_candidates(excluded_symbols=excluded_symbols)

    def close(self) -> None:
        if self._feature_executor is not None:
            self._feature_executor.shutdown(wait=True)
            self._feature_executor = None

    def current_regime(self, symbol: str) -> str | None:
        snapshot = self._market_snapshots.get(str(symbol).upper()) or {}
        primary = ((snapshot.get('timeframes', {}) or {}).get('15m', {}) or {})
        return (primary.get('regime_inputs', {}) or {}).get('v1_regime')

    def decision_symbol_order(self, symbols: list[str]) -> list[str]:
        selected = [item['symbol'] for item in (self._candidate_payload.get('candidates', []) or [])]
        selected_set = set(selected)
        return selected + [str(symbol).upper() for symbol in symbols if str(symbol).upper() not in selected_set]

    def evaluate_symbol(
        self,
        snapshot: MarketSnapshot,
        symbol: str,
        context: StrategyContext | None = None,
    ) -> StrategyDecision:
        symbol = str(symbol).upper()
        if self._cycle_timestamp != snapshot.timestamp or symbol not in self._market_snapshots:
            self.prepare_cycle(snapshot, symbols=list(snapshot.symbols))
        ms = self._market_snapshots[symbol]
        candidate = (self._candidate_payload.get('by_symbol', {}) or {}).get(symbol)

        if candidate is None:
            return StrategyDecision(
                symbol=symbol,
                action='skip',
                side='neutral',
                score=0.0,
                confidence=0.0,
                regime='unknown',
                macro_bias='neutral',
                selected_strategy='none',
                reason='CANDIDATE_FILTER_NOT_SELECTED',
                reason_tags=['CANDIDATE_FILTER_NOT_SELECTED'],
                debug={
                    'market_snapshot_v2': ms,
                    'candidate_filter_payload': self._candidate_payload,
                    'production_parity_version': 'production_source_runtime_v1',
                },
            )
        
        acct = {}
        if context and getattr(context, 'account_context', None):
            acct.update(context.account_context)

        acct.update({
            'strategy_trade_threshold': self.config.get('strategy_trade_threshold', 75),
            'strategy_btc_trade_threshold': self.config.get('strategy_btc_trade_threshold', 80),
            'strategy_observe_threshold': self.config.get('strategy_observe_threshold', 50),
        })

        signal = analyze_market_snapshot_v2(
            symbol,
            ms,
            account_context=acct,
            candidate_filter_context=candidate,
        )
        side = signal.get('decision_side')
        action = (
            'enter'
            if signal.get('v2_decision') == 'trade_candidate' and side in ('long', 'short')
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
                'candidate_filter_context': candidate,
                'production_parity_version': 'production_source_runtime_v1',
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

        tp1, tp2, tp3 = production_take_profit_prices(
            trade.get('take_profits'),
            entry,
        )

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
