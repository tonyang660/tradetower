from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
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