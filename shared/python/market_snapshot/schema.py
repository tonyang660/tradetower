from dataclasses import dataclass
from typing import Literal, List


Timeframe = Literal["5m", "15m", "1h", "4h"]
TrendDirection = Literal["up", "down", "neutral"]
MarketType = Literal["trend", "range", "transition"]
VolatilityState = Literal["low", "medium", "high"]

RsiState = Literal[
    "oversold",
    "bearish_but_not_oversold",
    "neutral",
    "bullish_but_not_overextended",
    "overbought",
]

StructureState = Literal[
    "clean_trend",
    "weak_trend",
    "range",
    "transition",
    "chop",
]

SwingBias = Literal["bullish", "bearish", "neutral"]
BosDirection = Literal["bullish", "bearish", "none"]
PullbackState = Literal[
    "active_pullback",
    "shallow_pullback",
    "deep_pullback",
    "no_pullback",
    "reversal_risk",
]
WickRejectionBias = Literal["bullish", "bearish", "neutral"]
ExpansionState = Literal["none", "healthy_expansion", "overextended_expansion", "failed_expansion"]
CompressionState = Literal["none", "mild_compression", "strong_compression"]


@dataclass
class SnapshotMeta:
    schema_version: str
    feature_factory_version: str
    generated_at: str
    symbol: str


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

    ema_separation_pct: float
    macd_histogram_slope: float
    rsi_state: RsiState
    atr_percent: float


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

    structure_state: StructureState
    structure_quality_score: float
    swing_bias: SwingBias
    trend_consistency_score: float


@dataclass
class PriceAction:
    recent_bos_direction: BosDirection
    recent_bos_bars_ago: int
    recent_bos_strength: float
    recent_bos_failed: bool

    pullback_state: PullbackState
    pullback_bars_ago: int
    pullback_depth_pct: float
    pullback_quality_score: float

    impulse_strength_score: float
    correction_strength_score: float
    impulse_to_correction_ratio: float

    wick_rejection_bias: WickRejectionBias
    wick_rejection_score: float

    expansion_state: ExpansionState
    compression_state: CompressionState


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
    price_action: PriceAction
    volatility: Volatility


@dataclass
class MarketSnapshot:
    snapshot_meta: SnapshotMeta
    schema_version: str
    symbol: str
    snapshot_timestamp: str
    source: str
    timeframes: dict[str, TimeframeBlock]