
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from datasets.local_dataset import LOCAL_DATASET_ADAPTER_VERSION, LocalCandle, load_candles, validate_local_dataset_request

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
            for timeframe in self.timeframes:
                self._candles[symbol][timeframe] = load_candles(
                    dataset_id=self.dataset_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=self.start_time,
                    end_time=self.end_time,
                )
        cycle_rows = []
        for symbol in self.symbols:
            rows = self._candles.get(symbol, {}).get(self.cycle_timeframe, [])
            if rows:
                cycle_rows = rows
                break
        self._cycle_timestamps = [row.timestamp for row in cycle_rows]
        if self.max_cycles > 0:
            self._cycle_timestamps = self._cycle_timestamps[:self.max_cycles]

    @staticmethod
    def _latest_at_or_before(rows: list[LocalCandle], ts: datetime) -> LocalCandle | None:
        chosen = None
        for row in rows:
            if row.timestamp <= ts:
                chosen = row
            else:
                break
        return chosen

    def iter_cycles(self) -> Iterator[list[Any]]:
        self._load()
        for ts in self._cycle_timestamps:
            cycle = []
            ordered_timeframes = [self.cycle_timeframe] + [tf for tf in self.timeframes if tf != self.cycle_timeframe]
            for symbol in self.symbols:
                for timeframe in ordered_timeframes:
                    row = self._latest_at_or_before(self._candles[symbol][timeframe], ts)
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
        }
