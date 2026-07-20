import json
import time

import psycopg
from psycopg.rows import dict_row

from config import DB_CONFIG, DEFAULT_ACCOUNT_ID, MTM_AUTO_REFRESH_ENABLED, MTM_REFRESH_INTERVAL_SECONDS
from market_data import refresh_mark_to_market
from time_utils import iso_now


def _fetch_mtm_account_ids():
    query = """
    SELECT DISTINCT a.account_id
    FROM accounts a
    LEFT JOIN positions p
      ON p.account_id = a.account_id
     AND p.status = 'open'
    WHERE COALESCE(a.enabled, a.is_active, TRUE) = TRUE
       OR p.position_id IS NOT NULL
    ORDER BY a.account_id ASC
    """

    try:
        with psycopg.connect(**DB_CONFIG, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        account_ids = [int(row["account_id"]) for row in rows]
        return account_ids or [int(DEFAULT_ACCOUNT_ID)], None
    except Exception as exc:
        return [int(DEFAULT_ACCOUNT_ID)], str(exc)


def mark_to_market_loop():
    while True:
        if MTM_AUTO_REFRESH_ENABLED:
            account_ids, account_error = _fetch_mtm_account_ids()

            for account_id in account_ids:
                try:
                    result = refresh_mark_to_market(account_id)
                    print(json.dumps({
                        "event": "MARK_TO_MARKET_REFRESHED",
                        "account_id": account_id,
                        "positions_checked": result.get("positions_checked", 0),
                        "positions_priced": result.get("positions_priced", 0),
                        "total_unrealized_pnl": result.get("total_unrealized_pnl", 0.0),
                        "account_discovery_error": account_error,
                        "timestamp": iso_now(),
                    }))
                except Exception as e:
                    print(json.dumps({
                        "event": "MARK_TO_MARKET_REFRESH_FAILED",
                        "account_id": account_id,
                        "account_discovery_error": account_error,
                        "error": str(e),
                        "timestamp": iso_now(),
                    }))

        time.sleep(MTM_REFRESH_INTERVAL_SECONDS)
