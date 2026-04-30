from db import get_conn
from positions import get_recent_closed_positions
from time_utils import iso_now
from trade_guardian_client import (
    fetch_trade_guardian_open_positions,
    fetch_trade_guardian_status,
    refresh_trade_guardian_mark_to_market,
)


def build_overview(account_id: int):
    mtm_payload, mtm_error = refresh_trade_guardian_mark_to_market(account_id)

    if mtm_error:
        tg_status, tg_error = fetch_trade_guardian_status(account_id)
        if tg_error:
            return None, tg_error

        open_positions, open_positions_error = fetch_trade_guardian_open_positions(account_id)
        if open_positions_error:
            open_positions = []
    else:
        tg_status = mtm_payload.get("account_status", {})
        open_positions = mtm_payload.get("positions", [])

    recent_positions_payload = get_recent_closed_positions(account_id, 10)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, equity
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at DESC
                LIMIT 8640
                """,
                (account_id,),
            )
            equity_rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*)
                FROM trades
                WHERE account_id = %s
                  AND closed_at::date = NOW()::date
                """,
                (account_id,),
            )
            daily_completed_trades = cur.fetchone()[0]

            cur.execute(
                """
                SELECT
                COALESCE(SUM(realized_pnl), 0),
                COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at::date = NOW()::date
                """,
                (account_id,),
            )
            daily_pnl, daily_wins, daily_losses = cur.fetchone()

            cur.execute(
                """
                SELECT cycle_id, started_at, completed_at, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (account_id,),
            )
            latest_cycle = cur.fetchone()

    open_positions_count = len(open_positions)

    equity_series = [
        {
            "recorded_at": row[0].isoformat().replace("+00:00", "Z"),
            "equity": float(row[1]),
        }
        for row in reversed(equity_rows)
    ]

    latest_cycle_payload = None
    if latest_cycle:
        latest_cycle_payload = {
            "cycle_id": latest_cycle[0],
            "started_at": latest_cycle[1].isoformat().replace("+00:00", "Z") if latest_cycle[1] else None,
            "completed_at": latest_cycle[2].isoformat().replace("+00:00", "Z") if latest_cycle[2] else None,
            "summary": latest_cycle[3],
        }

    total_daily_trades = int(daily_wins) + int(daily_losses)
    daily_win_rate = (float(daily_wins) / total_daily_trades * 100.0) if total_daily_trades > 0 else 0.0

    return {
        "ok": True,
        "account_id": account_id,
        "overview_generated_at": iso_now(),
        "account_status": tg_status,
        "equity_series": equity_series,
        "open_positions": open_positions,
        "recent_positions": recent_positions_payload["items"],
        "micro_metrics": {
            "daily_pnl": float(daily_pnl),
            "daily_completed_trades": int(daily_completed_trades),
            "daily_wins": int(daily_wins),
            "daily_losses": int(daily_losses),
            "daily_win_rate": round(daily_win_rate, 2),
            "open_positions_count": open_positions_count,
        },
        "latest_cycle": latest_cycle_payload,
    }, None
