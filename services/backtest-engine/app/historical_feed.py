from __future__ import annotations

from datasets.local_feed import LocalHistoricalDatasetFeed

import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterator, Protocol


TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass(frozen=True)
class CandleBar:
    timestamp: datetime
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    level: str
    message: str
    symbol: str | None = None
    timeframe: str | None = None
    details: dict | None = None


@dataclass(frozen=True)
class FeedPreflight:
    ok: bool
    data_mode: str
    symbols: list[str]
    timeframes: list[str]
    cycle_timeframe: str
    start_time: datetime
    end_time: datetime | None
    max_cycles: int
    expected_cycles: int
    coverage: dict
    issues: list[DataQualityIssue]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        payload["end_time"] = self.end_time.isoformat() if self.end_time else None
        return payload


class HistoricalFeed(Protocol):
    data_mode: str

    def preflight(self) -> FeedPreflight:
        ...

    def iter_cycles(self) -> Iterator[list[CandleBar]]:
        ...


def parse_time(value: str | datetime | None, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            parsed = fallback
    else:
        parsed = fallback

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


class Phase14SampleHistoricalFeed:
    """Deterministic feed implementation behind the HistoricalFeed contract.

    Phase 14B's main goal is to remove direct sample-stream coupling from the
    runner. This adapter stays deterministic so engine plumbing remains easy to
    verify. Phase 16 should add real Parquet/DataHub range adapters.
    """

    data_mode = "phase14b_sample_historical_feed"

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        cycle_timeframe: str,
        start_time: datetime,
        end_time: datetime | None,
        max_cycles: int,
    ):
        self.symbols = [normalize_symbol(s) for s in symbols]
        self.timeframes = [str(t) for t in timeframes]
        self.cycle_timeframe = str(cycle_timeframe)
        self.start_time = parse_time(start_time, datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.end_time = parse_time(end_time, self.start_time) if end_time else None
        self.max_cycles = max(0, int(max_cycles))

    def preflight(self) -> FeedPreflight:
        issues: list[DataQualityIssue] = []

        if not self.symbols:
            issues.append(DataQualityIssue(
                code="NO_SYMBOLS",
                level="ERROR",
                message="At least one symbol is required.",
            ))

        if self.cycle_timeframe not in TIMEFRAME_MINUTES:
            issues.append(DataQualityIssue(
                code="UNSUPPORTED_CYCLE_TIMEFRAME",
                level="ERROR",
                message=f"Unsupported cycle timeframe: {self.cycle_timeframe}",
                timeframe=self.cycle_timeframe,
                details={"supported_timeframes": sorted(TIMEFRAME_MINUTES.keys())},
            ))

        for timeframe in self.timeframes:
            if timeframe not in TIMEFRAME_MINUTES:
                issues.append(DataQualityIssue(
                    code="UNSUPPORTED_TIMEFRAME",
                    level="ERROR",
                    message=f"Unsupported timeframe: {timeframe}",
                    timeframe=timeframe,
                    details={"supported_timeframes": sorted(TIMEFRAME_MINUTES.keys())},
                ))

        if self.max_cycles <= 0:
            issues.append(DataQualityIssue(
                code="NO_CYCLES",
                level="ERROR",
                message="max_cycles must be greater than zero.",
            ))

        if self.end_time and self.end_time <= self.start_time:
            issues.append(DataQualityIssue(
                code="INVALID_TIME_RANGE",
                level="ERROR",
                message="end_time must be after start_time.",
                details={
                    "start_time": self.start_time.isoformat(),
                    "end_time": self.end_time.isoformat(),
                },
            ))

        coverage = {}
        minutes = TIMEFRAME_MINUTES.get(self.cycle_timeframe, 15)
        last_time = self.start_time + timedelta(minutes=minutes * max(0, self.max_cycles - 1))

        for symbol in self.symbols:
            coverage[symbol] = {}
            for timeframe in self.timeframes:
                coverage[symbol][timeframe] = {
                    "source": self.data_mode,
                    "available": True,
                    "synthetic": True,
                    "first_timestamp": self.start_time.isoformat(),
                    "last_timestamp": last_time.isoformat(),
                    "rows": self.max_cycles if timeframe == self.cycle_timeframe else None,
                    "gap_count": 0,
                    "quality_score": 1.0,
                    "warnings": ["SYNTHETIC_SAMPLE_DATA_NOT_EDGE_VALIDATION"],
                }

        return FeedPreflight(
            ok=not any(issue.level == "ERROR" for issue in issues),
            data_mode=self.data_mode,
            symbols=self.symbols,
            timeframes=self.timeframes,
            cycle_timeframe=self.cycle_timeframe,
            start_time=self.start_time,
            end_time=self.end_time,
            max_cycles=self.max_cycles,
            expected_cycles=self.max_cycles,
            coverage=coverage,
            issues=issues,
        )

    def iter_cycles(self) -> Iterator[list[CandleBar]]:
        minutes = TIMEFRAME_MINUTES.get(self.cycle_timeframe, 15)

        for i in range(self.max_cycles):
            timestamp = self.start_time + timedelta(minutes=minutes * i)
            yield [
                self._sample_candle(symbol=symbol, symbol_index=symbol_index, cycle_index=i, timestamp=timestamp)
                for symbol_index, symbol in enumerate(self.symbols)
            ]

    def _sample_price(self, symbol_index: int, cycle_index: int) -> float:
        return (
            100
            + symbol_index * 35
            + cycle_index * (0.015 + symbol_index * 0.002)
            + math.sin(cycle_index / 9 + symbol_index) * 1.25
            + math.sin(cycle_index / 29 + symbol_index * 3) * 0.75
        )

    def _sample_candle(self, symbol: str, symbol_index: int, cycle_index: int, timestamp: datetime) -> CandleBar:
        close = self._sample_price(symbol_index, cycle_index)
        open_ = close - math.sin(cycle_index / 5 + symbol_index) * 0.35
        high = max(open_, close) + 0.6
        low = min(open_, close) - 0.6
        volume = 1000 + 50 * math.sin(cycle_index / 13) + 15 * symbol_index

        return CandleBar(
            timestamp=timestamp,
            symbol=symbol,
            timeframe=self.cycle_timeframe,
            open=float(open_),
            high=float(high),
            low=float(low),
            close=float(close),
            volume=float(volume),
        )


class DataHubHistoricalFeed:
    """Placeholder contract for real historical data.

    This intentionally fails preflight for now because the current DataHub only
    exposes latest/limited candles. Phase 16 should add range reads from Parquet
    or DataHub so this can become executable.
    """

    data_mode = "data_hub_historical_range"

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        cycle_timeframe: str,
        start_time: datetime,
        end_time: datetime | None,
        max_cycles: int,
    ):
        self.symbols = [normalize_symbol(s) for s in symbols]
        self.timeframes = [str(t) for t in timeframes]
        self.cycle_timeframe = str(cycle_timeframe)
        self.start_time = start_time
        self.end_time = end_time
        self.max_cycles = max_cycles

    def preflight(self) -> FeedPreflight:
        issue = DataQualityIssue(
            code="HISTORICAL_RANGE_ADAPTER_NOT_IMPLEMENTED",
            level="ERROR",
            message=(
                "DataHub historical range reads are not implemented yet. "
                "Use phase14b_sample_historical_feed until Phase 16 dataset adapters are added."
            ),
            details={
                "required_next_step": "Phase 16 Historical Dataset System",
            },
        )
        return FeedPreflight(
            ok=False,
            data_mode=self.data_mode,
            symbols=self.symbols,
            timeframes=self.timeframes,
            cycle_timeframe=self.cycle_timeframe,
            start_time=self.start_time,
            end_time=self.end_time,
            max_cycles=self.max_cycles,
            expected_cycles=0,
            coverage={},
            issues=[issue],
        )

    def iter_cycles(self) -> Iterator[list[CandleBar]]:
        raise RuntimeError("DataHubHistoricalFeed is a contract placeholder until Phase 16.")


def build_historical_feed(config: dict) -> HistoricalFeed:
    data_mode = str(config.get("data_mode") or "phase14b_sample_historical_feed")

    if data_mode in {"phase14a_sample_stream", "phase14b_sample_historical_feed", "sample"}:
        return Phase14SampleHistoricalFeed(
            symbols=config["symbols"],
            timeframes=config["timeframes"],
            cycle_timeframe=config["cycle_timeframe"],
            start_time=config["start_time"],
            end_time=config.get("end_time"),
            max_cycles=config["max_cycles"],
        )

    if data_mode in {"data_hub", "data_hub_historical_range"}:
        return DataHubHistoricalFeed(
            symbols=config["symbols"],
            timeframes=config["timeframes"],
            cycle_timeframe=config["cycle_timeframe"],
            start_time=config["start_time"],
            end_time=config.get("end_time"),
            max_cycles=config["max_cycles"],
        )

    return Phase14SampleHistoricalFeed(
        symbols=config["symbols"],
        timeframes=config["timeframes"],
        cycle_timeframe=config["cycle_timeframe"],
        start_time=config["start_time"],
        end_time=config.get("end_time"),
        max_cycles=config["max_cycles"],
    )


# Phase 16E fallback helper. Route data_mode=local_historical_dataset to this if your feed factory is custom.
def build_local_historical_dataset_feed(config):
    return LocalHistoricalDatasetFeed(config)
