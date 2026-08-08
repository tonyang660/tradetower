
from __future__ import annotations

DEFAULT_DATASET_SOURCE = "binance"
DEFAULT_MARKET_TYPE = "um_futures"
DEFAULT_QUOTE_ASSET = "USDT"
DEFAULT_STORAGE_ROOT = "/data/historical/binance"

# User-curated Phase 16 Binance USD-M Futures universe.
DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "ADAUSDT",
    "BNBUSDT",
    "ZECUSDT",
    "XLMUSDT",
    "XMRUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "SOLUSDT",
    "HBARUSDT",
    "ARBUSDT",
    "SUIUSDT",
    "1000PEPEUSDT",
    "SEIUSDT",
    "TAOUSDT",
    "HYPEUSDT"
]

# Production-parity backtests consume only these persisted candle intervals.
# Logical 1m execution remains virtual and does not require 1m downloads.
DEFAULT_TIMEFRAMES = ["5m", "15m", "1h", "4h"]

TIMEFRAME_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
}

# First Binance USD-M daily kline archive for every supported interval above.
# These are archive boundaries, which are not always the contract launch dates.
BINANCE_UM_FUTURES_AVAILABLE_FROM = {
    "BTCUSDT": "2019-12-31",
    "ETHUSDT": "2019-12-31",
    "XRPUSDT": "2020-01-06",
    "LTCUSDT": "2020-01-09",
    "LINKUSDT": "2020-01-17",
    "ADAUSDT": "2020-01-31",
    "BNBUSDT": "2020-02-10",
    "ZECUSDT": "2020-02-05",
    "XLMUSDT": "2020-01-20",
    "XMRUSDT": "2020-02-03",
    "DOGEUSDT": "2020-07-10",
    "DOTUSDT": "2020-08-22",
    "SOLUSDT": "2020-09-14",
    "HBARUSDT": "2021-03-17",
    "ARBUSDT": "2023-03-23",
    "SUIUSDT": "2023-05-03",
    "1000PEPEUSDT": "2023-05-05",
    "SEIUSDT": "2023-08-17",
    "TAOUSDT": "2024-04-11",
    "HYPEUSDT": "2025-05-30"
}

BINANCE_DATA_BASE_URL = "https://data.binance.vision"
BINANCE_UM_MONTHLY_KLINES_PATH = "data/futures/um/monthly/klines"
BINANCE_UM_DAILY_KLINES_PATH = "data/futures/um/daily/klines"


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


def available_from(symbol: str) -> str | None:
    return BINANCE_UM_FUTURES_AVAILABLE_FROM.get(normalize_symbol(symbol))
