import json
from uuid import uuid4

from db import get_conn


ACTIVE_ORDER_STATUSES = (
    "created",
    "submitted",
    "acknowledged",
    "open",
    "partially_filled",
    "cancel_pending",
)

WORKING_ORDER_STATUSES = (
    "created",
    "submitted",
    "acknowledged",
    "open",
    "partially_filled",
    "cancel_pending",
)


def opposite_order_side(position_side: str) -> str:
    return "sell" if position_side == "long" else "buy"


def _working_status_sql() -> str:
    return ", ".join(["%s"] * len(WORKING_ORDER_STATUSES))


def _active_status_sql() -> str:
    return ", ".join(["%s"] * len(ACTIVE_ORDER_STATUSES))


def _normalize_working_status(status: str) -> str:
    mapping = {
        "created": "PENDING_ENTRY",
        "submitted": "PENDING_ENTRY",
        "acknowledged": "RESTING",
        "open": "RESTING",
        "partially_filled": "PARTIALLY_FILLED",
        "cancel_pending": "CANCEL_PENDING",
        "filled": "FILLED",
        "cancelled": "CANCELLED",
        "rejected": "REJECTED",
        "expired": "EXPIRED",
    }
    return mapping.get(status, str(status).upper())


def get_open_entry_order(account_id: int, symbol: str):
    query = f"""
    SELECT
        order_id,
        account_id,
        symbol,
        side,
        order_type,
        role,
        requested_price,
        requested_size,
        status,
        created_at,
        updated_at,
        client_order_id,
        filled_size,
        remaining_size,
        average_fill_price,
        submitted_at
    FROM orders
    WHERE account_id = %s
      AND symbol = %s
      AND status IN ({_active_status_sql()})
      AND role = 'entry'
    ORDER BY created_at DESC
    LIMIT 1
    """

    params = (account_id, symbol, *ACTIVE_ORDER_STATUSES)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    if not row:
        return None

    return {
        "order_id": int(row[0]),
        "account_id": int(row[1]),
        "symbol": row[2],
        "side": row[3],
        "order_type": row[4],
        "role": row[5],
        "requested_price": float(row[6]) if row[6] is not None else None,
        "requested_size": float(row[7]),
        "status": row[8],
        "created_at": row[9].isoformat().replace("+00:00", "Z") if row[9] else None,
        "updated_at": row[10].isoformat().replace("+00:00", "Z") if row[10] else None,
        "client_order_id": row[11],
        "filled_size": float(row[12] or 0),
        "remaining_size": float(row[13] or 0),
        "average_fill_price": float(row[14]) if row[14] is not None else None,
        "submitted_at": row[15].isoformat().replace("+00:00", "Z") if row[15] else None,
    }


def fetch_all_open_orders(account_id: int):
    query = f"""
    SELECT
        order_id,
        account_id,
        symbol,
        side,
        order_type,
        role,
        requested_price,
        requested_size,
        stop_loss,
        tp1,
        tp2,
        tp3,
        status,
        linked_position_id,
        created_at,
        updated_at,
        client_order_id,
        filled_size,
        remaining_size,
        average_fill_price,
        submitted_at
    FROM orders
    WHERE account_id = %s
      AND status IN ({_working_status_sql()})
    ORDER BY created_at DESC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, *WORKING_ORDER_STATUSES))
            rows = cur.fetchall()

    items = []
    for row in rows:
        raw_side = row[3]
        normalized_side = "long" if raw_side == "buy" else "short"

        items.append({
            "order_id": str(row[0]),
            "account_id": int(row[1]),
            "symbol": row[2],
            "side": normalized_side,
            "order_type": row[4].upper(),
            "role": row[5],
            "entry_price": float(row[6]) if row[6] is not None else None,
            "requested_size": float(row[7]) if row[7] is not None else None,
            "stop_loss": float(row[8]) if row[8] is not None else None,
            "tp1": float(row[9]) if row[9] is not None else None,
            "tp2": float(row[10]) if row[10] is not None else None,
            "tp3": float(row[11]) if row[11] is not None else None,
            "status": _normalize_working_status(row[12]),
            "linked_position_id": int(row[13]) if row[13] is not None else None,
            "created_at": row[14].isoformat().replace("+00:00", "Z") if row[14] else None,
            "updated_at": row[15].isoformat().replace("+00:00", "Z") if row[15] else None,
            "client_order_id": row[16],
            "filled_size": float(row[17] or 0),
            "remaining_size": float(row[18] or 0),
            "average_fill_price": float(row[19]) if row[19] is not None else None,
            "submitted_at": row[20].isoformat().replace("+00:00", "Z") if row[20] else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }


def create_order_record(
    account_id: int,
    symbol: str,
    side: str,
    order_type: str,
    requested_price: float | None,
    requested_size: float,
    status: str,
    role: str,
    linked_position_id: int | None = None,
    stop_loss: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
    tp3: float | None = None,
    position_side: str | None = None,
    client_order_id: str | None = None,
    exchange: str | None = None,
    reduce_only: bool = False,
    post_only: bool = False,
):
    query = """
    INSERT INTO orders (
        account_id,
        symbol,
        side,
        order_type,
        requested_price,
        requested_size,
        status,
        role,
        linked_position_id,
        stop_loss,
        tp1,
        tp2,
        tp3,
        position_side,
        client_order_id,
        exchange,
        filled_size,
        remaining_size,
        reduce_only,
        post_only,
        submitted_at,
        created_at,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, 0, %s, %s, %s,
        CASE WHEN %s IN ('submitted', 'acknowledged', 'open', 'partially_filled') THEN NOW() ELSE NULL END,
        NOW(),
        NOW()
    )
    RETURNING order_id
    """

    client_order_id = client_order_id or f"tt-{uuid4().hex}"
    remaining_size = requested_size

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    account_id,
                    symbol,
                    side,
                    order_type,
                    requested_price,
                    requested_size,
                    status,
                    role,
                    linked_position_id,
                    stop_loss,
                    tp1,
                    tp2,
                    tp3,
                    position_side,
                    client_order_id,
                    exchange,
                    remaining_size,
                    reduce_only,
                    post_only,
                    status,
                ),
            )
            order_id = cur.fetchone()[0]
        conn.commit()

    return int(order_id)


def create_order_record_tx(
    cur,
    account_id: int,
    symbol: str,
    side: str,
    order_type: str,
    requested_price: float | None,
    requested_size: float,
    status: str,
    role: str,
    linked_position_id: int | None = None,
    stop_loss: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
    tp3: float | None = None,
    position_side: str | None = None,
    client_order_id: str | None = None,
    exchange: str | None = None,
    reduce_only: bool = False,
    post_only: bool = False,
):
    client_order_id = client_order_id or f"tt-{uuid4().hex}"

    cur.execute(
        """
        INSERT INTO orders (
            account_id,
            symbol,
            side,
            order_type,
            requested_price,
            requested_size,
            status,
            role,
            linked_position_id,
            stop_loss,
            tp1,
            tp2,
            tp3,
            position_side,
            client_order_id,
            exchange,
            filled_size,
            remaining_size,
            reduce_only,
            post_only,
            submitted_at,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, 0, %s, %s, %s,
            CASE WHEN %s IN ('submitted', 'acknowledged', 'open', 'partially_filled') THEN NOW() ELSE NULL END,
            NOW(),
            NOW()
        )
        RETURNING order_id
        """,
        (
            account_id,
            symbol,
            side,
            order_type,
            requested_price,
            requested_size,
            status,
            role,
            linked_position_id,
            stop_loss,
            tp1,
            tp2,
            tp3,
            position_side,
            client_order_id,
            exchange,
            requested_size,
            reduce_only,
            post_only,
            status,
        ),
    )
    return int(cur.fetchone()[0])


def ensure_entry_order(
    account_id: int,
    symbol: str,
    position_side: str,
    order_type: str,
    requested_price: float | None,
    requested_size: float,
    order_id: int | None = None,
    execution_context: dict | None = None,
    retry_attempt: int = 0,
    max_retry_attempts: int | None = None,
    originating_cycle_id: str | None = None,
):
    symbol = symbol.upper()
    side = "buy" if position_side == "long" else "sell"
    context_json = (
        json.dumps(execution_context)
        if execution_context is not None
        else None
    )

    if order_id is not None:
        query = f"""
        UPDATE orders
        SET order_type = %s,
            requested_price = %s,
            requested_size = %s,
            remaining_size = GREATEST(%s - filled_size, 0),
            position_side = %s,
            execution_context = COALESCE(%s::jsonb, execution_context),
            retry_attempt = %s,
            max_retry_attempts = COALESCE(%s, max_retry_attempts),
            originating_cycle_id = COALESCE(%s, originating_cycle_id),
            status = CASE
                WHEN status IN ('created', 'submitted', 'acknowledged', 'open')
                    THEN 'submitted'
                ELSE status
            END,
            submitted_at = COALESCE(submitted_at, NOW()),
            updated_at = NOW()
        WHERE order_id = %s
          AND account_id = %s
          AND symbol = %s
          AND role = 'entry'
          AND status IN ({_active_status_sql()})
        RETURNING order_id
        """

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        order_type,
                        requested_price,
                        requested_size,
                        requested_size,
                        position_side,
                        context_json,
                        retry_attempt,
                        max_retry_attempts,
                        originating_cycle_id,
                        order_id,
                        account_id,
                        symbol,
                        *ACTIVE_ORDER_STATUSES,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

        if row:
            return int(row[0])

    existing = get_open_entry_order(account_id, symbol)
    if existing is not None:
        existing_order_id = int(existing["order_id"])

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE orders
                    SET execution_context = COALESCE(%s::jsonb, execution_context),
                        retry_attempt = %s,
                        max_retry_attempts = COALESCE(%s, max_retry_attempts),
                        originating_cycle_id = COALESCE(%s, originating_cycle_id),
                        updated_at = NOW()
                    WHERE order_id = %s
                    """,
                    (
                        context_json,
                        retry_attempt,
                        max_retry_attempts,
                        originating_cycle_id,
                        existing_order_id,
                    ),
                )
            conn.commit()

        return existing_order_id

    order_id = create_order_record(
        account_id=account_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        requested_price=requested_price,
        requested_size=requested_size,
        status="submitted",
        role="entry",
        position_side=position_side,
        exchange="paper",
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET execution_context = %s::jsonb,
                    retry_attempt = %s,
                    max_retry_attempts = %s,
                    originating_cycle_id = %s,
                    updated_at = NOW()
                WHERE order_id = %s
                """,
                (
                    context_json,
                    retry_attempt,
                    max_retry_attempts,
                    originating_cycle_id,
                    order_id,
                ),
            )
        conn.commit()

    return order_id


def fetch_pending_entry_orders(account_id: int):
    query = f"""
    SELECT
        order_id,
        account_id,
        symbol,
        side,
        position_side,
        order_type,
        requested_price,
        requested_size,
        status,
        filled_size,
        remaining_size,
        average_fill_price,
        execution_context,
        retry_attempt,
        max_retry_attempts,
        originating_cycle_id,
        created_at,
        submitted_at,
        updated_at
    FROM orders
    WHERE account_id = %s
      AND role = 'entry'
      AND status IN ({_active_status_sql()})
    ORDER BY created_at ASC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, *ACTIVE_ORDER_STATUSES))
            rows = cur.fetchall()

    items = []
    for row in rows:
        context = row[12] if isinstance(row[12], dict) else (row[12] or {})

        items.append({
            "order_id": int(row[0]),
            "account_id": int(row[1]),
            "symbol": row[2],
            "side": row[3],
            "position_side": row[4],
            "order_type": row[5],
            "requested_price": float(row[6]) if row[6] is not None else None,
            "requested_size": float(row[7]),
            "status": row[8],
            "filled_size": float(row[9] or 0),
            "remaining_size": float(row[10] or 0),
            "average_fill_price": (
                float(row[11]) if row[11] is not None else None
            ),
            "execution_context": context,
            "retry_attempt": int(row[13] or 0),
            "max_retry_attempts": (
                int(row[14]) if row[14] is not None else None
            ),
            "originating_cycle_id": row[15],
            "created_at": (
                row[16].isoformat().replace("+00:00", "Z")
                if row[16]
                else None
            ),
            "submitted_at": (
                row[17].isoformat().replace("+00:00", "Z")
                if row[17]
                else None
            ),
            "updated_at": (
                row[18].isoformat().replace("+00:00", "Z")
                if row[18]
                else None
            ),
        })

    return items


def cancel_entry_order(account_id: int, order_id: int):
    query = f"""
    UPDATE orders
    SET status = 'cancelled',
        cancelled_at = COALESCE(cancelled_at, NOW()),
        updated_at = NOW()
    WHERE account_id = %s
      AND order_id = %s
      AND role = 'entry'
      AND status IN ({_active_status_sql()})
    RETURNING order_id, symbol, status
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (account_id, order_id, *ACTIVE_ORDER_STATUSES),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "order_id": int(row[0]),
        "symbol": row[1],
        "status": row[2],
    }


def mark_order_open(order_id: int):
    update_order_status(order_id, "open")


def apply_order_fill_tx(cur, order_id: int, fill_size: float, fill_price: float):
    cur.execute(
        """
        UPDATE orders
        SET average_fill_price = CASE
                WHEN filled_size <= 0 OR average_fill_price IS NULL THEN %s
                ELSE ((average_fill_price * filled_size) + (%s * %s))
                     / NULLIF(filled_size + %s, 0)
            END,
            filled_size = LEAST(requested_size, filled_size + %s),
            remaining_size = GREATEST(requested_size - LEAST(requested_size, filled_size + %s), 0),
            status = CASE
                WHEN filled_size + %s >= requested_size THEN 'filled'
                ELSE 'partially_filled'
            END,
            filled_at = CASE
                WHEN filled_size + %s >= requested_size THEN NOW()
                ELSE filled_at
            END,
            updated_at = NOW()
        WHERE order_id = %s
        RETURNING status, filled_size, remaining_size, average_fill_price
        """,
        (
            fill_price,
            fill_price,
            fill_size,
            fill_size,
            fill_size,
            fill_size,
            fill_size,
            fill_size,
            order_id,
        ),
    )
    row = cur.fetchone()
    if not row:
        return None

    return {
        "status": row[0],
        "filled_size": float(row[1]),
        "remaining_size": float(row[2]),
        "average_fill_price": float(row[3]),
    }


def apply_order_fill(order_id: int, fill_size: float, fill_price: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            result = apply_order_fill_tx(cur, order_id, fill_size, fill_price)
        conn.commit()
    return result


def create_protective_orders_for_position(
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):
    exit_side = opposite_order_side(position_side)
    tp1_size = round(original_size * 0.40, 8)
    tp2_size = round(original_size * 0.40, 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)

    common = {
        "account_id": account_id,
        "symbol": symbol,
        "side": exit_side,
        "order_type": "limit",
        "status": "open",
        "linked_position_id": linked_position_id,
        "position_side": position_side,
        "exchange": "paper",
        "reduce_only": True,
    }

    return {
        "stop_loss_order_id": create_order_record(
            **common,
            requested_price=stop_loss,
            requested_size=original_size,
            role="stop_loss",
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record(
            **common,
            requested_price=tp1_price,
            requested_size=tp1_size,
            role="tp1",
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record(
            **common,
            requested_price=tp2_price,
            requested_size=tp2_size,
            role="tp2",
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record(
            **common,
            requested_price=tp3_price,
            requested_size=tp3_size,
            role="tp3",
            tp3=tp3_price,
        ),
    }


def create_protective_orders_for_position_tx(
    cur,
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):
    exit_side = opposite_order_side(position_side)
    tp1_size = round(original_size * 0.40, 8)
    tp2_size = round(original_size * 0.40, 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)

    common = {
        "cur": cur,
        "account_id": account_id,
        "symbol": symbol,
        "side": exit_side,
        "order_type": "limit",
        "status": "open",
        "linked_position_id": linked_position_id,
        "position_side": position_side,
        "exchange": "paper",
        "reduce_only": True,
    }

    return {
        "stop_loss_order_id": create_order_record_tx(
            **common,
            requested_price=stop_loss,
            requested_size=original_size,
            role="stop_loss",
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record_tx(
            **common,
            requested_price=tp1_price,
            requested_size=tp1_size,
            role="tp1",
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record_tx(
            **common,
            requested_price=tp2_price,
            requested_size=tp2_size,
            role="tp2",
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record_tx(
            **common,
            requested_price=tp3_price,
            requested_size=tp3_size,
            role="tp3",
            tp3=tp3_price,
        ),
    }


def reprice_protective_order(account_id: int, order_id: int, new_price: float):
    query = f"""
    UPDATE orders
    SET requested_price = %s,
        tp1 = CASE WHEN role = 'tp1' THEN %s ELSE tp1 END,
        tp2 = CASE WHEN role = 'tp2' THEN %s ELSE tp2 END,
        tp3 = CASE WHEN role = 'tp3' THEN %s ELSE tp3 END,
        updated_at = NOW()
    WHERE account_id = %s
      AND order_id = %s
      AND status IN ({_active_status_sql()})
      AND role IN ('stop_loss', 'tp1', 'tp2', 'tp3')
    RETURNING order_id, role, requested_price, stop_loss
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    new_price,
                    new_price,
                    new_price,
                    new_price,
                    account_id,
                    order_id,
                    *ACTIVE_ORDER_STATUSES,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "order_id": int(row[0]),
        "role": row[1],
        "requested_price": float(row[2]),
        "stop_loss": float(row[3]) if row[3] is not None else None,
    }


def update_order_status(order_id: int, status: str):
    timestamp_fields = {
        "submitted": "submitted_at = COALESCE(submitted_at, NOW()),",
        "acknowledged": "acknowledged_at = COALESCE(acknowledged_at, NOW()),",
        "filled": "filled_at = COALESCE(filled_at, NOW()),",
        "cancelled": "cancelled_at = COALESCE(cancelled_at, NOW()),",
    }
    timestamp_sql = timestamp_fields.get(status, "")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE orders
                SET status = %s,
                    {timestamp_sql}
                    updated_at = NOW()
                WHERE order_id = %s
                """,
                (status, order_id),
            )
        conn.commit()


def cancel_open_protective_orders_for_position(
    position_id: int,
    exclude_order_id: int | None = None,
):
    query = f"""
    UPDATE orders
    SET status = 'cancelled',
        cancelled_at = COALESCE(cancelled_at, NOW()),
        updated_at = NOW()
    WHERE linked_position_id = %s
      AND status IN ({_active_status_sql()})
    """
    params = [position_id, *ACTIVE_ORDER_STATUSES]

    if exclude_order_id is not None:
        query += " AND order_id <> %s"
        params.append(exclude_order_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
        conn.commit()
