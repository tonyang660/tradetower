import os

SERVICE_NAME = "dashboard-api"
PORT = int(os.getenv("PORT", "8080"))

EVALUATOR_BASE_URL = os.getenv("EVALUATOR_BASE_URL", "http://evaluator:8080")
SCHEDULER_BASE_URL = os.getenv("SCHEDULER_BASE_URL", "http://scheduler:8080")
TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")
CANDIDATE_FILTER_BASE_URL = os.getenv("CANDIDATE_FILTER_BASE_URL", "http://candidate-filter:8080")
STRATEGY_ENGINE_BASE_URL = os.getenv("STRATEGY_ENGINE_BASE_URL", "http://strategy-engine:8080")
RISK_ENGINE_BASE_URL = os.getenv("RISK_ENGINE_BASE_URL", "http://risk-engine:8080")
PAPER_EXECUTION_BASE_URL = os.getenv("PAPER_EXECUTION_BASE_URL", "http://paper-execution:8080")
API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
DATA_HUB_BASE_URL = os.getenv("DATA_HUB_BASE_URL", "http://data-hub:8080")

APP_ENV = os.getenv("APP_ENV", "staging")
SYMBOL_UNIVERSE_PATH = os.getenv("SYMBOL_UNIVERSE_PATH", "/config/symbol_universe.json")

STRICT_SCORE_THRESHOLD = float(os.getenv("STRICT_SCORE_THRESHOLD", "68"))
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "15.0"))
MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE = float(os.getenv("MIN_NOTIONAL_PCT_OF_MAX_DEPLOYABLE", "1.0"))

LIMIT_FEE_PCT = float(os.getenv("LIMIT_FEE_PCT", "0.02"))
MARKET_FEE_PCT = float(os.getenv("MARKET_FEE_PCT", "0.06"))
MARKET_SLIPPAGE_PCT = float(os.getenv("MARKET_SLIPPAGE_PCT", "0.06"))

MTM_AUTO_REFRESH_ENABLED = os.getenv("MTM_AUTO_REFRESH_ENABLED", "true").lower() == "true"
MTM_AUTO_REFRESH_INTERVAL_SECONDS = int(os.getenv("MTM_AUTO_REFRESH_INTERVAL_SECONDS", "30"))
