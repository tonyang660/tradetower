import os
SERVICE_NAME = "backtest-engine"
PORT = int(os.getenv("PORT", "8080"))
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "trading_platform")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DEFAULT_STARTING_CAPITAL = float(os.getenv("BACKTEST_DEFAULT_STARTING_CAPITAL", "2000"))
DEFAULT_FEE_BPS = float(os.getenv("BACKTEST_DEFAULT_FEE_BPS", "6"))
DEFAULT_SLIPPAGE_BPS = float(os.getenv("BACKTEST_DEFAULT_SLIPPAGE_BPS", "3"))
DEFAULT_RISK_PER_TRADE_PCT = float(os.getenv("BACKTEST_DEFAULT_RISK_PER_TRADE_PCT", "1.0"))
DEFAULT_MAX_CYCLES = int(os.getenv("BACKTEST_DEFAULT_MAX_CYCLES", "300"))
