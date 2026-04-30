from db import get_conn


def opposite_order_side(position_side: str) -> str:
    return "sell" if position_side == "long" else "buy"


def get_open_entry_order(account_id: int, symbol: str):
    query = """
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
        updated_at
    FROM orders
    WHERE account_id = %s
      AND symbol = %s
      AND status IN ('planned', 'submitted')
      AND (role = 'entry' OR role IS NULL)
    ORDER BY created_at DESC
    LIMIT 1
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, symbol))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "order_id": row[0],
        "account_id": row[1],
        "symbol": row[2],
        "side": row[3],
        "order_type": row[4],
        "role": row[5],
        "requested_price": float(row[6]) if row[6] is not None else None,
        "requested_size": float(row[7]) if row[7] is not None else None,
        "status": row[8],
        "created_at": row[9].isoformat().replace("+00:00", "Z") if row[9] else None,
        "updated_at": row[10].isoformat().replace("+00:00", "Z") if row[10] else None,
    }


def fetch_all_open_orders(account_id: int):
    query = """
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
        updated_at
    FROM orders
    WHERE account_id = %s
      AND status IN ('planned', 'submitted')
    ORDER BY created_at DESC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            rows = cur.fetchall()

    items = []
    for row in rows:
        raw_side = row[3]
        normalized_side = "long" if raw_side == "buy" else "short"

        normalized_status = row[12]
        if normalized_status == "planned":
            normalized_status = "PENDING_ENTRY"
        elif normalized_status == "submitted":
            normalized_status = "RESTING"
        elif normalized_status == "filled":
            normalized_status = "FILLED"
        elif normalized_status == "cancelled":
            normalized_status = "CANCELLED"
        elif normalized_status == "rejected":
            normalized_status = "REJECTED"

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
            "status": normalized_status,
            "linked_position_id": int(row[13]) if row[13] is not None else None,
            "submitted_at": row[14].isoformat().replace("+00:00", "Z") if row[14] else None,
            "updated_at": row[15].isoformat().replace("+00:00", "Z") if row[15] else None,
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
        created_at,
        updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    RETURNING order_id
    """

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
):
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
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
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
        ),
    )
    return int(cur.fetchone()[0])


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

    created = {
        "stop_loss_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=stop_loss,
            requested_size=original_size,
            status="submitted",
            role="stop_loss",
            linked_position_id=linked_position_id,
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp1_price,
            requested_size=tp1_size,
            status="submitted",
            role="tp1",
            linked_position_id=linked_position_id,
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp2_price,
            requested_size=tp2_size,
            status="submitted",
            role="tp2",
            linked_position_id=linked_position_id,
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record(
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp3_price,
            requested_size=tp3_size,
            status="submitted",
            role="tp3",
            linked_position_id=linked_position_id,
            tp3=tp3_price,
        ),
    }

    return created


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

    return {
        "stop_loss_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=stop_loss,
            requested_size=original_size,
            status="submitted",
            role="stop_loss",
            linked_position_id=linked_position_id,
            stop_loss=stop_loss,
        ),
        "tp1_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp1_price,
            requested_size=tp1_size,
            status="submitted",
            role="tp1",
            linked_position_id=linked_position_id,
            tp1=tp1_price,
        ),
        "tp2_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp2_price,
            requested_size=tp2_size,
            status="submitted",
            role="tp2",
            linked_position_id=linked_position_id,
            tp2=tp2_price,
        ),
        "tp3_order_id": create_order_record_tx(
            cur=cur,
            account_id=account_id,
            symbol=symbol,
            side=exit_side,
            order_type="limit",
            requested_price=tp3_price,
            requested_size=tp3_size,
            status="submitted",
            role="tp3",
            linked_position_id=linked_position_id,
            tp3=tp3_price,
        ),
    }


def reprice_protective_order(account_id: int, order_id: int, new_price: float):
    query = """
    UPDATE orders
    SET requested_price = %s,
        tp1 = CASE WHEN role = 'tp1' THEN %s ELSE tp1 END,
        tp2 = CASE WHEN role = 'tp2' THEN %s ELSE tp2 END,
        tp3 = CASE WHEN role = 'tp3' THEN %s ELSE tp3 END,
        updated_at = NOW()
    WHERE account_id = %s
      AND order_id = %s
      AND status IN ('planned', 'submitted')
      AND role IN ('stop_loss', 'tp1', 'tp2', 'tp3')
    RETURNING order_id, role, requested_price, stop_loss
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (new_price, new_price, new_price, new_price, account_id, order_id),
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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET status = %s,
                    updated_at = NOW()
                WHERE order_id = %s
                """,
                (status, order_id),
            )
        conn.commit()


def cancel_open_protective_orders_for_position(position_id: int, exclude_order_id: int | None = None):
    query = """
    UPDATE orders
    SET status = 'cancelled',
        updated_at = NOW()
    WHERE linked_position_id = %s
      AND status IN ('planned', 'submitted')
    """
    params = [position_id]

    if exclude_order_id is not None:
        query += " AND order_id <> %s"
        params.append(exclude_order_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
        conn.commit()
