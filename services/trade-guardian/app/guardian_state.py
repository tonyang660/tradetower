import json
from datetime import datetime, timedelta

from db import get_conn
from time_utils import iso_now, start_of_week_utc, sunday_end_utc, utc_now


def get_realized_pnl_for_period(account_id: int, start_ts: datetime, end_ts: datetime | None = None) -> float:
    if end_ts is None:
        end_ts = utc_now()

    query = """
    SELECT COALESCE(SUM(realized_pnl), 0)
    FROM trades
    WHERE account_id = %s
      AND closed_at IS NOT NULL
      AND closed_at >= %s
      AND closed_at <= %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, start_ts, end_ts))
            value = cur.fetchone()[0]

    return float(value or 0)


def update_guardian_state_fields(account_id: int, fields: dict):
    if not fields:
        return

    assignments = ", ".join(f"{k} = %s" for k in fields.keys())
    values = list(fields.values())
    values.append(account_id)

    query = f"""
    UPDATE guardian_state
    SET {assignments},
        updated_at = NOW()
    WHERE account_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
        conn.commit()


def insert_guardian_event(account_id: int, event_type: str, reason_code: str, details: dict | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO guardian_events (account_id, event_type, reason_code, details_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, NOW())
                """,
                (
                    account_id,
                    event_type,
                    reason_code,
                    json.dumps(details or {}),
                ),
            )
        conn.commit()


def insert_guardian_event_tx(cur, account_id: int, event_type: str, reason_code: str, details: dict | None = None):
    cur.execute(
        """
        INSERT INTO guardian_events (account_id, event_type, reason_code, details_json, created_at)
        VALUES (%s, %s, %s, %s::jsonb, NOW())
        """,
        (
            account_id,
            event_type,
            reason_code,
            json.dumps(details or {}),
        ),
    )


def fetch_guardian_status(account_id: int):
    query = """
    SELECT
        a.account_id,
        a.account_name,
        a.account_type,
        a.execution_mode,
        a.is_active,
        ab.cash_balance,
        ab.equity,
        COALESCE((
            SELECT SUM(t.realized_pnl)
            FROM trades t
            WHERE t.account_id = a.account_id
        ), 0) AS realized_pnl,
        ab.unrealized_pnl,
        COALESCE((
            SELECT SUM(er.fee_paid)
            FROM execution_reports er
            WHERE er.account_id = a.account_id
        ), 0) AS fees_paid_total,
        gs.trading_enabled,
        gs.manual_halt,
        gs.daily_kill_switch,
        gs.weekly_kill_switch,
        gs.max_concurrent_positions,
        gs.daily_loss_limit_pct,
        gs.weekly_loss_limit_pct,
        gs.daily_basis_equity,
        gs.weekly_basis_equity,
        gs.daily_basis_date,
        gs.weekly_basis_start,
        gs.weekly_kill_switch_expires_at,
        (
            SELECT COUNT(*)
            FROM positions p
            WHERE p.account_id = a.account_id
              AND p.status = 'open'
        ) AS open_positions_count
    FROM accounts a
    JOIN account_balances ab ON ab.account_id = a.account_id
    JOIN guardian_state gs ON gs.account_id = a.account_id
    WHERE a.account_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "account_id": int(row[0]),
        "account_name": row[1],
        "account_type": row[2],
        "execution_mode": row[3],
        "is_active": row[4],
        "cash_balance": float(row[5]),
        "equity": float(row[6]),
        "realized_pnl": float(row[7]),
        "unrealized_pnl": float(row[8]),
        "fees_paid_total": float(row[9]),
        "trading_enabled": row[10],
        "manual_halt": row[11],
        "daily_kill_switch": row[12],
        "weekly_kill_switch": row[13],
        "max_concurrent_positions": row[14],
        "daily_loss_limit_pct": float(row[15]),
        "weekly_loss_limit_pct": float(row[16]),
        "daily_basis_equity": float(row[17]),
        "weekly_basis_equity": float(row[18]),
        "daily_basis_date": str(row[19]),
        "weekly_basis_start": str(row[20]),
        "weekly_kill_switch_expires_at": row[21].isoformat().replace("+00:00", "Z") if row[21] else None,
        "open_positions_count": int(row[22]),
    }


def evaluate_and_refresh_guardian_state(status: dict):
    account_id = status["account_id"]
    now = utc_now()

    updates = {}

    # --- Daily reset ---
    today = now.date()
    if status["daily_basis_date"] != str(today):
        updates["daily_basis_date"] = today
        updates["daily_basis_equity"] = status["equity"]
        updates["daily_kill_switch"] = False

        insert_guardian_event(
            account_id,
            "DAILY_BASIS_RESET",
            "DAILY_RESET",
            {
                "daily_basis_date": str(today),
                "daily_basis_equity": status["equity"],
            },
        )

    # --- Weekly reset (Monday start) ---
    current_week_start = start_of_week_utc().date()
    if status["weekly_basis_start"] != str(current_week_start):
        updates["weekly_basis_start"] = current_week_start
        updates["weekly_basis_equity"] = status["equity"]
        updates["weekly_kill_switch"] = False
        updates["weekly_kill_switch_expires_at"] = None

        insert_guardian_event(
            account_id,
            "WEEKLY_BASIS_RESET",
            "WEEKLY_RESET",
            {
                "weekly_basis_start": str(current_week_start),
                "weekly_basis_equity": status["equity"],
            },
        )

    # --- Weekly kill switch expiry check ---
    expires_at = status["weekly_kill_switch_expires_at"]
    if status["weekly_kill_switch"] and expires_at is not None:
        expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if now >= expiry_dt:
            updates["weekly_kill_switch"] = False
            updates["weekly_kill_switch_expires_at"] = None

            insert_guardian_event(
                account_id,
                "WEEKLY_KILL_SWITCH_CLEARED",
                "WEEKLY_KILL_SWITCH_EXPIRED",
                {"expired_at": expires_at},
            )

    # Apply reset/expiry updates first
    if updates:
        update_guardian_state_fields(account_id, updates)
        status = fetch_guardian_status(account_id)

    # --- Daily net realized loss check ---
    daily_limit_amount = status["daily_basis_equity"] * (status["daily_loss_limit_pct"] / 100.0)
    daily_drawdown = status["daily_basis_equity"] - status["equity"]

    if daily_drawdown >= daily_limit_amount:
        if not status["daily_kill_switch"]:
            update_guardian_state_fields(account_id, {"daily_kill_switch": True})

            insert_guardian_event(
                account_id,
                "DAILY_KILL_SWITCH_TRIGGERED",
                "DAILY_MAX_LOSS_REACHED",
                {
                    "daily_basis_equity": status["daily_basis_equity"],
                    "current_equity": status["equity"],
                    "daily_drawdown": daily_drawdown,
                    "daily_limit_amount": daily_limit_amount,
                },
            )

            status = fetch_guardian_status(account_id)

    # --- Weekly net realized loss check ---
    weekly_limit_amount = status["weekly_basis_equity"] * (status["weekly_loss_limit_pct"] / 100.0)
    weekly_drawdown = status["weekly_basis_equity"] - status["equity"]

    if weekly_drawdown >= weekly_limit_amount:
        if not status["weekly_kill_switch"]:
            expiry_candidate = now + timedelta(hours=48)
            sunday_cutoff = sunday_end_utc()
            final_expiry = min(expiry_candidate, sunday_cutoff)

            update_guardian_state_fields(
                account_id,
                {
                    "weekly_kill_switch": True,
                    "weekly_kill_switch_expires_at": final_expiry,
                },
            )

            insert_guardian_event(
                account_id,
                "WEEKLY_KILL_SWITCH_TRIGGERED",
                "WEEKLY_MAX_LOSS_REACHED",
                {
                    "weekly_basis_equity": status["weekly_basis_equity"],
                    "current_equity": status["equity"],
                    "weekly_drawdown": weekly_drawdown,
                    "weekly_limit_amount": weekly_limit_amount,
                    "expires_at": final_expiry.isoformat().replace("+00:00", "Z"),
                },
            )

            status = fetch_guardian_status(account_id)

    return status


def set_manual_halt(account_id: int, enabled: bool, reason_code: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE guardian_state
                SET manual_halt = %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (enabled, account_id),
            )

            cur.execute(
                """
                INSERT INTO guardian_events (account_id, event_type, reason_code, details_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, NOW())
                """,
                (
                    account_id,
                    "MANUAL_HALT_UPDATED",
                    reason_code,
                    json.dumps({"enabled": enabled}),
                ),
            )

        conn.commit()
