from db import get_conn


def get_equity_history(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    recorded_at,
                    cash_balance,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    fees_paid_total
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in reversed(rows):
        items.append({
            "recorded_at": row[0].isoformat().replace("+00:00", "Z"),
            "cash_balance": float(row[1]),
            "equity": float(row[2]),
            "realized_pnl": float(row[3]),
            "unrealized_pnl": float(row[4]),
            "fees_paid_total": float(row[5]),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
