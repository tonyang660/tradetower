
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from datasets.local_dataset import LOCAL_DATASET_ADAPTER_VERSION, LocalCandle, load_candles, validate_local_dataset_request

TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
PRODUCTION_FEATURE_WARMUP_ROWS = 72

@dataclass(frozen=True)
class LocalFeedPreflight:
    ok: bool
    data_mode: str
    dataset_id: int
    symbols: list[str]
    timeframes: list[str]
    cycle_timeframe: str
    start_time: str | None
    end_time: str | None
    coverage: dict[str, Any]
    issues: list[dict[str, Any]]
    adapter_version: str = LOCAL_DATASET_ADAPTER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__

class LocalHistoricalDatasetFeed:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.dataset_id = int(config.get("dataset_id") or 0)
        if self.dataset_id <= 0:
            raise ValueError("dataset_id is required for local_historical_dataset")
        self.symbols = [str(s).upper() for s in config.get("symbols", [])]
        self.timeframes = [str(tf) for tf in config.get("timeframes", [])]
        self.cycle_timeframe = str(config.get("cycle_timeframe") or (self.timeframes[0] if self.timeframes else "15m"))
        self.start_time = config.get("start_time")
        self.end_time = config.get("end_time")
        self.max_cycles = int(config.get("max_cycles") or 0)
        self._candles: dict[str, dict[str, list[LocalCandle]]] = {}
        self._cycle_timestamps: list[datetime] = []
        self._cursor_indices: dict[str, dict[str, int]] = {}

    def preflight(self) -> LocalFeedPreflight:
        validation = validate_local_dataset_request(
            dataset_id=self.dataset_id,
            symbols=self.symbols,
            timeframes=self.timeframes,
            start_time=self.start_time,
            end_time=self.end_time,
        )
        issues = []
        if validation.get("missing"):
            issues.append({"severity": "error", "issue_code": "MISSING_DATASET_ASSET", "details": validation["missing"]})
        if validation.get("not_ready"):
            issues.append({"severity": "error", "issue_code": "DATASET_ASSET_NOT_READY", "details": validation["not_ready"]})
        return LocalFeedPreflight(
            ok=bool(validation.get("ok")),
            data_mode="local_historical_dataset",
            dataset_id=self.dataset_id,
            symbols=self.symbols,
            timeframes=self.timeframes,
            cycle_timeframe=self.cycle_timeframe,
            start_time=str(self.start_time) if self.start_time else None,
            end_time=str(self.end_time) if self.end_time else None,
            coverage=validation.get("coverage", {}),
            issues=issues,
        )

    def _load(self) -> None:
        if self._candles:
            return
        for symbol in self.symbols:
            self._candles[symbol] = {}
            self._cursor_indices[symbol] = {}
            for timeframe in self.timeframes:
                requested_start = self.start_time
                if requested_start is not None:
                    requested_start = requested_start if isinstance(requested_start, datetime) else datetime.fromisoformat(str(requested_start).replace("Z", "+00:00"))
                    if requested_start.tzinfo is None:
                        requested_start = requested_start.replace(tzinfo=timezone.utc)
                    requested_start = requested_start - timedelta(
                        minutes=TIMEFRAME_MINUTES.get(timeframe, 5) * PRODUCTION_FEATURE_WARMUP_ROWS
                    )
                self._candles[symbol][timeframe] = load_candles(
                    dataset_id=self.dataset_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=requested_start,
                    end_time=self.end_time,
                )
                self._cursor_indices[symbol][timeframe] = -1
        cycle_rows = [
            row
            for symbol in self.symbols
            for row in self._candles.get(symbol, {}).get(self.cycle_timeframe, [])
        ]
        start = self.start_time
        if start is not None and not isinstance(start, datetime):
            start = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        if isinstance(start, datetime) and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._cycle_timestamps = sorted({
            row.timestamp for row in cycle_rows
            if start is None or row.timestamp >= start
        })
        if self.max_cycles > 0:
            self._cycle_timestamps = self._cycle_timestamps[:self.max_cycles]

    def _latest_closed_cursor(self, symbol: str, timeframe: str, ts: datetime) -> LocalCandle | None:
        rows = self._candles[symbol][timeframe]
        index = self._cursor_indices[symbol][timeframe]
        cycle_close = ts + timedelta(minutes=TIMEFRAME_MINUTES.get(self.cycle_timeframe, 5))
        timeframe_delta = timedelta(minutes=TIMEFRAME_MINUTES.get(timeframe, 5))

        # Iteration is normally monotonic. Reset only if this feed instance is
        # explicitly rewound and iterated again.
        if index >= 0 and rows[index].timestamp + timeframe_delta > cycle_close:
            index = -1

        while index + 1 < len(rows) and rows[index + 1].timestamp + timeframe_delta <= cycle_close:
            index += 1

        self._cursor_indices[symbol][timeframe] = index
        selected = rows[index] if index >= 0 else None
        if timeframe == self.cycle_timeframe and (selected is None or selected.timestamp != ts):
            return None
        return selected

    def bootstrap_history(self) -> list[LocalCandle]:
        """Rows fully closed before the first simulated decision candle opens."""
        self._load()
        if not self._cycle_timestamps:
            return []
        first_cycle = self._cycle_timestamps[0]
        history: list[LocalCandle] = []
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                delta = timedelta(minutes=TIMEFRAME_MINUTES.get(timeframe, 5))
                rows = [row for row in self._candles[symbol][timeframe] if row.timestamp + delta <= first_cycle]
                history.extend(rows[-PRODUCTION_FEATURE_WARMUP_ROWS:])
        return sorted(history, key=lambda row: (row.timestamp, row.symbol, row.timeframe))

    def iter_cycles(self) -> Iterator[list[Any]]:
        self._load()
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                self._cursor_indices[symbol][timeframe] = -1

        for ts in self._cycle_timestamps:
            cycle = []
            ordered_timeframes = [self.cycle_timeframe] + [tf for tf in self.timeframes if tf != self.cycle_timeframe]
            for symbol in self.symbols:
                for timeframe in ordered_timeframes:
                    row = self._latest_closed_cursor(symbol, timeframe, ts)
                    if row is not None:
                        cycle.append(row)
            yield cycle

    def to_debug_summary(self) -> dict[str, Any]:
        self._load()
        return {
            "adapter_version": LOCAL_DATASET_ADAPTER_VERSION,
            "dataset_id": self.dataset_id,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "cycle_timeframe": self.cycle_timeframe,
            "cycle_count": len(self._cycle_timestamps),
            "first_cycle": self._cycle_timestamps[0].isoformat() if self._cycle_timestamps else None,
            "last_cycle": self._cycle_timestamps[-1].isoformat() if self._cycle_timestamps else None,
            "candle_availability": "close_time_lte_cycle_close",
            "cycle_rows_require_exact_open_time": True,
            "bootstrap_rows": len(self.bootstrap_history()),
        }
