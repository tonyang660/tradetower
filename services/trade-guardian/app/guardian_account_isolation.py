from __future__ import annotations

import json
from typing import Any
from db import get_conn

def _rows(cur, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur.execute(query, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _table_exists(cur, table: str) -> bool:
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (table,))
    return bool(cur.fetchone()[0])

def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=%s)", (table, column))
    return bool(cur.fetchone()[0])

def fetch_guardian_account_isolation_audit(account_id: int | None = None) -> dict[str, Any]:
    findings = []
    with get_conn() as conn, conn.cursor() as cur:
        accounts = _rows(cur, "SELECT account_id, account_name, account_type, execution_mode, COALESCE(enabled,is_active,TRUE) AS enabled FROM accounts ORDER BY account_id")
        guardian_state = _rows(cur, "SELECT account_id, trading_enabled, manual_halt, daily_kill_switch, weekly_kill_switch, daily_loss_limit_pct, weekly_loss_limit_pct, daily_basis_equity, weekly_basis_equity, daily_basis_date, weekly_basis_start FROM guardian_state ORDER BY account_id")
        balances = _rows(cur, "SELECT account_id, cash_balance, equity, unrealized_pnl FROM account_balances ORDER BY account_id")
        duplicate_guardian_state = _rows(cur, "SELECT account_id, COUNT(*)::int AS row_count FROM guardian_state GROUP BY account_id HAVING COUNT(*) > 1 ORDER BY account_id")
        missing_guardian_state = _rows(cur, "SELECT a.account_id FROM accounts a LEFT JOIN guardian_state gs ON gs.account_id=a.account_id WHERE gs.account_id IS NULL ORDER BY a.account_id")
        missing_balances = _rows(cur, "SELECT a.account_id FROM accounts a LEFT JOIN account_balances ab ON ab.account_id=a.account_id WHERE ab.account_id IS NULL ORDER BY a.account_id")

        where = "WHERE account_id = %s" if account_id is not None else ""
        params = (account_id,) if account_id is not None else ()

        trades_by_account = []
        if _table_exists(cur, "trades") and _column_exists(cur, "trades", "account_id"):
            trades_by_account = _rows(cur, f"SELECT account_id, COUNT(*)::int AS trades, COALESCE(SUM(realized_pnl),0)::float AS realized_pnl FROM trades {where} GROUP BY account_id ORDER BY account_id", params)

        execution_reports_by_account = []
        if _table_exists(cur, "execution_reports") and _column_exists(cur, "execution_reports", "account_id"):
            execution_reports_by_account = _rows(cur, f"SELECT account_id, COUNT(*)::int AS reports, COALESCE(SUM(fee_paid),0)::float AS fees_paid FROM execution_reports {where} GROUP BY account_id ORDER BY account_id", params)

        kill_events = []
        if _table_exists(cur, "guardian_events"):
            kill_events = _rows(cur, "SELECT account_id, event_type, reason_code, details_json, created_at FROM guardian_events WHERE event_type ILIKE '%kill%' OR reason_code ILIKE '%KILL%' ORDER BY created_at DESC LIMIT 50")

    if duplicate_guardian_state:
        findings.append({"severity": "critical", "code": "DUPLICATE_GUARDIAN_STATE", "rows": duplicate_guardian_state})
    if missing_guardian_state:
        findings.append({"severity": "critical", "code": "MISSING_GUARDIAN_STATE", "rows": missing_guardian_state})
    if missing_balances:
        findings.append({"severity": "critical", "code": "MISSING_ACCOUNT_BALANCE", "rows": missing_balances})

    return {
        "ok": not any(f["severity"] == "critical" for f in findings),
        "account_id": account_id,
        "findings": findings,
        "accounts": accounts,
        "guardian_state": guardian_state,
        "account_balances": balances,
        "trades_by_account": trades_by_account,
        "execution_reports_by_account": execution_reports_by_account,
        "recent_kill_events": kill_events,
    }

def assert_kill_switch_update_is_account_scoped(sql: str, params: tuple | list | None = None) -> None:
    normalized = " ".join(str(sql).lower().split())
    if "update guardian_state" in normalized and "where account_id" not in normalized:
        raise RuntimeError("unsafe_guardian_state_update_missing_account_id_scope")
    if "update guardian_state" in normalized and not params:
        raise RuntimeError("unsafe_guardian_state_update_missing_params")

def set_account_kill_switch(*, account_id: int, daily: bool | None = None, weekly: bool | None = None, reason_code: str = "ACCOUNT_SCOPED_KILL_SWITCH_UPDATE", details: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = {}
    if daily is not None:
        fields["daily_kill_switch"] = bool(daily)
    if weekly is not None:
        fields["weekly_kill_switch"] = bool(weekly)
    if not fields:
        return {"ok": False, "error": "no_fields"}

    assignments = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [int(account_id)]
    sql = f"UPDATE guardian_state SET {assignments}, updated_at = NOW() WHERE account_id = %s"
    assert_kill_switch_update_is_account_scoped(sql, values)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, values)
        if cur.rowcount != 1:
            raise RuntimeError(f"guardian_state_update_expected_one_row_updated_{cur.rowcount}")
        cur.execute(
            "INSERT INTO guardian_events (account_id,event_type,reason_code,details_json,created_at) VALUES (%s,%s,%s,%s::jsonb,NOW())",
            (int(account_id), "account_scoped_kill_switch_update", reason_code, json.dumps(details or {"fields": fields})),
        )
        conn.commit()
    return {"ok": True, "account_id": int(account_id), "updated": fields}
