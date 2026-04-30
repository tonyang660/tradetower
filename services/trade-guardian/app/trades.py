from db import get_conn


def maybe_finalize_trade(position: dict):
    query = """
    SELECT
        COALESCE(SUM(
            CASE
                WHEN er.execution_type IN ('TP1', 'TP2', 'TP3', 'STOP_LOSS')
                THEN CASE
                    WHEN p.side = 'long' THEN (er.fill_price - p.entry_price) * er.filled_size
                    WHEN p.side = 'short' THEN (p.entry_price - er.fill_price) * er.filled_size
                    ELSE 0
                END
                ELSE 0
            END
        ), 0) AS realized_pnl_sum,
        COALESCE(SUM(er.fee_paid), 0) AS total_fees_sum,
        COALESCE(SUM(
            CASE
                WHEN er.execution_type IN ('TP1', 'TP2', 'TP3', 'STOP_LOSS')
                THEN er.fill_price * er.filled_size
                ELSE 0
            END
        ), 0) AS weighted_exit_numerator,
        COALESCE(SUM(
            CASE
                WHEN er.execution_type IN ('TP1', 'TP2', 'TP3', 'STOP_LOSS')
                THEN er.filled_size
                ELSE 0
            END
        ), 0) AS total_closed_size
    FROM execution_reports er
    JOIN positions p
      ON p.position_id = %s
    WHERE er.account_id = %s
      AND er.symbol = %s
      AND er.execution_timestamp >= (p.opened_at - INTERVAL '10 seconds')
      AND er.execution_type IN ('ENTRY', 'TP1', 'TP2', 'TP3', 'STOP_LOSS')
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    position["position_id"],
                    position["account_id"],
                    position["symbol"],
                ),
            )
            pnl_sum, fees_sum, weighted_exit_numerator, total_closed_size = cur.fetchone()

            avg_exit_price = None
            if total_closed_size and float(total_closed_size) > 0:
                avg_exit_price = float(weighted_exit_numerator) / float(total_closed_size)

            notional = float(position["entry_price"]) * float(position["original_size"])

            cur.execute(
                """
                INSERT INTO trades (
                    account_id,
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
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING trade_id
                """,
                (
                    position["account_id"],
                    position["symbol"],
                    position["side"],
                    position["entry_price"],
                    avg_exit_price,
                    position["original_size"],
                    position["leverage"],
                    notional,
                    float(pnl_sum or 0),
                    float(fees_sum or 0),
                    position["opened_at"],
                ),
            )
            trade_id = cur.fetchone()[0]

        conn.commit()

    return trade_id
