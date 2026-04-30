from db import get_conn


def get_open_position(account_id: int, symbol: str):
    query = """
    SELECT
        position_id,
        account_id,
        symbol,
        side,
        size,
        original_size,
        remaining_size,
        entry_price,
        leverage,
        margin_used,
        stop_loss,
        take_profit,
        risk_amount,
        tp1_price,
        tp2_price,
        tp3_price,
        tp1_hit,
        tp2_hit,
        tp3_hit,
        opened_at,
        closed_at,
        status
    FROM positions
    WHERE account_id = %s
      AND symbol = %s
      AND status = 'open'
    ORDER BY opened_at DESC
    LIMIT 1
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id, symbol))
            row = cur.fetchone()

    if not row:
        return None

    return {
        "position_id": row[0],
        "account_id": row[1],
        "symbol": row[2],
        "side": row[3],
        "size": float(row[4]),
        "original_size": float(row[5]) if row[5] is not None else float(row[4]),
        "remaining_size": float(row[6]) if row[6] is not None else float(row[4]),
        "entry_price": float(row[7]),
        "leverage": float(row[8]),
        "margin_used": float(row[9]),
        "stop_loss": float(row[10]) if row[10] is not None else None,
        "take_profit": float(row[11]) if row[11] is not None else None,
        "risk_amount": float(row[12]) if row[12] is not None else 0.0,
        "tp1_price": float(row[13]) if row[13] is not None else None,
        "tp2_price": float(row[14]) if row[14] is not None else None,
        "tp3_price": float(row[15]) if row[15] is not None else None,
        "tp1_hit": row[16],
        "tp2_hit": row[17],
        "tp3_hit": row[18],
        "opened_at": row[19],
        "closed_at": row[20],
        "status": row[21],
    }


def fetch_open_position_for_api(account_id: int, symbol: str):
    position = get_open_position(account_id, symbol)
    if position is None:
        return None

    return {
        **position,
        "opened_at": position["opened_at"].isoformat().replace("+00:00", "Z")
        if position.get("opened_at") else None,
        "closed_at": position["closed_at"].isoformat().replace("+00:00", "Z")
        if position.get("closed_at") else None,
    }


def fetch_all_open_positions(account_id: int):
    query = """
    SELECT
        p.position_id,
        p.account_id,
        p.symbol,
        p.side,
        p.original_size,
        p.remaining_size,
        p.entry_price,
        p.leverage,
        p.margin_used,
        p.stop_loss,
        p.tp1_price,
        p.tp2_price,
        p.tp3_price,
        p.tp1_hit,
        p.tp2_hit,
        p.tp3_hit,
        p.opened_at,
        p.status,
        COALESCE((
            SELECT SUM(
                CASE
                    WHEN ge.details_json ? 'fee_paid'
                    THEN (ge.details_json->>'fee_paid')::numeric
                    ELSE 0
                END
            )
            FROM guardian_events ge
            WHERE ge.account_id = p.account_id
              AND ge.event_type IN ('POSITION_OPENED', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'STOP_LOSS_HIT')
              AND ge.details_json->>'position_id' = p.position_id::text
        ), 0) AS fees_paid_total,
        COALESCE((
            SELECT SUM(
                CASE
                    WHEN ge.details_json ? 'realized_pnl'
                    THEN (ge.details_json->>'realized_pnl')::numeric
                    ELSE 0
                END
            )
            FROM guardian_events ge
            WHERE ge.account_id = p.account_id
              AND ge.event_type IN ('TP1_HIT', 'TP2_HIT', 'TP3_HIT', 'STOP_LOSS_HIT')
              AND ge.details_json->>'position_id' = p.position_id::text
        ), 0) AS realized_pnl_closed
    FROM positions p
    WHERE p.account_id = %s
      AND p.status = 'open'
    ORDER BY p.opened_at ASC
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (account_id,))
            rows = cur.fetchall()

    results = []
    for row in rows:
        results.append({
            "position_id": row[0],
            "account_id": row[1],
            "symbol": row[2],
            "side": row[3],
            "original_size": float(row[4]),
            "remaining_size": float(row[5]),
            "entry_price": float(row[6]),
            "leverage": float(row[7]),
            "margin_used": float(row[8]) if row[8] is not None else 0.0,
            "stop_loss": float(row[9]) if row[9] is not None else None,
            "tp1_price": float(row[10]) if row[10] is not None else None,
            "tp2_price": float(row[11]) if row[11] is not None else None,
            "tp3_price": float(row[12]) if row[12] is not None else None,
            "tp1_hit": row[13],
            "tp2_hit": row[14],
            "tp3_hit": row[15],
            "opened_at": row[16].isoformat().replace("+00:00", "Z") if row[16] else None,
            "status": row[17],
            "fees_paid": float(row[18]) if row[18] is not None else 0.0,
            "realized_pnl_closed": float(row[19]) if row[19] is not None else 0.0,
        })

    return results


def create_open_position(account_id: int, symbol: str, position_side: str, size: float, entry_price: float,
                         leverage: float, stop_loss: float, tp1_price: float, tp2_price: float,
                         tp3_price: float, risk_amount: float):
    margin_used = size * entry_price / leverage if leverage != 0 else size * entry_price

    query = """
    INSERT INTO positions (
        account_id,
        symbol,
        side,
        size,
        original_size,
        remaining_size,
        entry_price,
        leverage,
        margin_used,
        stop_loss,
        take_profit,
        risk_amount,
        tp1_price,
        tp2_price,
        tp3_price,
        tp1_hit,
        tp2_hit,
        tp3_hit,
        opened_at,
        status
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, FALSE, NOW(), 'open')
    RETURNING position_id
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    account_id,
                    symbol,
                    position_side,
                    size,
                    size,
                    size,
                    entry_price,
                    leverage,
                    margin_used,
                    stop_loss,
                    tp3_price,
                    risk_amount,
                    tp1_price,
                    tp2_price,
                    tp3_price,
                ),
            )
            position_id = cur.fetchone()[0]
        conn.commit()

    return position_id


def create_open_position_tx(cur, account_id: int, symbol: str, position_side: str, size: float, entry_price: float,
                            leverage: float, stop_loss: float, tp1_price: float, tp2_price: float,
                            tp3_price: float, risk_amount: float):
    margin_used = size * entry_price / leverage if leverage != 0 else size * entry_price

    cur.execute(
        """
        INSERT INTO positions (
            account_id,
            symbol,
            side,
            size,
            original_size,
            remaining_size,
            entry_price,
            leverage,
            margin_used,
            stop_loss,
            take_profit,
            risk_amount,
            tp1_price,
            tp2_price,
            tp3_price,
            tp1_hit,
            tp2_hit,
            tp3_hit,
            opened_at,
            status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE, FALSE, NOW(), 'open')
        RETURNING position_id, margin_used
        """,
        (
            account_id,
            symbol,
            position_side,
            size,
            size,
            size,
            entry_price,
            leverage,
            margin_used,
            stop_loss,
            tp3_price,
            risk_amount,
            tp1_price,
            tp2_price,
            tp3_price,
        ),
    )
    row = cur.fetchone()
    return int(row[0]), float(row[1])


def update_position_after_partial_exit(
    position_id: int,
    remaining_size: float,
    remaining_margin_used: float,
    tp1_hit=None,
    tp2_hit=None,
    tp3_hit=None,
):
    updates = ["remaining_size = %s", "margin_used = %s"]
    values = [remaining_size, remaining_margin_used]

    if tp1_hit is not None:
        updates.append("tp1_hit = %s")
        values.append(tp1_hit)
    if tp2_hit is not None:
        updates.append("tp2_hit = %s")
        values.append(tp2_hit)
    if tp3_hit is not None:
        updates.append("tp3_hit = %s")
        values.append(tp3_hit)

    values.append(position_id)

    query = f"""
    UPDATE positions
    SET {", ".join(updates)}
    WHERE position_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
        conn.commit()


def close_position(position_id: int, tp1_hit=None, tp2_hit=None, tp3_hit=None):
    updates = ["status = 'closed'", "closed_at = NOW()", "margin_used = 0", "remaining_size = 0"]
    values = []

    if tp1_hit is not None:
        updates.append("tp1_hit = %s")
        values.append(tp1_hit)
    if tp2_hit is not None:
        updates.append("tp2_hit = %s")
        values.append(tp2_hit)
    if tp3_hit is not None:
        updates.append("tp3_hit = %s")
        values.append(tp3_hit)

    values.append(position_id)

    query = f"""
    UPDATE positions
    SET {", ".join(updates)}
    WHERE position_id = %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
        conn.commit()


def calculate_realized_pnl(position_side: str, entry_price: float, exit_price: float, close_size: float) -> float:
    if position_side == "long":
        return (exit_price - entry_price) * close_size
    if position_side == "short":
        return (entry_price - exit_price) * close_size
    raise ValueError("unsupported_position_side")
