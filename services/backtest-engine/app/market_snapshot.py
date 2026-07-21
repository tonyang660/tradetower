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

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cycle_index": self.cycle_index,
            "symbols": self.symbols,
            "warmup_required_bars": self.warmup_required_bars,
            "warmup_ready": self.warmup_ready,
            "lookahead_guard": self.lookahead_guard,
            "closes": self.closes,
        }


class MarketSnapshotBuilder:
    """Build point-in-time snapshots from the historical event stream.

    The builder appends only candles that have already arrived. Strategies see
    current + past bars only, never future bars.
    """

    def __init__(self, symbols: list[str], warmup_required_bars: int = 8):
        self.symbols = [str(s).upper().replace("/", "").replace("-", "") for s in symbols]
        self.warmup_required_bars = max(1, int(warmup_required_bars))
        self._close_history: dict[str, list[float]] = {symbol: [] for symbol in self.symbols}
        self._last_timestamp: datetime | None = None

    def build(self, cycle_index: int, candles: list[CandleBar]) -> MarketSnapshot:
        if not candles:
            raise ValueError("cannot_build_snapshot_without_candles")

        timestamp = candles[0].timestamp
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError("historical_feed_timestamp_regressed")
        self._last_timestamp = timestamp

        bars = {bar.symbol: bar for bar in candles}
        closes = {symbol: bar.close for symbol, bar in bars.items()}
        highs = {symbol: bar.high for symbol, bar in bars.items()}
        lows = {symbol: bar.low for symbol, bar in bars.items()}

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
            bars=bars,
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
            },
        )
