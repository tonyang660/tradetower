import json

from db import get_conn


def record_position_event(
    position_id: int,
    account_id: int,
    event_type: str,
    order_id: int | None = None,
    execution_id: int | None = None,
    price: float | None = None,
    size_before: float | None = None,
    size_delta: float | None = None,
    size_after: float | None = None,
    details: dict | None = None,
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            event_id = record_position_event_tx(
                cur=cur,
                position_id=position_id,
                account_id=account_id,
                event_type=event_type,
                order_id=order_id,
                execution_id=execution_id,
                price=price,
                size_before=size_before,
                size_delta=size_delta,
                size_after=size_after,
                details=details,
            )
        conn.commit()

    return event_id


def record_position_event_tx(
    cur,
    position_id: int,
    account_id: int,
    event_type: str,
    order_id: int | None = None,
    execution_id: int | None = None,
    price: float | None = None,
    size_before: float | None = None,
    size_delta: float | None = None,
    size_after: float | None = None,
    details: dict | None = None,
):
    cur.execute(
        """
        INSERT INTO position_events (
            position_id,
            account_id,
            order_id,
            execution_id,
            event_type,
            event_timestamp,
            price,
            size_before,
            size_delta,
            size_after,
            details_json,
            created_at
        )
        VALUES (
            %s, %s, %s, %s, %s, NOW(),
            %s, %s, %s, %s, %s::jsonb, NOW()
        )
        RETURNING position_event_id
        """,
        (
            position_id,
            account_id,
            order_id,
            execution_id,
            event_type,
            price,
            size_before,
            size_delta,
            size_after,
            json.dumps(details or {}),
        ),
    )

    return int(cur.fetchone()[0])


def fetch_position_events(
    account_id: int,
    position_id: int | None = None,
):
    query = """
    SELECT
        position_event_id,
        position_id,
        account_id,
        order_id,
        execution_id,
        event_type,
        event_timestamp,
        price,
        size_before,
        size_delta,
        size_after,
        details_json,
        created_at
    FROM position_events
    WHERE account_id = %s
    """
    params = [account_id]

    if position_id is not None:
        query += " AND position_id = %s"
        params.append(position_id)

    query += """
    ORDER BY event_timestamp ASC, position_event_id ASC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

    items = []
    for row in rows:
        items.append({
            "position_event_id": int(row[0]),
            "position_id": int(row[1]),
            "account_id": int(row[2]),
            "order_id": int(row[3]) if row[3] is not None else None,
            "execution_id": int(row[4]) if row[4] is not None else None,
            "event_type": row[5],
            "event_timestamp": (
                row[6].isoformat().replace("+00:00", "Z")
                if row[6]
                else None
            ),
            "price": float(row[7]) if row[7] is not None else None,
            "size_before": float(row[8]) if row[8] is not None else None,
            "size_delta": float(row[9]) if row[9] is not None else None,
            "size_after": float(row[10]) if row[10] is not None else None,
            "details": row[11] or {},
            "created_at": (
                row[12].isoformat().replace("+00:00", "Z")
                if row[12]
                else None
            ),
        })

    return items
