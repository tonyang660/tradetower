
from __future__ import annotations
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "trading_platform"),
    "user": os.getenv("POSTGRES_USER", "trading"),
    "password": os.getenv("POSTGRES_PASSWORD", "change_me"),
}
PHASE8_ACCOUNT_MANAGER_VERSION = "phase8a_account_management_foundation"

def get_conn():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)

def _num(v, default=0.0):
    try:
        return default if v is None else float(v)
    except Exception:
        return default

def _bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).lower() in {"1","true","yes","on","enabled"}

def _validate(payload, creating=False):
    account_type = str(payload.get("account_type", "paper")).lower()
    mode = str(payload.get("execution_mode") or ("paper" if account_type == "paper" else "shadow")).lower()
    if account_type not in {"paper", "live"}:
        return None, {"error": "invalid_account_type"}
    if mode not in {"paper", "shadow", "live"}:
        return None, {"error": "invalid_execution_mode"}
    if account_type == "paper" and mode != "paper":
        return None, {"error": "invalid_mode_for_paper_account"}
    if account_type == "live" and mode not in {"shadow", "live"}:
        return None, {"error": "invalid_mode_for_live_account"}
    name = str(payload.get("account_name") or "").strip()
    if creating and not name:
        return None, {"error": "missing_account_name"}
    starting = _num(payload.get("starting_equity", payload.get("starting_balance", 0)))
    if creating and starting <= 0:
        return None, {"error": "invalid_starting_equity"}
    return {
        "account_name": name,
        "account_type": account_type,
        "execution_mode": mode,
        "enabled": _bool(payload.get("enabled"), True),
        "exchange": payload.get("exchange") or ("paper" if account_type == "paper" else None),
        "base_currency": payload.get("base_currency") or "USDT",
        "starting_equity": starting,
        "metadata_json": payload.get("metadata_json") if isinstance(payload.get("metadata_json"), dict) else {},
    }, None

def _row_to_account(row):
    realized = _num(row.get("realized_pnl"))
    fees = abs(_num(row.get("fees_paid_total")))
    unrealized = _num(row.get("unrealized_pnl"))
    equity = _num(row.get("balance_equity"), _num(row.get("current_equity")))
    return {
        "account_id": int(row["account_id"]),
        "account_name": row["account_name"],
        "account_type": row["account_type"],
        "execution_mode": row["execution_mode"],
        "enabled": bool(row["enabled"]),
        "is_active": bool(row.get("is_active", row["enabled"])),
        "exchange": row.get("exchange"),
        "base_currency": row.get("base_currency") or "USDT",
        "starting_equity": _num(row.get("starting_equity"), _num(row.get("starting_balance"))),
        "current_equity": equity,
        "cash_balance": _num(row.get("cash_balance")),
        "equity": equity,
        "gross_realized_pnl": realized,
        "fees_paid_total": fees,
        "net_realized_pnl": realized - fees,
        "unrealized_pnl": unrealized,
        "total_account_pnl": realized - fees + unrealized,
        "open_positions_count": int(row.get("open_positions_count") or 0),
        "metadata_json": row.get("metadata_json") or {},
        "created_at": row["created_at"].isoformat().replace("+00:00", "Z") if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat().replace("+00:00", "Z") if row.get("updated_at") else None,
    }

def list_accounts():
    q = '''
    SELECT a.account_id,a.account_name,a.account_type,
           COALESCE(a.execution_mode, CASE WHEN a.account_type='paper' THEN 'paper' ELSE 'shadow' END) AS execution_mode,
           COALESCE(a.enabled,a.is_active,TRUE) AS enabled,
           a.is_active,a.exchange,a.base_currency,
           COALESCE(a.starting_equity,a.starting_balance,0) AS starting_equity,
           COALESCE(a.current_equity,ab.equity,a.starting_equity,a.starting_balance,0) AS current_equity,
           COALESCE(ab.cash_balance,0) AS cash_balance,
           COALESCE(ab.equity,a.current_equity,a.starting_equity,a.starting_balance,0) AS balance_equity,
           COALESCE(ab.realized_pnl,0) AS realized_pnl,
           COALESCE(ab.unrealized_pnl,0) AS unrealized_pnl,
           COALESCE(ab.fees_paid_total,0) AS fees_paid_total,
           COALESCE(op.open_positions_count,0) AS open_positions_count,
           COALESCE(a.metadata_json,'{}'::jsonb) AS metadata_json,
           a.created_at, COALESCE(a.updated_at,a.created_at) AS updated_at
    FROM accounts a
    LEFT JOIN account_balances ab ON ab.account_id=a.account_id
    LEFT JOIN (SELECT account_id,COUNT(*) AS open_positions_count FROM positions WHERE status='open' GROUP BY account_id) op ON op.account_id=a.account_id
    ORDER BY a.account_id ASC
    '''
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q)
            rows = cur.fetchall()
    accounts = [_row_to_account(dict(r)) for r in rows]
    selected = next((a for a in accounts if a["enabled"]), accounts[0] if accounts else None)
    return {"ok": True, "account_manager_version": PHASE8_ACCOUNT_MANAGER_VERSION, "count": len(accounts), "accounts": accounts, "default_selected_account_id": selected["account_id"] if selected else None}

def create_account(payload):
    n, err = _validate(payload, creating=True)
    if err:
        return {"ok": False, **err}, 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
            INSERT INTO accounts (account_name,account_type,starting_balance,is_active,execution_mode,enabled,exchange,base_currency,starting_equity,current_equity,metadata_json,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
            RETURNING account_id
            ''', (n["account_name"], n["account_type"], n["starting_equity"], n["enabled"], n["execution_mode"], n["enabled"], n["exchange"], n["base_currency"], n["starting_equity"], n["starting_equity"], Jsonb(n["metadata_json"])))
            account_id = int(cur.fetchone()["account_id"])
            cur.execute('''INSERT INTO account_balances (account_id,cash_balance,equity,realized_pnl,unrealized_pnl,fees_paid_total,updated_at)
                           VALUES (%s,%s,%s,0,0,0,NOW()) ON CONFLICT (account_id) DO NOTHING''', (account_id, n["starting_equity"], n["starting_equity"]))
            cur.execute('''INSERT INTO guardian_state (account_id,trading_enabled,manual_halt,daily_kill_switch,weekly_kill_switch,max_concurrent_positions,daily_loss_limit_pct,weekly_loss_limit_pct,daily_basis_equity,weekly_basis_equity,daily_basis_date,weekly_basis_start,updated_at)
                           VALUES (%s,TRUE,FALSE,FALSE,FALSE,5,3.0,6.0,%s,%s,CURRENT_DATE,CURRENT_DATE,NOW()) ON CONFLICT (account_id) DO NOTHING''', (account_id, n["starting_equity"], n["starting_equity"]))
        conn.commit()
    return {"ok": True, "account_id": account_id, "accounts": list_accounts()["accounts"]}, 201

def update_account(payload):
    try:
        account_id = int(payload.get("account_id"))
    except Exception:
        return {"ok": False, "error": "invalid_account_id"}, 400
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM accounts WHERE account_id=%s", (account_id,))
            current = cur.fetchone()
            if not current:
                return {"ok": False, "error": "account_not_found"}, 404
            merged = dict(current)
            for key in ("account_name","account_type","execution_mode","enabled","exchange","base_currency","metadata_json","starting_equity"):
                if key in payload:
                    merged[key] = payload[key]
            n, err = _validate(merged, creating=False)
            if err:
                return {"ok": False, **err}, 400
            cur.execute('''
            UPDATE accounts
            SET account_name=COALESCE(%s,account_name), account_type=%s, execution_mode=%s,
                enabled=%s, is_active=%s, exchange=%s, base_currency=%s,
                starting_equity=COALESCE(%s,starting_equity),
                metadata_json=COALESCE(%s,metadata_json), updated_at=NOW()
            WHERE account_id=%s
            ''', (n["account_name"] or None, n["account_type"], n["execution_mode"], n["enabled"], n["enabled"], n["exchange"], n["base_currency"], n["starting_equity"] if "starting_equity" in payload else None, Jsonb(n["metadata_json"]) if "metadata_json" in payload else None, account_id))
        conn.commit()
    return {"ok": True, "account_id": account_id, "accounts": list_accounts()["accounts"]}, 200
