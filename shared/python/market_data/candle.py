from dataclasses import dataclass


@dataclass
class Candle:
    timestamp: str  # ISO 8601 UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
