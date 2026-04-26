from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta, date
from threading import Thread
import json
import os
import time

import requests
import psycopg


SERVICE_NAME = "trade-guardian"
PORT = int(os.getenv("PORT", "8080"))

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "trading_platform"),
    "user": os.getenv("POSTGRES_USER", "trading"),
    "password": os.getenv("POSTGRES_PASSWORD", "change_me"),
}

API_GATEWAY_BASE_URL = os.getenv("API_GATEWAY_BASE_URL", "http://api-gateway:8080")
API_GATEWAY_LATEST_PRICE_PATH = os.getenv("API_GATEWAY_LATEST_PRICE_PATH", "/providers/bitget/ticker")

MTM_AUTO_REFRESH_ENABLED = os.getenv("MTM_AUTO_REFRESH_ENABLED", "false").lower() == "true"
MTM_REFRESH_INTERVAL_SECONDS = int(os.getenv("MTM_REFRESH_INTERVAL_SECONDS", "30"))
MTM_ACCOUNT_ID = int(os.getenv("MTM_ACCOUNT_ID", "1"))

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_conn():
    return psycopg.connect(**DB_CONFIG)

def utc_now():
    return datetime.now(timezone.utc)


def start_of_today_utc() -> datetime:
    now = utc_now()
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_week_utc() -> datetime:
    now = utc_now()
    monday = now.date() - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def next_monday_utc() -> datetime:
    sow = start_of_week_utc()
    return sow + timedelta(days=7)


def sunday_end_utc() -> datetime:
    return next_monday_utc() - timedelta(seconds=1)


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
                    json.dumps(details or {})
                )
            )
        conn.commit()

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
                "daily_basis_equity": status["equity"]
            }
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
                "weekly_basis_equity": status["equity"]
            }
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
                {"expired_at": expires_at}
            )

    # Apply reset/expiry updates first
    if updates:
        update_guardian_state_fields(account_id, updates)
        status = fetch_guardian_status(account_id)

    # --- Daily net realized loss check ---
    daily_realized_pnl = get_realized_pnl_for_period(account_id, start_of_today_utc())
    daily_limit_amount = status["daily_basis_equity"] * (status["daily_loss_limit_pct"] / 100.0)

    if daily_realized_pnl < 0 and abs(daily_realized_pnl) >= daily_limit_amount:
        if not status["daily_kill_switch"]:
            update_guardian_state_fields(account_id, {"daily_kill_switch": True})

            insert_guardian_event(
                account_id,
                "DAILY_KILL_SWITCH_TRIGGERED",
                "DAILY_MAX_LOSS_REACHED",
                {
                    "daily_realized_pnl": daily_realized_pnl,
                    "daily_limit_amount": daily_limit_amount
                }
            )

            status = fetch_guardian_status(account_id)

    # --- Weekly net realized loss check ---
    weekly_realized_pnl = get_realized_pnl_for_period(account_id, start_of_week_utc())
    weekly_limit_amount = status["weekly_basis_equity"] * (status["weekly_loss_limit_pct"] / 100.0)

    if weekly_realized_pnl < 0 and abs(weekly_realized_pnl) >= weekly_limit_amount:
        if not status["weekly_kill_switch"]:
            expiry_candidate = now + timedelta(hours=48)
            sunday_cutoff = sunday_end_utc()
            final_expiry = min(expiry_candidate, sunday_cutoff)

            update_guardian_state_fields(
                account_id,
                {
                    "weekly_kill_switch": True,
                    "weekly_kill_switch_expires_at": final_expiry
                }
            )

            insert_guardian_event(
                account_id,
                "WEEKLY_KILL_SWITCH_TRIGGERED",
                "WEEKLY_MAX_LOSS_REACHED",
                {
                    "weekly_realized_pnl": weekly_realized_pnl,
                    "weekly_limit_amount": weekly_limit_amount,
                    "expires_at": final_expiry.isoformat().replace("+00:00", "Z")
                }
            )

            status = fetch_guardian_status(account_id)

    return status

def fetch_guardian_status(account_id: int):
    query = """
    SELECT
        a.account_id,
        a.account_name,
        a.is_active,
        ab.cash_balance,
        ab.equity,
        ab.realized_pnl,
        ab.unrealized_pnl,
        ab.fees_paid_total,
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
        "is_active": row[2],
        "cash_balance": float(row[3]),
        "equity": float(row[4]),
        "realized_pnl": float(row[5]),
        "unrealized_pnl": float(row[6]),
        "fees_paid_total": float(row[7]),
        "trading_enabled": row[8],
        "manual_halt": row[9],
        "daily_kill_switch": row[10],
        "weekly_kill_switch": row[11],
        "max_concurrent_positions": row[12],
        "daily_loss_limit_pct": float(row[13]),
        "weekly_loss_limit_pct": float(row[14]),
        "daily_basis_equity": float(row[15]),
        "weekly_basis_equity": float(row[16]),
        "daily_basis_date": str(row[17]),
        "weekly_basis_start": str(row[18]),
        "weekly_kill_switch_expires_at": row[19].isoformat().replace("+00:00", "Z") if row[19] else None,
        "open_positions_count": int(row[20]),
    }


def compute_entry_guard_check(
    status: dict,
    symbol: str | None = None,
    ignore_pending_order: bool = False,
):
    reason_codes = []

    if not status["is_active"]:
        reason_codes.append("ACCOUNT_INACTIVE")

    if not status["trading_enabled"]:
        reason_codes.append("TRADING_DISABLED")

    if status["manual_halt"]:
        reason_codes.append("MANUAL_HALT")

    if status["daily_kill_switch"]:
        reason_codes.append("DAILY_KILL_SWITCH")

    if status["weekly_kill_switch"]:
        reason_codes.append("WEEKLY_KILL_SWITCH")

    if status["open_positions_count"] >= status["max_concurrent_positions"]:
        reason_codes.append("MAX_CONCURRENT_POSITIONS_REACHED")

    existing_position = None
    existing_pending_order = None

    if symbol:
        symbol = symbol.upper()

        existing_position = get_open_position(status["account_id"], symbol)
        if existing_position is not None:
            reason_codes.append("SYMBOL_ALREADY_HAS_OPEN_POSITION")

        if not ignore_pending_order:
            existing_pending_order = get_open_entry_order(status["account_id"], symbol)
            if existing_pending_order is not None:
                reason_codes.append("SYMBOL_ALREADY_HAS_PENDING_ORDER")

    return {
        "trade_allowed": len(reason_codes) == 0,
        "reason_codes": reason_codes,
        "existing_position": existing_position,
        "existing_pending_order": existing_pending_order if not ignore_pending_order else None,
    }


def compute_maintenance_guard_check(status: dict, symbol: str | None = None):
    reason_codes = []

    if not status["is_active"]:
        reason_codes.append("ACCOUNT_INACTIVE")

    # Important rule:
    # maintenance actions remain allowed even if trading is disabled,
    # manual halt is active, or kill switches are active.
    # We only require that the account exists and that an open position exists if symbol is provided.

    if symbol:
        existing_position = get_open_position(status["account_id"], symbol.upper())
        if existing_position is None:
            reason_codes.append("NO_OPEN_POSITION_FOR_SYMBOL")

    return {
        "maintenance_allowed": len(reason_codes) == 0,
        "reason_codes": reason_codes
    }


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
                (enabled, account_id)
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
                    json.dumps({"enabled": enabled})
                )
            )

        conn.commit()

def get_open_position(account_id: int, symbol: str):
    query = """
    SELECT
        position_id,
        account_id,
        symbol,
        side,
        size,
        original_size,
        remaining_size,
        entry_price,
        leverage,
        margin_used,
        stop_loss,
        take_profit,
        risk_amount,
        tp1_price,
        tp2_price,
        tp3_price,
        tp1_hit,
        tp2_hit,
        tp3_hit,
        opened_at,
        closed_at,
        status
    FROM positions
    WHERE account_id = %s
      AND symbol = %s
      AND status = 'open'
    ORDER BY opened_at DESC
    LIMIT 1
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, symbol))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "position_id": row[0],
        "account_id": row[1],
        "symbol": row[2],
        "side": row[3],
        "size": float(row[4]),
        "original_size": float(row[5]) if row[5] is not None else float(row[4]),
        "remaining_size": float(row[6]) if row[6] is not None else float(row[4]),
        "entry_price": float(row[7]),
        "leverage": float(row[8]),
        "margin_used": float(row[9]),
        "stop_loss": float(row[10]) if row[10] is not None else None,
        "take_profit": float(row[11]) if row[11] is not None else None,
        "risk_amount": float(row[12]) if row[12] is not None else 0.0,
        "tp1_price": float(row[13]) if row[13] is not None else None,
        "tp2_price": float(row[14]) if row[14] is not None else None,
        "tp3_price": float(row[15]) if row[15] is not None else None,
        "tp1_hit": row[16],
        "tp2_hit": row[17],
        "tp3_hit": row[18],
        "opened_at": row[19],
        "closed_at": row[20],
        "status": row[21],
    }

def get_open_entry_order(account_id: int, symbol: str):
    query = """
    SELECT
        order_id,
        account_id,
        symbol,
        side,
        order_type,
        role,
        requested_price,
        requested_size,
        status,
        created_at,
        updated_at
    FROM orders
    WHERE account_id = %s
      AND symbol = %s
      AND status IN ('planned', 'submitted')
      AND (role = 'entry' OR role IS NULL)
    ORDER BY created_at DESC
    LIMIT 1
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, symbol))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "order_id": row[0],
        "account_id": row[1],
        "symbol": row[2],
        "side": row[3],
        "order_type": row[4],
        "role": row[5],
        "requested_price": float(row[6]) if row[6] is not None else None,
        "requested_size": float(row[7]) if row[7] is not None else None,
        "status": row[8],
        "created_at": row[9].isoformat().replace("+00:00", "Z") if row[9] else None,
        "updated_at": row[10].isoformat().replace("+00:00", "Z") if row[10] else None,
    }

def fetch_open_position_for_api(account_id: int, symbol: str):
    position = get_open_position(account_id, symbol)
    if position is None:
        return None

    return {
        **position,
        "opened_at": position["opened_at"].isoformat().replace("+00:00", "Z")
        if position.get("opened_at") else None,
        "closed_at": position["closed_at"].isoformat().replace("+00:00", "Z")
        if position.get("closed_at") else None,
    }

def fetch_all_open_positions(account_id: int):
    query = """
    SELECT
        p.position_id,
        p.account_id,
        p.symbol,
        p.side,
        p.original_size,
        p.remaining_size,
        p.entry_price,
        p.leverage,
        p.margin_used,
        p.stop_loss,
        p.tp1_price,
        p.tp2_price,
        p.tp3_price,
        p.tp1_hit,
        p.tp2_hit,
        p.tp3_hit,
        p.opened_at,
        p.status,
        COALESCE((
            SELECT SUM(er.fee_paid)
            FROM execution_reports er
            WHERE er.account_id = p.account_id
            AND er.symbol = p.symbol
            AND er.execution_timestamp >= p.opened_at
        ), 0)
    FROM positions p
    WHERE p.account_id = %s
    AND p.status = 'open'
    ORDER BY p.opened_at ASC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            rows = cur.fetchall()

    results = []
    for row in rows:
        results.append({
            "position_id": row[0],
            "account_id": row[1],
            "symbol": row[2],
            "side": row[3],
            "original_size": float(row[4]),
            "remaining_size": float(row[5]),
            "entry_price": float(row[6]),
            "leverage": float(row[7]),
            "margin_used": float(row[8]) if row[8] is not None else 0.0,
            "stop_loss": float(row[9]) if row[9] is not None else None,
            "tp1_price": float(row[10]) if row[10] is not None else None,
            "tp2_price": float(row[11]) if row[11] is not None else None,
            "tp3_price": float(row[12]) if row[12] is not None else None,
            "tp1_hit": row[13],
            "tp2_hit": row[14],
            "tp3_hit": row[15],
            "opened_at": row[16].isoformat().replace("+00:00", "Z") if row[16] else None,
            "status": row[17],
            "fees_paid": float(row[18]) if row[18] is not None else 0.0,
        })

    return results

def fetch_all_open_orders(account_id: int):
    query = """
    SELECT
        order_id,
        account_id,
        symbol,
        side,
        order_type,
        role,
        requested_price,
        requested_size,
        stop_loss,
        tp1,
        tp2,
        tp3,
        status,
        linked_position_id,
        created_at,
        updated_at
    FROM orders
    WHERE account_id = %s
      AND status IN ('planned', 'submitted')
    ORDER BY created_at DESC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            rows = cur.fetchall()

    items = []
    for row in rows:
        raw_side = row[3]
        normalized_side = "long" if raw_side == "buy" else "short"

        normalized_status = row[12]
        if normalized_status == "planned":
            normalized_status = "PENDING_ENTRY"
        elif normalized_status == "submitted":
            normalized_status = "RESTING"
        elif normalized_status == "filled":
            normalized_status = "FILLED"
        elif normalized_status == "cancelled":
            normalized_status = "CANCELLED"
        elif normalized_status == "rejected":
            normalized_status = "REJECTED"

        items.append({
            "order_id": str(row[0]),
            "account_id": int(row[1]),
            "symbol": row[2],
            "side": normalized_side,
            "order_type": row[4].upper(),
            "role": row[5],
            "entry_price": float(row[6]) if row[6] is not None else None,
            "requested_size": float(row[7]) if row[7] is not None else None,
            "stop_loss": float(row[8]) if row[8] is not None else None,
            "tp1": float(row[9]) if row[9] is not None else None,
            "tp2": float(row[10]) if row[10] is not None else None,
            "tp3": float(row[11]) if row[11] is not None else None,
            "status": normalized_status,
            "linked_position_id": int(row[13]) if row[13] is not None else None,
            "submitted_at": row[14].isoformat().replace("+00:00", "Z") if row[14] else None,
            "updated_at": row[15].isoformat().replace("+00:00", "Z") if row[15] else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }

def opposite_order_side(position_side: str) -> str:
    return "sell" if position_side == "long" else "buy"


def create_order_record(
    account_id: int,
    symbol: str,
    side: str,
    order_type: str,
    requested_price: float | None,
    requested_size: float,
    status: str,
    role: str,
    linked_position_id: int | None = None,
    stop_loss: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
    tp3: float | None = None,
):
    query = """
    INSERT INTO orders (
        account_id,
        symbol,
        side,
        order_type,
        requested_price,
        requested_size,
        status,
        role,
        linked_position_id,
        stop_loss,
        tp1,
        tp2,
        tp3,
        created_at,
        updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    RETURNING order_id
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    account_id,
                    symbol,
                    side,
                    order_type,
                    requested_price,
                    requested_size,
                    status,
                    role,
                    linked_position_id,
                    stop_loss,
                    tp1,
                    tp2,
                    tp3,
                ),
            )
            order_id = cur.fetchone()[0]
        conn.commit()

    return int(order_id)


def create_protective_orders_for_position(
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):
    exit_side = opposite_order_side(position_side)

    tp1_size = round(original_size * 0.40, 8)
    tp2_size = round(original_size * 0.40, 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)

    created = {
        "stop_loss_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="market",
            requested_price=stop_loss,
            requested_size=original_size,
            status="submitted",
            role="stop_loss",
            linked_position_id=linked_position_id,
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp1_price,
            requested_size=tp1_size,
            status="submitted",
            role="tp1",
            linked_position_id=linked_position_id,
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp2_price,
            requested_size=tp2_size,
            status="submitted",
            role="tp2",
            linked_position_id=linked_position_id,
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp3_price,
            requested_size=tp3_size,
            status="submitted",
            role="tp3",
            linked_position_id=linked_position_id,
            tp3=tp3_price,
        ),
    }

    return created


def update_order_status(order_id: int, status: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET status = %s,
                    updated_at = NOW()
                WHERE order_id = %s
                """,
                (status, order_id),
            )
        conn.commit()


def cancel_open_protective_orders_for_position(position_id: int, exclude_order_id: int | None = None):
    query = """
    UPDATE orders
    SET status = 'cancelled',
        updated_at = NOW()
    WHERE linked_position_id = %s
      AND status IN ('planned', 'submitted')
    """
    params = [position_id]

    if exclude_order_id is not None:
        query += " AND order_id <> %s"
        params.append(exclude_order_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
        conn.commit()

def insert_execution_report(account_id: int, order_id, symbol: str, fill_price: float, filled_size: float,
                            fee_paid: float, slippage_bps: float, notes: str | None,
                            execution_type: str, position_side: str):
    query = """
    INSERT INTO execution_reports (
        order_id,
        account_id,
        symbol,
        fill_price,
        filled_size,
        fee_paid,
        slippage_bps,
        execution_timestamp,
        notes,
        execution_type,
        position_side
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
    RETURNING execution_id
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    order_id,
                    account_id,
                    symbol,
                    fill_price,
                    filled_size,
                    fee_paid,
                    slippage_bps,
                    notes,
                    execution_type,
                    position_side
                )
            )
            execution_id = cur.fetchone()[0]
        conn.commit()

    return execution_id

def create_open_position(account_id: int, symbol: str, position_side: str, size: float, entry_price: float,
                         leverage: float, stop_loss: float, tp1_price: float, tp2_price: float,
                         tp3_price: float, risk_amount: float):
    margin_used = size * entry_price / leverage if leverage != 0 else size * entry_price

    query = """
    INSERT INTO positions (
        account_id,
        symbol,
        side,
        size,
        original_size,
        remaining_size,
        entry_price,
        leverage,
        margin_used,
        stop_loss,
        take_profit,
        risk_amount,
        tp1_price,
        tp2_price,
        tp3_price,
        tp1_hit,
        tp2_hit,
        tp3_hit,
        opened_at,
        status
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, FALSE, NOW(), 'open')
    RETURNING position_id
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    account_id,
                    symbol,
                    position_side,
                    size,
                    size,
                    size,
                    entry_price,
                    leverage,
                    margin_used,
                    stop_loss,
                    tp3_price,
                    risk_amount,
                    tp1_price,
                    tp2_price,
                    tp3_price
                )
            )
            position_id = cur.fetchone()[0]
        conn.commit()

    return position_id

def calculate_realized_pnl(position_side: str, entry_price: float, exit_price: float, close_size: float) -> float:
    if position_side == "long":
        return (exit_price - entry_price) * close_size
    if position_side == "short":
        return (entry_price - exit_price) * close_size
    raise ValueError("unsupported_position_side")


def apply_entry_balance_update(account_id: int, margin_used: float, fee_paid: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET cash_balance = cash_balance - %s - %s,
                    equity = equity - %s,
                    fees_paid_total = fees_paid_total + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (margin_used, fee_paid, fee_paid, fee_paid, account_id)
            )
        conn.commit()


def apply_exit_balance_update(account_id: int, released_margin: float, realized_pnl: float, fee_paid: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET cash_balance = cash_balance + %s + %s - %s,
                    equity = equity + %s - %s,
                    realized_pnl = realized_pnl + %s,
                    fees_paid_total = fees_paid_total + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (
                    released_margin,
                    realized_pnl,
                    fee_paid,
                    realized_pnl,
                    fee_paid,
                    realized_pnl,
                    fee_paid,
                    account_id,
                )
            )
        conn.commit()

def insert_execution_report_tx(cur, account_id: int, order_id, symbol: str, fill_price: float, filled_size: float,
                               fee_paid: float, slippage_bps: float, notes: str | None,
                               execution_type: str, position_side: str):
    cur.execute(
        """
        INSERT INTO execution_reports (
            order_id,
            account_id,
            symbol,
            fill_price,
            filled_size,
            fee_paid,
            slippage_bps,
            execution_timestamp,
            notes,
            execution_type,
            position_side
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
        RETURNING execution_id
        """,
        (
            order_id,
            account_id,
            symbol,
            fill_price,
            filled_size,
            fee_paid,
            slippage_bps,
            notes,
            execution_type,
            position_side,
        ),
    )
    return int(cur.fetchone()[0])


def create_open_position_tx(cur, account_id: int, symbol: str, position_side: str, size: float, entry_price: float,
                            leverage: float, stop_loss: float, tp1_price: float, tp2_price: float,
                            tp3_price: float, risk_amount: float):
    margin_used = size * entry_price / leverage if leverage != 0 else size * entry_price

    cur.execute(
        """
        INSERT INTO positions (
            account_id,
            symbol,
            side,
            size,
            original_size,
            remaining_size,
            entry_price,
            leverage,
            margin_used,
            stop_loss,
            take_profit,
            risk_amount,
            tp1_price,
            tp2_price,
            tp3_price,
            tp1_hit,
            tp2_hit,
            tp3_hit,
            opened_at,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, FALSE, NOW(), 'open')
        RETURNING position_id, margin_used
        """,
        (
            account_id,
            symbol,
            position_side,
            size,
            size,
            size,
            entry_price,
            leverage,
            margin_used,
            stop_loss,
            tp3_price,
            risk_amount,
            tp1_price,
            tp2_price,
            tp3_price,
        ),
    )
    row = cur.fetchone()
    return int(row[0]), float(row[1])


def create_order_record_tx(
    cur,
    account_id: int,
    symbol: str,
    side: str,
    order_type: str,
    requested_price: float | None,
    requested_size: float,
    status: str,
    role: str,
    linked_position_id: int | None = None,
    stop_loss: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
    tp3: float | None = None,
):
    cur.execute(
        """
        INSERT INTO orders (
            account_id,
            symbol,
            side,
            order_type,
            requested_price,
            requested_size,
            status,
            role,
            linked_position_id,
            stop_loss,
            tp1,
            tp2,
            tp3,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING order_id
        """,
        (
            account_id,
            symbol,
            side,
            order_type,
            requested_price,
            requested_size,
            status,
            role,
            linked_position_id,
            stop_loss,
            tp1,
            tp2,
            tp3,
        ),
    )
    return int(cur.fetchone()[0])


def create_protective_orders_for_position_tx(
    cur,
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):
    exit_side = opposite_order_side(position_side)

    tp1_size = round(original_size * 0.40, 8)
    tp2_size = round(original_size * 0.40, 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)

    return {
        "stop_loss_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="market",
            requested_price=stop_loss,
            requested_size=original_size,
            status="submitted",
            role="stop_loss",
            linked_position_id=linked_position_id,
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp1_price,
            requested_size=tp1_size,
            status="submitted",
            role="tp1",
            linked_position_id=linked_position_id,
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp2_price,
            requested_size=tp2_size,
            status="submitted",
            role="tp2",
            linked_position_id=linked_position_id,
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp3_price,
            requested_size=tp3_size,
            status="submitted",
            role="tp3",
            linked_position_id=linked_position_id,
            tp3=tp3_price,
        ),
    }


def apply_entry_balance_update_tx(cur, account_id: int, margin_used: float, fee_paid: float):
    cur.execute(
        """
        UPDATE account_balances
        SET cash_balance = cash_balance - %s - %s,
            equity = equity - %s,
            fees_paid_total = fees_paid_total + %s,
            updated_at = NOW()
        WHERE account_id = %s
        """,
        (margin_used, fee_paid, fee_paid, fee_paid, account_id),
    )


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

def update_position_after_partial_exit(
    position_id: int,
    remaining_size: float,
    remaining_margin_used: float,
    tp1_hit=None,
    tp2_hit=None,
    tp3_hit=None,
):
    updates = ["remaining_size = %s", "margin_used = %s"]
    values = [remaining_size, remaining_margin_used]

    if tp1_hit is not None:
        updates.append("tp1_hit = %s")
        values.append(tp1_hit)
    if tp2_hit is not None:
        updates.append("tp2_hit = %s")
        values.append(tp2_hit)
    if tp3_hit is not None:
        updates.append("tp3_hit = %s")
        values.append(tp3_hit)

    values.append(position_id)

    query = f"""
    UPDATE positions
    SET {", ".join(updates)}
    WHERE position_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
        conn.commit()


def close_position(position_id: int, tp1_hit=None, tp2_hit=None, tp3_hit=None):
    updates = ["status = 'closed'", "closed_at = NOW()", "margin_used = 0", "remaining_size = 0"]
    values = []

    if tp1_hit is not None:
        updates.append("tp1_hit = %s")
        values.append(tp1_hit)
    if tp2_hit is not None:
        updates.append("tp2_hit = %s")
        values.append(tp2_hit)
    if tp3_hit is not None:
        updates.append("tp3_hit = %s")
        values.append(tp3_hit)

    values.append(position_id)

    query = f"""
    UPDATE positions
    SET {", ".join(updates)}
    WHERE position_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
        conn.commit()

def maybe_finalize_trade(position: dict):
    query = """
    SELECT
        COALESCE(SUM((details_json->>'realized_pnl')::numeric), 0),
        COALESCE(SUM((details_json->>'fee_paid')::numeric), 0),
        COALESCE(SUM(((details_json->>'fill_price')::numeric) * ((details_json->>'close_size')::numeric)), 0),
        COALESCE(SUM((details_json->>'close_size')::numeric), 0)
    FROM guardian_events
    WHERE account_id = %s
      AND event_type IN ('TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'STOP_LOSS_HIT')
      AND details_json->>'position_id' = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (position["account_id"], str(position["position_id"])))
            pnl_sum, fees_sum, weighted_exit_numerator, total_closed_size = cur.fetchone()

            avg_exit_price = None
            if total_closed_size and float(total_closed_size) > 0:
                avg_exit_price = float(weighted_exit_numerator) / float(total_closed_size)

            notional = float(position["entry_price"]) * float(position["original_size"])

            cur.execute(
                """
                INSERT INTO trades (
                    account_id,
                    symbol,
                    side,
                    entry_price,
                    exit_price,
                    size,
                    leverage,
                    notional,
                    realized_pnl,
                    fees_paid,
                    opened_at,
                    closed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING trade_id
                """,
                (
                    position["account_id"],
                    position["symbol"],
                    position["side"],
                    position["entry_price"],
                    avg_exit_price,
                    position["original_size"],
                    position["leverage"],
                    notional,
                    float(pnl_sum or 0),
                    float(fees_sum or 0),
                    position["opened_at"]
                )
            )
            trade_id = cur.fetchone()[0]

        conn.commit()

    return trade_id

def apply_execution_report(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    position_side = payload["position_side"].lower()
    execution_type = payload["execution_type"].upper()
    order_type = payload["order_type"].lower()
    fill_price = float(payload["fill_price"])
    filled_size = float(payload["filled_size"])
    fee_paid = float(payload.get("fee_paid", 0))
    slippage_bps = float(payload.get("slippage_bps", 0))
    notes = payload.get("notes")
    order_id = payload.get("order_id")

    if position_side not in ("long", "short"):
        return {"ok": False, "error": "unsupported_position_side"}

    if execution_type not in ("ENTRY", "TP1", "TP2", "TP3", "STOP_LOSS"):
        return {"ok": False, "error": "unsupported_execution_type"}

    if order_type not in ("market", "limit"):
        return {"ok": False, "error": "unsupported_order_type"}

    execution_id = None
    open_position = get_open_position(account_id, symbol)

    # ENTRY
    if execution_type == "ENTRY":
        if open_position is not None:
            return {
                "ok": False,
                "error": "position_already_open",
            }

        stop_loss = float(payload["stop_loss"])
        tp1_price = float(payload["tp1_price"])
        tp2_price = float(payload["tp2_price"])
        tp3_price = float(payload["tp3_price"])
        risk_amount = float(payload["risk_amount"])
        leverage = float(payload.get("leverage", 1.0))

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    execution_id = insert_execution_report_tx(
                        cur=cur,
                        account_id=account_id,
                        order_id=order_id,
                        symbol=symbol,
                        fill_price=fill_price,
                        filled_size=filled_size,
                        fee_paid=fee_paid,
                        slippage_bps=slippage_bps,
                        notes=notes,
                        execution_type=execution_type,
                        position_side=position_side,
                    )

                    position_id, position_margin_used = create_open_position_tx(
                        cur=cur,
                        account_id=account_id,
                        symbol=symbol,
                        position_side=position_side,
                        size=filled_size,
                        entry_price=fill_price,
                        leverage=leverage,
                        stop_loss=stop_loss,
                        tp1_price=tp1_price,
                        tp2_price=tp2_price,
                        tp3_price=tp3_price,
                        risk_amount=risk_amount,
                    )

                    protective_orders = create_protective_orders_for_position_tx(
                        cur=cur,
                        account_id=account_id,
                        symbol=symbol,
                        position_side=position_side,
                        original_size=filled_size,
                        stop_loss=stop_loss,
                        tp1_price=tp1_price,
                        tp2_price=tp2_price,
                        tp3_price=tp3_price,
                        linked_position_id=position_id,
                    )

                    apply_entry_balance_update_tx(
                        cur=cur,
                        account_id=account_id,
                        margin_used=position_margin_used,
                        fee_paid=fee_paid,
                    )

                    insert_guardian_event_tx(
                        cur=cur,
                        account_id=account_id,
                        event_type="POSITION_OPENED",
                        reason_code="ENTRY_FILLED",
                        details={
                            "symbol": symbol,
                            "position_id": position_id,
                            "execution_id": execution_id,
                            "position_side": position_side,
                            "fill_price": fill_price,
                            "filled_size": filled_size,
                            "fee_paid": fee_paid,
                            "execution_type": execution_type,
                            "order_type": order_type,
                            "risk_amount": risk_amount,
                            "stop_loss": stop_loss,
                            "tp1_price": tp1_price,
                            "tp2_price": tp2_price,
                            "tp3_price": tp3_price,
                            "protective_orders": protective_orders,
                        },
                    )

                conn.commit()

            return {
                "ok": True,
                "action": "position_opened",
                "execution_id": execution_id,
                "position_id": position_id,
                "protective_orders": protective_orders,
            }

        except Exception as e:
            return {
                "ok": False,
                "error": "entry_apply_failed",
                "details": str(e),
            }

    # Maintenance actions below must have an open position
    if open_position is None:
        return {
            "ok": False,
            "error": "no_open_position",
            "execution_id": execution_id
        }

    original_size = open_position["original_size"]
    remaining_size = open_position["remaining_size"]

    if execution_type == "TP1":
        if open_position["tp1_hit"]:
            return {"ok": False, "error": "tp1_already_hit", "execution_id": execution_id}

        close_size = round(original_size * 0.40, 8)
        if close_size > remaining_size:
            close_size = remaining_size

        released_margin = open_position["margin_used"] * (close_size / remaining_size) if remaining_size > 0 else 0.0
        new_remaining_margin = round(open_position["margin_used"] - released_margin, 8)

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side
        )

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)
        new_remaining = round(remaining_size - close_size, 8)

        update_position_after_partial_exit(
            open_position["position_id"],
            new_remaining,
            new_remaining_margin,
            tp1_hit=True
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            update_order_status(int(order_id), "filled")

        insert_guardian_event(
            account_id,
            "TP1_HIT",
            "TAKE_PROFIT_1",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": new_remaining,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl
            }
        )

        return {
            "ok": True,
            "action": "tp1_applied",
            "execution_id": execution_id,
            "realized_pnl": realized_pnl,
            "remaining_size": new_remaining
        }

    if execution_type == "TP2":
        if not open_position["tp1_hit"]:
            return {"ok": False, "error": "tp1_not_hit_yet", "execution_id": execution_id}
        if open_position["tp2_hit"]:
            return {"ok": False, "error": "tp2_already_hit", "execution_id": execution_id}

        close_size = round(original_size * 0.40, 8)
        if close_size > remaining_size:
            close_size = remaining_size

        released_margin = open_position["margin_used"] * (close_size / remaining_size) if remaining_size > 0 else 0.0
        new_remaining_margin = round(open_position["margin_used"] - released_margin, 8)

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side
        )

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)
        new_remaining = round(remaining_size - close_size, 8)

        update_position_after_partial_exit(
            open_position["position_id"],
            new_remaining,
            new_remaining_margin,
            tp2_hit=True
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            update_order_status(int(order_id), "filled")

        insert_guardian_event(
            account_id,
            "TP2_HIT",
            "TAKE_PROFIT_2",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": new_remaining,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl
            }
        )

        return {
            "ok": True,
            "action": "tp2_applied",
            "execution_id": execution_id,
            "realized_pnl": realized_pnl,
            "remaining_size": new_remaining
        }

    if execution_type == "TP3":
        if open_position["tp3_hit"]:
            return {"ok": False, "error": "tp3_already_hit", "execution_id": execution_id}

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side
        )

        close_size = remaining_size
        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)

        released_margin = open_position["margin_used"]

        close_position(
            open_position["position_id"],
            tp3_hit=True
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            update_order_status(int(order_id), "filled")

        cancel_open_protective_orders_for_position(
            open_position["position_id"],
            exclude_order_id=int(order_id) if order_id is not None else None,
        )

        insert_guardian_event(
            account_id,
            "TP3_HIT",
            "TAKE_PROFIT_3",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": 0,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl
            }
        )

        refreshed_position = open_position.copy()
        refreshed_position["remaining_size"] = 0
        trade_id = maybe_finalize_trade(refreshed_position)

        return {
            "ok": True,
            "action": "tp3_applied_position_closed",
            "execution_id": execution_id,
            "trade_id": trade_id,
            "realized_pnl": realized_pnl
        }

    if execution_type == "STOP_LOSS":
        close_size = remaining_size

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side
        )

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)

        released_margin = open_position["margin_used"]

        close_position(open_position["position_id"])
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            update_order_status(int(order_id), "filled")

        cancel_open_protective_orders_for_position(
            open_position["position_id"],
            exclude_order_id=int(order_id) if order_id is not None else None,
        )        

        insert_guardian_event(
            account_id,
            "STOP_LOSS_HIT",
            "STOP_LOSS_EXECUTED",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": 0,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl
            }
        )

        refreshed_position = open_position.copy()
        refreshed_position["remaining_size"] = 0
        trade_id = maybe_finalize_trade(refreshed_position)

        return {
            "ok": True,
            "action": "stop_loss_applied_position_closed",
            "execution_id": execution_id,
            "trade_id": trade_id,
            "realized_pnl": realized_pnl
        }

    return {"ok": False, "error": "unhandled_execution_case"}


# Update ticker prices for active symbols and account equity state
def fetch_latest_price(symbol: str):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}{API_GATEWAY_LATEST_PRICE_PATH}",
            params={"symbol": symbol},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"latest_price_request_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "latest_price_fetch_failed")

    # Prefer mark price if present, otherwise fall back to last traded price.
    price = payload.get("mark_price")
    if price is None:
        price = payload.get("last_price")

    if price is None:
        return None, "latest_price_missing_in_response"

    return float(price), None

def calculate_unrealized_pnl(position_side: str, entry_price: float, current_price: float, remaining_size: float) -> float:
    if position_side == "long":
        return (current_price - entry_price) * remaining_size
    if position_side == "short":
        return (entry_price - current_price) * remaining_size
    raise ValueError("unsupported_position_side")

def update_account_mark_to_market(account_id: int, unrealized_pnl: float, reserved_margin_total: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET unrealized_pnl = %s,
                    equity = cash_balance + %s + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (unrealized_pnl, reserved_margin_total, unrealized_pnl, account_id)
            )
        conn.commit()

def refresh_mark_to_market(account_id: int):
    positions = fetch_all_open_positions(account_id)

    enriched_positions = []
    total_unrealized_pnl = 0.0
    reserved_margin_total = 0.0
    pricing_errors = []

    for pos in positions:
        symbol = pos["symbol"]
        current_price, price_error = fetch_latest_price(symbol)

        if price_error:
            pricing_errors.append({
                "symbol": symbol,
                "error": price_error
            })
            continue

        remaining_size = float(pos["remaining_size"])
        entry_price = float(pos["entry_price"])
        side = pos["side"]

        unrealized_pnl = calculate_unrealized_pnl(
            side,
            entry_price,
            current_price,
            remaining_size
        )

        notional = entry_price * remaining_size
        pnl_pct = (unrealized_pnl / notional * 100.0) if notional > 0 else 0.0

        total_unrealized_pnl += unrealized_pnl
        reserved_margin_total += float(pos.get("margin_used", 0.0) or 0.0)

        enriched_positions.append({
            **pos,
            "current_price": round(current_price, 8),
            "unrealized_pnl": round(unrealized_pnl, 8),
            "unrealized_pnl_pct": round(pnl_pct, 4),
            "notional": round(notional, 8),
        })

    update_account_mark_to_market(account_id, total_unrealized_pnl, reserved_margin_total)

    refreshed_status = fetch_guardian_status(account_id)
    if refreshed_status:
        refreshed_status = evaluate_and_refresh_guardian_state(refreshed_status)

    return {
        "ok": True,
        "account_id": account_id,
        "positions_checked": len(positions),
        "positions_priced": len(enriched_positions),
        "pricing_errors": pricing_errors,
        "total_unrealized_pnl": round(total_unrealized_pnl, 8),
        "positions": enriched_positions,
        "account_status": refreshed_status,
    }

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "env": os.getenv("APP_ENV", "unknown"),
                "timestamp": iso_now()
            })
            return

        if self.path.startswith("/status"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)
                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    **status
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        if self.path.startswith("/position/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])
                symbol = query.get("symbol", [None])[0]

                if not symbol:
                    self._send_json({
                        "ok": False,
                        "error": "missing_parameters",
                        "required": ["symbol"]
                    }, status=400)
                    return

                position = fetch_open_position_for_api(account_id, symbol.upper())

                if not position:
                    self._send_json({
                        "ok": False,
                        "error": "open_position_not_found",
                        "account_id": account_id,
                        "symbol": symbol.upper()
                    }, status=404)
                    return

                self._send_json({
                    "ok": True,
                    "position": position
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return           

        if self.path.startswith("/positions/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                positions = fetch_all_open_positions(account_id)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "positions": positions
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return
            
        if self.path.startswith("/orders/open"):
            try:
                query = parse_qs(urlparse(self.path).query)
                account_id = int(query.get("account_id", ["1"])[0])

                payload = fetch_all_open_orders(account_id)
                self._send_json(payload)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/guard/check-entry":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))
                symbol = payload.get("symbol")
                ignore_pending_order = bool(payload.get("ignore_pending_order", False))

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)

                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id
                    }, status=404)
                    return

                result = compute_entry_guard_check(
                    status,
                    symbol=symbol,
                    ignore_pending_order=ignore_pending_order,
                )

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "symbol": symbol.upper() if symbol else None,
                    "ignore_pending_order": ignore_pending_order,
                    **result
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        if self.path == "/guard/check-maintenance":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))
                symbol = payload.get("symbol")

                status = fetch_guardian_status(account_id)
                if status:
                    status = evaluate_and_refresh_guardian_state(status)

                if not status:
                    self._send_json({
                        "ok": False,
                        "error": "account_not_found",
                        "account_id": account_id
                    }, status=404)
                    return

                result = compute_maintenance_guard_check(status, symbol=symbol)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "symbol": symbol.upper() if symbol else None,
                    **result
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        if self.path == "/guard/manual-halt":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))

                account_id = int(payload["account_id"])
                enabled = bool(payload["enabled"])
                reason_code = payload.get("reason_code", "MANUAL_HALT")

                set_manual_halt(account_id, enabled, reason_code)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
                    "manual_halt": enabled,
                    "reason_code": reason_code
                })
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        if self.path == "/execution/apply":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))

                result = apply_execution_report(payload)

                status_code = 200 if result.get("ok") else 400
                self._send_json(result, status=status_code)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return     
            
        if self.path == "/mark-to-market/refresh":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))

                result = refresh_mark_to_market(account_id)
                self._send_json(result)
                return

            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "internal_error",
                    "details": str(e)
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    loop_thread = Thread(target=mark_to_market_loop, daemon=True)
    loop_thread.start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()