
from __future__ import annotations

DEFAULT_DATASET_SOURCE = "binance"
DEFAULT_MARKET_TYPE = "um_futures"
DEFAULT_QUOTE_ASSET = "USDT"
DEFAULT_STORAGE_ROOT = "/data/historical/binance"

# Phase 16A target universe.
# This is intentionally centralized so Phase 16B downloader and Phase 16C Parquet
# store use the same default universe.
DEFAULT_SYMBOLS = [
    "ADAUSDT",
    "ARBUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "ETHUSDT",
    "HBARUSDT",
    "HYPEUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "1000PEPEUSDT",  # Adjusted from PEPEUSDT for Binance USD-M Futures
    "SEIUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "TAOUSDT",
    "XLMUSDT",
    "XMRUSDT",
    "XRPUSDT",
    "ZECUSDT",
]

# Production strategy parity target.
# 1m can be used later to resample / verify intrabar assumptions.
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def normalize_timeframe(timeframe: str) -> str:
    return str(timeframe).strip()


def normalize_symbols(symbols: list[str] | str | None) -> list[str]:
    if not symbols:
        return list(DEFAULT_SYMBOLS)
    if isinstance(symbols, str):
        symbols = [symbols]
    return [normalize_symbol(symbol) for symbol in symbols]


def normalize_timeframes(timeframes: list[str] | str | None) -> list[str]:
    if not timeframes:
        return list(DEFAULT_TIMEFRAMES)
    if isinstance(timeframes, str):
        timeframes = [timeframes]
    return [normalize_timeframe(tf) for tf in timeframes]
