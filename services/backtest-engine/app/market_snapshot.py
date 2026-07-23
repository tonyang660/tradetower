from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from historical_feed import CandleBar


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: datetime
    cycle_index: int
    symbols: list[str]
    bars: dict[str, CandleBar]
    closes: dict[str, float]
    highs: dict[str, float]
    lows: dict[str, float]
    close_history: dict[str, list[float]]
    warmup_required_bars: int
    warmup_ready: dict[str, bool]
    lookahead_guard: dict[str, Any]
    timeframe_history: dict[str, dict[str, list[CandleBar]]]

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cycle_index": self.cycle_index,
            "symbols": self.symbols,
            "warmup_required_bars": self.warmup_required_bars,
            "warmup_ready": self.warmup_ready,
            "lookahead_guard": self.lookahead_guard,
            "closes": self.closes,
            "timeframe_history": {
                symbol: {tf: len(rows) for tf, rows in tf_map.items()}
                for symbol, tf_map in self.timeframe_history.items()
            },
        }


class MarketSnapshotBuilder:
    def __init__(self, symbols: list[str], warmup_required_bars: int = 8):
        self.symbols = [str(s).upper().replace("/", "").replace("-", "") for s in symbols]
        self.warmup_required_bars = max(1, int(warmup_required_bars))
        self._close_history: dict[str, list[float]] = {symbol: [] for symbol in self.symbols}
        self._timeframe_history: dict[str, dict[str, list[CandleBar]]] = {symbol: {} for symbol in self.symbols}
        self._last_timestamp: datetime | None = None

    def build(self, cycle_index: int, candles: list[CandleBar]) -> MarketSnapshot:
        if not candles:
            raise ValueError("cannot_build_snapshot_without_candles")

        timestamp = candles[0].timestamp
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("historical_feed_timestamp_regressed")
        self._last_timestamp = timestamp

        cycle_tf = candles[0].timeframe
        cycle_bars = {bar.symbol: bar for bar in candles if bar.timeframe == cycle_tf}

        for bar in candles:
            self._timeframe_history.setdefault(bar.symbol, {}).setdefault(bar.timeframe, []).append(bar)

        closes = {symbol: bar.close for symbol, bar in cycle_bars.items()}
        highs = {symbol: bar.high for symbol, bar in cycle_bars.items()}
        lows = {symbol: bar.low for symbol, bar in cycle_bars.items()}

        for symbol in self.symbols:
            if symbol in closes:
                self._close_history.setdefault(symbol, []).append(float(closes[symbol]))

        warmup_ready = {
            symbol: len(self._close_history.get(symbol, [])) >= self.warmup_required_bars
            for symbol in self.symbols
        }

        return MarketSnapshot(
            timestamp=timestamp,
            cycle_index=cycle_index,
            symbols=self.symbols,
            bars=cycle_bars,
            closes=closes,
            highs=highs,
            lows=lows,
            close_history={symbol: list(values) for symbol, values in self._close_history.items()},
            warmup_required_bars=self.warmup_required_bars,
            warmup_ready=warmup_ready,
            lookahead_guard={
                "mode": "point_in_time_snapshot",
                "uses_current_and_past_candles_only": True,
                "future_candle_access": False,
                "cycle_index": cycle_index,
                "current_timestamp": timestamp.isoformat(),
                "phase16f_hf1_timeframe_history": True,
            },
            timeframe_history={
                symbol: {tf: list(rows) for tf, rows in tf_map.items()}
                for symbol, tf_map in self._timeframe_history.items()
            },
        )
