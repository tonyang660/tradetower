from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from historical_feed import CandleBar


DEFAULT_HISTORY_LIMIT = 250
TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


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
    def __init__(self, symbols: list[str], warmup_required_bars: int = 8, history_limit: int = DEFAULT_HISTORY_LIMIT, cycle_timeframe: str = "5m"):
        self.symbols = [str(s).upper().replace("/", "").replace("-", "") for s in symbols]
        self.warmup_required_bars = max(1, int(warmup_required_bars))
        self.history_limit = max(self.warmup_required_bars, int(history_limit))
        self.cycle_timeframe = str(cycle_timeframe)
        self._close_history: dict[str, deque[float]] = {
            symbol: deque(maxlen=self.history_limit) for symbol in self.symbols
        }
        self._timeframe_history: dict[str, dict[str, deque[CandleBar]]] = {symbol: {} for symbol in self.symbols}
        self._last_close_timestamp: dict[str, datetime | None] = {symbol: None for symbol in self.symbols}
        self._last_timestamp: datetime | None = None

    def seed(self, candles: list[CandleBar]) -> None:
        for bar in sorted(candles, key=lambda item: (item.timestamp, item.symbol, item.timeframe)):
            rows = self._timeframe_history.setdefault(bar.symbol, {}).setdefault(
                bar.timeframe,
                deque(maxlen=self.history_limit),
            )
            if rows and rows[-1].timestamp == bar.timestamp:
                rows[-1] = bar
            elif not rows or bar.timestamp > rows[-1].timestamp:
                rows.append(bar)
            if bar.timeframe == self.cycle_timeframe and self._last_close_timestamp.get(bar.symbol) != bar.timestamp:
                self._close_history.setdefault(bar.symbol, deque(maxlen=self.history_limit)).append(float(bar.close))
                self._last_close_timestamp[bar.symbol] = bar.timestamp

    def build(self, cycle_index: int, candles: list[CandleBar]) -> MarketSnapshot:
        if not candles:
            raise ValueError("cannot_build_snapshot_without_candles")

        cycle_candidates = [bar for bar in candles if bar.timeframe == self.cycle_timeframe]
        if not cycle_candidates:
            raise ValueError("historical_feed_missing_exact_cycle_candle")
        timestamp = max(bar.timestamp for bar in cycle_candidates) + timedelta(
            minutes=TIMEFRAME_MINUTES.get(self.cycle_timeframe, 5)
        )
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("historical_feed_timestamp_regressed")
        self._last_timestamp = timestamp

        cycle_tf = self.cycle_timeframe
        cycle_bars = {bar.symbol: bar for bar in candles if bar.timeframe == cycle_tf}

        for bar in candles:
            rows = self._timeframe_history.setdefault(bar.symbol, {}).setdefault(
                bar.timeframe,
                deque(maxlen=self.history_limit),
            )
            if rows and rows[-1].timestamp == bar.timestamp:
                rows[-1] = bar
            elif not rows or bar.timestamp > rows[-1].timestamp:
                rows.append(bar)
            else:
                raise ValueError("historical_feed_timeframe_timestamp_regressed")

        closes = {symbol: bar.close for symbol, bar in cycle_bars.items()}
        highs = {symbol: bar.high for symbol, bar in cycle_bars.items()}
        lows = {symbol: bar.low for symbol, bar in cycle_bars.items()}

        for symbol in self.symbols:
            if symbol in closes:
                bar_timestamp = cycle_bars[symbol].timestamp
                if self._last_close_timestamp.get(symbol) != bar_timestamp:
                    self._close_history.setdefault(symbol, deque(maxlen=self.history_limit)).append(float(closes[symbol]))
                    self._last_close_timestamp[symbol] = bar_timestamp

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
                "availability_rule": "candle_open_time_plus_timeframe_lte_cycle_close",
                "cycle_candle_rule": "exact_open_time_required",
                "snapshot_timestamp_semantics": "cycle_candle_close_time",
                "cycle_index": cycle_index,
                "current_timestamp": timestamp.isoformat(),
                "phase16f_hf1_timeframe_history": True,
                "deduplicates_timeframe_timestamps": True,
                "history_limit": self.history_limit,
            },
            timeframe_history={
                symbol: {tf: list(rows) for tf, rows in tf_map.items()}
                for symbol, tf_map in self._timeframe_history.items()
            },
        )
