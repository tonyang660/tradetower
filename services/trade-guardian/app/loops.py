import json
import time

from config import MTM_ACCOUNT_ID, MTM_AUTO_REFRESH_ENABLED, MTM_REFRESH_INTERVAL_SECONDS
from market_data import refresh_mark_to_market
from time_utils import iso_now


def mark_to_market_loop():
    while True:
        if MTM_AUTO_REFRESH_ENABLED:
            try:
                result = refresh_mark_to_market(MTM_ACCOUNT_ID)
                print(json.dumps({
                    "event": "MARK_TO_MARKET_REFRESHED",
                    "account_id": MTM_ACCOUNT_ID,
                    "positions_checked": result.get("positions_checked", 0),
                    "positions_priced": result.get("positions_priced", 0),
                    "total_unrealized_pnl": result.get("total_unrealized_pnl", 0.0),
                    "timestamp": iso_now(),
                }))
            except Exception as e:
                print(json.dumps({
                    "event": "MARK_TO_MARKET_REFRESH_FAILED",
                    "account_id": MTM_ACCOUNT_ID,
                    "error": str(e),
                    "timestamp": iso_now(),
                }))

        time.sleep(MTM_REFRESH_INTERVAL_SECONDS)
