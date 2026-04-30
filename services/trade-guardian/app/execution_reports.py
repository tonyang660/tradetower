from db import get_conn


def insert_execution_report(account_id: int, order_id, symbol: str, fill_price: float, filled_size: float,
                            fee_paid: float, slippage_bps: float, notes: str | None,
                            execution_type: str, position_side: str):
    query = """
    INSERT INTO execution_reports (
        order_id,
        account_id,
        symbol,
        fill_price,
        filled_size,
        fee_paid,
        slippage_bps,
        execution_timestamp,
        notes,
        execution_type,
        position_side
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
    RETURNING execution_id
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    order_id,
                    account_id,
                    symbol,
                    fill_price,
                    filled_size,
                    fee_paid,
                    slippage_bps,
                    notes,
                    execution_type,
                    position_side,
                ),
            )
            execution_id = cur.fetchone()[0]
        conn.commit()

    return execution_id


def insert_execution_report_tx(cur, account_id: int, order_id, symbol: str, fill_price: float, filled_size: float,
                               fee_paid: float, slippage_bps: float, notes: str | None,
                               execution_type: str, position_side: str):
    cur.execute(
        """
        INSERT INTO execution_reports (
            order_id,
            account_id,
            symbol,
            fill_price,
            filled_size,
            fee_paid,
            slippage_bps,
            execution_timestamp,
            notes,
            execution_type,
            position_side
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
        RETURNING execution_id
        """,
        (
            order_id,
            account_id,
            symbol,
            fill_price,
            filled_size,
            fee_paid,
            slippage_bps,
            notes,
            execution_type,
            position_side,
        ),
    )
    return int(cur.fetchone()[0])
