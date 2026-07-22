
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

# Production strategy parity target plus useful resampling/context frames.
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

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

# Binance USD-M Futures public archive availability as provided for Phase 16B.
BINANCE_UM_FUTURES_AVAILABLE_FROM = {
    "BTCUSDT": "2019-09-08",
    "ETHUSDT": "2019-11-27",
    "XRPUSDT": "2020-01-06",
    "LTCUSDT": "2020-01-09",
    "LINKUSDT": "2020-01-17",
    "ADAUSDT": "2020-01-31",
    "BNBUSDT": "2020-02-10",
    "ZECUSDT": "2020-02-18",
    "XLMUSDT": "2020-02-20",
    "XMRUSDT": "2020-05-20",
    "DOGEUSDT": "2020-07-10",
    "DOTUSDT": "2020-08-18",
    "SOLUSDT": "2020-09-13",
    "HBARUSDT": "2021-10-18",
    "ARBUSDT": "2023-03-23",
    "SUIUSDT": "2023-05-03",
    "1000PEPEUSDT": "2023-05-05",
    "SEIUSDT": "2023-08-15",
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
