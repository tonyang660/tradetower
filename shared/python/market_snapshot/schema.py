from dataclasses import dataclass
from typing import Literal, List


Timeframe = Literal["5m", "15m", "1h", "4h"]
TrendDirection = Literal["up", "down", "neutral"]
MarketType = Literal["trend", "range", "transition"]
VolatilityState = Literal["low", "medium", "high"]


@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Indicators:
    rsi: float
    atr: float
    ema_fast: float
    ema_slow: float
    macd: float
    macd_signal: float
    macd_histogram: float
    volume_sma: float
    price_vs_ema_fast_pct: float
    price_vs_ema_slow_pct: float


@dataclass
class Structure:
    trend_direction: TrendDirection
    market_type: MarketType
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool
    range_high: float
    range_low: float
    distance_to_range_high_pct: float
    distance_to_range_low_pct: float


@dataclass
class Volatility:
    atr: float
    atr_percent: float
    volatility_state: VolatilityState


@dataclass
class TimeframeBlock:
    timeframe: Timeframe
    window_size: int
    candles: List[Candle]
    indicators: Indicators
    structure: Structure
    volatility: Volatility


@dataclass
class MarketSnapshot:
    schema_version: str
    symbol: str
    snapshot_timestamp: str
    source: str
    timeframes: dict[str, TimeframeBlock]
