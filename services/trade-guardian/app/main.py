from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta, date
import json
import os

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
        "account_id": row[0],
        "account_name": row[1],
        "is_active": row[2],
        "cash_balance": float(row[3]),
        "equity": float(row[4]),
        "realized_pnl": float(row[5]),
        "unrealized_pnl": float(row[6]),
        "trading_enabled": row[7],
        "manual_halt": row[8],
        "daily_kill_switch": row[9],
        "weekly_kill_switch": row[10],
        "max_concurrent_positions": row[11],
        "daily_loss_limit_pct": float(row[12]),
        "weekly_loss_limit_pct": float(row[13]),
        "daily_basis_equity": float(row[14]),
        "weekly_basis_equity": float(row[15]),
        "daily_basis_date": str(row[16]),
        "weekly_basis_start": str(row[17]),
        "weekly_kill_switch_expires_at": row[18].isoformat().replace("+00:00", "Z") if row[18] else None,
        "open_positions_count": int(row[19]),
    }


def compute_guard_check(status: dict):
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

    return {
        "trade_allowed": len(reason_codes) == 0,
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

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        if self.path == "/guard/check":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8")) if raw else {}

                account_id = int(payload.get("account_id", 1))

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

                result = compute_guard_check(status)

                self._send_json({
                    "ok": True,
                    "account_id": account_id,
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

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()