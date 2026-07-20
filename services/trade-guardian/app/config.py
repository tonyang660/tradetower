import os

SERVICE_NAME = "trade-guardian"
PORT = int(os.getenv("PORT", "8080"))

APP_ENV = os.getenv("APP_ENV", "unknown")

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "trading_platform"),
    "user": os.getenv("POSTGRES_USER", "trading"),
    "password": os.getenv("POSTGRES_PASSWORD", "change_me"),
}

API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
API_GATEWAY_LATEST_PRICE_PATH = os.getenv("API_GATEWAY_LATEST_PRICE_PATH", "/market/ticker")

MTM_AUTO_REFRESH_ENABLED = os.getenv("MTM_AUTO_REFRESH_ENABLED", "false").lower() == "true"
MTM_REFRESH_INTERVAL_SECONDS = int(os.getenv("MTM_REFRESH_INTERVAL_SECONDS", "30"))
DEFAULT_ACCOUNT_ID = int(os.getenv("DEFAULT_ACCOUNT_ID", os.getenv("ACCOUNT_ID", "1")))
