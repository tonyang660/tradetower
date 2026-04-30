import os

SERVICE_NAME = "evaluator"
PORT = int(os.getenv("PORT", "8080"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "trading_platform")
POSTGRES_USER = os.getenv("POSTGRES_USER", "trading")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "trading")

TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
