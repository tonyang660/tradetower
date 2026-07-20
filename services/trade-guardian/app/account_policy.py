from __future__ import annotations
import json
from typing import Any
from db import get_conn

PHASE9_GUARDIAN_ACCOUNT_MANAGER_VERSION = "phase9a_guardian_account_manager_policy"
ACCOUNT_FIELDS = {"enabled", "execution_mode"}
GUARDIAN_FIELDS = {
    "trading_enabled", "manual_halt", "daily_kill_switch", "weekly_kill_switch",
    "max_concurrent_positions", "daily_loss_limit_pct", "weekly_loss_limit_pct",
    "max_account_exposure_pct", "read_only_mode", "maintenance_only_mode",
}

def _bool(value: Any) -> bool:
    if isinstance(value, bool): return value
    if value is None: return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

def fetch_guardian_account_policy(account_id: int) -> dict[str, Any] | None:
    query = """
    SELECT a.account_id, a.account_name, a.account_type,
           COALESCE(a.enabled, a.is_active, TRUE) AS enabled,
           COALESCE(a.is_active, a.enabled, TRUE) AS is_active,
           a.execution_mode,
           gs.trading_enabled, gs.manual_halt, gs.daily_kill_switch, gs.weekly_kill_switch,
           gs.max_concurrent_positions, gs.daily_loss_limit_pct, gs.weekly_loss_limit_pct,
           COALESCE(gs.max_account_exposure_pct, 50.0),
           COALESCE(gs.read_only_mode, FALSE),
           COALESCE(gs.maintenance_only_mode, FALSE),
           gs.policy_updated_at, gs.policy_updated_by
    FROM accounts a
    JOIN guardian_state gs ON gs.account_id = a.account_id
    WHERE a.account_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            row = cur.fetchone()
    if not row: return None
    return {
        "account_id": int(row[0]), "account_name": row[1], "account_type": row[2],
        "enabled": bool(row[3]), "is_active": bool(row[4]), "execution_mode": row[5],
        "trading_enabled": bool(row[6]), "manual_halt": bool(row[7]),
        "daily_kill_switch": bool(row[8]), "weekly_kill_switch": bool(row[9]),
        "max_concurrent_positions": int(row[10]),
        "daily_loss_limit_pct": float(row[11]), "weekly_loss_limit_pct": float(row[12]),
        "max_account_exposure_pct": float(row[13]),
        "read_only_mode": bool(row[14]), "maintenance_only_mode": bool(row[15]),
        "policy_updated_at": row[16].isoformat().replace("+00:00","Z") if row[16] else None,
        "policy_updated_by": row[17],
        "rules": {
            "enabled_false": "blocks new cycles and new entries; exits/maintenance remain allowed",
            "read_only_mode": "blocks new orders; status/read operations remain allowed",
            "maintenance_only_mode": "blocks new entries; protective exits and risk-reduction maintenance remain allowed",
        },
    }

def _validate_execution_mode(account_type: str, execution_mode: str | None) -> str | None:
    if execution_mode is None: return None
    execution_mode = str(execution_mode).lower()
    if execution_mode not in {"paper", "shadow", "live"}:
        raise ValueError("execution_mode must be paper, shadow, or live")
    if account_type == "paper" and execution_mode != "paper":
        raise ValueError("paper account execution_mode must be paper")
    if account_type == "live" and execution_mode not in {"shadow", "live"}:
        raise ValueError("live account execution_mode must be shadow or live")
    return execution_mode

def update_guardian_account_policy(account_id: int, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_payload"}, 400
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT account_type FROM accounts WHERE account_id = %s", (account_id,))
                row = cur.fetchone()
                if not row:
                    return {"ok": False, "error": "account_not_found", "account_id": account_id}, 404
                account_type = row[0]
                account_updates, guardian_updates = {}, {}
                for k,v in payload.items():
                    if k in ACCOUNT_FIELDS: account_updates[k]=v
                    elif k in GUARDIAN_FIELDS: guardian_updates[k]=v
                if "execution_mode" in account_updates:
                    account_updates["execution_mode"] = _validate_execution_mode(account_type, account_updates["execution_mode"])
                if "enabled" in account_updates:
                    account_updates["enabled"] = _bool(account_updates["enabled"])
                for k in ("trading_enabled","manual_halt","daily_kill_switch","weekly_kill_switch","read_only_mode","maintenance_only_mode"):
                    if k in guardian_updates: guardian_updates[k] = _bool(guardian_updates[k])
                if "max_concurrent_positions" in guardian_updates:
                    guardian_updates["max_concurrent_positions"] = int(guardian_updates["max_concurrent_positions"])
                    if guardian_updates["max_concurrent_positions"] < 0: raise ValueError("max_concurrent_positions must be >= 0")
                for k in ("daily_loss_limit_pct","weekly_loss_limit_pct","max_account_exposure_pct"):
                    if k in guardian_updates:
                        guardian_updates[k] = float(guardian_updates[k])
                        if guardian_updates[k] < 0: raise ValueError(f"{k} must be >= 0")
                if account_updates:
                    assignments, values = [], []
                    if "enabled" in account_updates:
                        assignments += ["enabled = %s", "is_active = %s"]
                        values += [account_updates["enabled"], account_updates["enabled"]]
                    if "execution_mode" in account_updates:
                        assignments.append("execution_mode = %s"); values.append(account_updates["execution_mode"])
                    assignments.append("updated_at = NOW()")
                    values.append(account_id)
                    cur.execute(f"UPDATE accounts SET {', '.join(assignments)} WHERE account_id = %s", values)
                if guardian_updates:
                    assignments = [f"{k} = %s" for k in guardian_updates.keys()]
                    values = list(guardian_updates.values())
                    assignments += ["policy_updated_at = NOW()", "policy_updated_by = %s"]
                    values += [str(payload.get("policy_updated_by") or "dashboard"), account_id]
                    cur.execute(f"UPDATE guardian_state SET {', '.join(assignments)} WHERE account_id = %s", values)
                cur.execute(
                    """INSERT INTO guardian_events (account_id,event_type,reason_code,details_json,created_at)
                       VALUES (%s,%s,%s,%s::jsonb,NOW())""",
                    (account_id,"account_policy_updated","GUARDIAN_ACCOUNT_POLICY_UPDATED",
                     json.dumps({"account_updates":account_updates,"guardian_updates":guardian_updates}))
                )
            conn.commit()
    except ValueError as exc:
        return {"ok": False, "error": "invalid_policy_update", "details": str(exc)}, 400
    return {"ok": True, "guardian_account_manager_version": PHASE9_GUARDIAN_ACCOUNT_MANAGER_VERSION,
            "account_id": account_id, "policy": fetch_guardian_account_policy(account_id)}, 200
