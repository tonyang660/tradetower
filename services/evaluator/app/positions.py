from db import get_conn


def get_recent_closed_positions(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trade_id,
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
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                ORDER BY closed_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        (
            trade_id,
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
            closed_at,
        ) = row

        pnl_pct = (float(realized_pnl) / float(notional) * 100.0) if notional and float(notional) > 0 else 0.0

        items.append({
            "trade_id": int(trade_id),
            "symbol": symbol,
            "direction": side,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "exit_price": float(exit_price) if exit_price is not None else None,
            "size": float(size) if size is not None else None,
            "leverage": float(leverage) if leverage is not None else None,
            "notional": float(notional) if notional is not None else 0.0,
            "realized_pnl": float(realized_pnl) if realized_pnl is not None else 0.0,
            "fees_paid": float(fees_paid) if fees_paid is not None else 0.0,
            "pnl_pct": round(pnl_pct, 4),
            "win_loss": "WIN" if float(realized_pnl or 0.0) > 0 else ("LOSS" if float(realized_pnl or 0.0) < 0 else "BREAKEVEN"),
            "opened_at": opened_at.isoformat().replace("+00:00", "Z") if opened_at else None,
            "closed_at": closed_at.isoformat().replace("+00:00", "Z") if closed_at else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
