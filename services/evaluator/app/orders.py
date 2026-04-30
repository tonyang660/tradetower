from db import get_conn
from trade_guardian_client import fetch_trade_guardian_open_orders


def get_open_orders(account_id: int):
    orders, error = fetch_trade_guardian_open_orders(account_id)
    if error:
        return {
            "ok": False,
            "error": error,
        }, 500

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(orders),
        "items": orders,
    }, 200


def get_executed_orders(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    er.execution_id,
                    er.order_id,
                    er.account_id,
                    er.symbol,
                    er.execution_type,
                    er.position_side,
                    er.fill_price,
                    er.filled_size,
                    er.fee_paid,
                    er.slippage_bps,
                    er.execution_timestamp,
                    er.notes,
                    COALESCE(
                        o.order_type,
                        CASE
                            WHEN er.notes ILIKE '%%limit%%' THEN 'limit'
                            WHEN er.notes ILIKE '%%market%%' THEN 'market'
                            ELSE 'unknown'
                        END
                    ) AS order_type,
                    o.linked_position_id,
                    CASE
                        WHEN ge.details_json ? 'realized_pnl'
                        THEN (ge.details_json->>'realized_pnl')::numeric
                        ELSE NULL
                    END AS realized_pnl
                FROM execution_reports er
                LEFT JOIN orders o
                    ON o.order_id = er.order_id
                LEFT JOIN guardian_events ge
                    ON ge.account_id = er.account_id
                   AND (ge.details_json->>'execution_id') ~ '^[0-9]+$'
                   AND ((ge.details_json->>'execution_id')::int = er.execution_id)
                   AND ge.event_type IN ('TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'STOP_LOSS_HIT')
                WHERE er.account_id = %s
                ORDER BY er.execution_timestamp DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        (
            execution_id,
            order_id,
            account_id_row,
            symbol,
            execution_type,
            position_side,
            fill_price,
            filled_size,
            fee_paid,
            slippage_bps,
            execution_timestamp,
            notes,
            order_type,
            linked_position_id,
            realized_pnl,
        ) = row

        items.append({
            "execution_id": int(execution_id),
            "order_id": int(order_id) if order_id is not None else None,
            "account_id": int(account_id_row),
            "symbol": str(symbol),
            "execution_type": str(execution_type),
            "position_side": str(position_side).lower() if position_side is not None else "unknown",
            "order_type": str(order_type).lower() if order_type is not None else "unknown",
            "fill_price": float(fill_price) if fill_price is not None else 0.0,
            "filled_size": float(filled_size) if filled_size is not None else 0.0,
            "fee_paid": float(fee_paid) if fee_paid is not None else 0.0,
            "slippage_bps": float(slippage_bps) if slippage_bps is not None else 0.0,
            "execution_timestamp": execution_timestamp.isoformat().replace("+00:00", "Z") if execution_timestamp else None,
            "notes": str(notes) if notes is not None else None,
            "linked_position_id": int(linked_position_id) if linked_position_id is not None else None,
            "realized_pnl": float(realized_pnl) if realized_pnl is not None else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
