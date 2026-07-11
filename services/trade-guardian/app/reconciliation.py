import json
from datetime import datetime, timezone

from db import get_conn


RECONCILIATION_STATUSES = {
    "unknown",
    "running",
    "healthy",
    "drift",
    "error",
}


def _iso(value):
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def fetch_reconciliation_state(account_id: int):
    query = """
    SELECT
        rs.account_id,
        rs.provider,
        rs.status,
        rs.last_started_at,
        rs.last_completed_at,
        rs.last_success_at,
        rs.account_match,
        rs.positions_match,
        rs.orders_match,
        rs.mismatch_count,
        rs.max_age_seconds,
        rs.details_json,
        rs.updated_at
    FROM reconciliation_state rs
    WHERE rs.account_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "account_id": int(row[0]),
        "provider": row[1],
        "status": row[2],
        "last_started_at": _iso(row[3]),
        "last_completed_at": _iso(row[4]),
        "last_success_at": _iso(row[5]),
        "account_match": row[6],
        "positions_match": row[7],
        "orders_match": row[8],
        "mismatch_count": int(row[9]),
        "max_age_seconds": int(row[10]),
        "details": row[11] or {},
        "updated_at": _iso(row[12]),
    }


def ensure_reconciliation_state(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reconciliation_state (
                    account_id,
                    provider,
                    status,
                    mismatch_count,
                    max_age_seconds,
                    details_json,
                    updated_at
                )
                VALUES (
                    %s,
                    'blofin',
                    'unknown',
                    0,
                    120,
                    '{}'::jsonb,
                    NOW()
                )
                ON CONFLICT (account_id) DO NOTHING
                """,
                (account_id,),
            )
        conn.commit()

    return fetch_reconciliation_state(account_id)


def update_reconciliation_state(
    account_id: int,
    status: str,
    provider: str = "blofin",
    account_match: bool | None = None,
    positions_match: bool | None = None,
    orders_match: bool | None = None,
    mismatch_count: int = 0,
    details: dict | None = None,
):
    status = str(status).lower()

    if status not in RECONCILIATION_STATUSES:
        raise ValueError("invalid_reconciliation_status")

    if mismatch_count < 0:
        raise ValueError("invalid_mismatch_count")

    ensure_reconciliation_state(account_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE reconciliation_state
                SET provider = %s,
                    status = %s,
                    last_started_at = CASE
                        WHEN %s = 'running' THEN NOW()
                        ELSE last_started_at
                    END,
                    last_completed_at = CASE
                        WHEN %s IN ('healthy', 'drift', 'error') THEN NOW()
                        ELSE last_completed_at
                    END,
                    last_success_at = CASE
                        WHEN %s = 'healthy' THEN NOW()
                        ELSE last_success_at
                    END,
                    account_match = %s,
                    positions_match = %s,
                    orders_match = %s,
                    mismatch_count = %s,
                    details_json = %s::jsonb,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (
                    provider,
                    status,
                    status,
                    status,
                    status,
                    account_match,
                    positions_match,
                    orders_match,
                    mismatch_count,
                    json.dumps(details or {}),
                    account_id,
                ),
            )

            cur.execute(
                """
                INSERT INTO guardian_events (
                    account_id,
                    event_type,
                    reason_code,
                    details_json,
                    created_at
                )
                VALUES (
                    %s,
                    'RECONCILIATION_STATE_UPDATED',
                    %s,
                    %s::jsonb,
                    NOW()
                )
                """,
                (
                    account_id,
                    f"RECONCILIATION_{status.upper()}",
                    json.dumps({
                        "provider": provider,
                        "status": status,
                        "account_match": account_match,
                        "positions_match": positions_match,
                        "orders_match": orders_match,
                        "mismatch_count": mismatch_count,
                        "details": details or {},
                    }),
                ),
            )
        conn.commit()

    return fetch_reconciliation_state(account_id)


def evaluate_reconciliation_gate(
    execution_mode: str,
    reconciliation_state: dict | None,
):
    mode = str(execution_mode or "").lower()

    if mode == "paper":
        return {
            "required": False,
            "healthy": True,
            "stale": False,
            "reason_codes": [],
        }

    if mode not in ("shadow", "live"):
        return {
            "required": True,
            "healthy": False,
            "stale": False,
            "reason_codes": ["RECONCILIATION_REQUIRED"],
        }

    if reconciliation_state is None:
        return {
            "required": True,
            "healthy": False,
            "stale": False,
            "reason_codes": ["RECONCILIATION_UNKNOWN"],
        }

    status = reconciliation_state.get("status")
    if status != "healthy":
        reason = {
            "unknown": "RECONCILIATION_UNKNOWN",
            "running": "RECONCILIATION_RUNNING",
            "drift": "RECONCILIATION_DRIFT",
            "error": "RECONCILIATION_ERROR",
        }.get(status, "RECONCILIATION_UNHEALTHY")

        return {
            "required": True,
            "healthy": False,
            "stale": False,
            "reason_codes": [reason],
        }

    last_success_at = reconciliation_state.get("last_success_at")
    if last_success_at is None:
        return {
            "required": True,
            "healthy": False,
            "stale": False,
            "reason_codes": ["RECONCILIATION_UNKNOWN"],
        }

    last_success = datetime.fromisoformat(
        last_success_at.replace("Z", "+00:00")
    )
    now = datetime.now(timezone.utc)
    age_seconds = max((now - last_success).total_seconds(), 0)
    max_age_seconds = int(
        reconciliation_state.get("max_age_seconds", 120)
    )
    stale = age_seconds > max_age_seconds

    return {
        "required": True,
        "healthy": not stale,
        "stale": stale,
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": max_age_seconds,
        "reason_codes": (
            ["RECONCILIATION_STALE"]
            if stale
            else []
        ),
    }
