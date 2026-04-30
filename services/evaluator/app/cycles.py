from db import get_conn


def get_latest_cycle(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
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
            row = cur.fetchone()

    if not row:
        return {
            "ok": True,
            "account_id": account_id,
            "cycle": None,
        }

    return {
        "ok": True,
        "account_id": account_id,
        "cycle": {
            "cycle_id": row[0],
            "started_at": row[1].isoformat().replace("+00:00", "Z") if row[1] else None,
            "completed_at": row[2].isoformat().replace("+00:00", "Z") if row[2] else None,
            "summary": row[3],
        },
    }


def get_cycle_history(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cycle_id, started_at, completed_at, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        items.append({
            "cycle_id": row[0],
            "started_at": row[1].isoformat().replace("+00:00", "Z") if row[1] else None,
            "completed_at": row[2].isoformat().replace("+00:00", "Z") if row[2] else None,
            "summary": row[3],
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
