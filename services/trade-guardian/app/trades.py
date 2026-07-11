from db import get_conn
from guardian_state import apply_completed_trade_result_tx


def maybe_finalize_trade(position: dict):
    query = """
    SELECT
        COALESCE(SUM(
            CASE
                WHEN er.execution_type IN ('TP1', 'TP2', 'TP3', 'STOP_LOSS')
                THEN CASE
                    WHEN p.side = 'long'
                        THEN (er.fill_price - p.entry_price) * er.filled_size
                    WHEN p.side = 'short'
                        THEN (p.entry_price - er.fill_price) * er.filled_size
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
      AND er.execution_timestamp >= (
          p.opened_at - INTERVAL '10 seconds'
      )
      AND er.execution_type IN (
          'ENTRY',
          'TP1',
          'TP2',
          'TP3',
          'STOP_LOSS'
      )
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Idempotency: one completed trade per position.
            cur.execute(
                """
                SELECT trade_id
                FROM trades
                WHERE position_id = %s
                """,
                (position["position_id"],),
            )
            existing_trade = cur.fetchone()

            if existing_trade:
                return int(existing_trade[0])

            cur.execute(
                query,
                (
                    position["position_id"],
                    position["account_id"],
                    position["symbol"],
                ),
            )
            (
                pnl_sum,
                fees_sum,
                weighted_exit_numerator,
                total_closed_size,
            ) = cur.fetchone()

            realized_pnl = float(pnl_sum or 0)
            total_fees = float(fees_sum or 0)

            avg_exit_price = None
            if total_closed_size and float(total_closed_size) > 0:
                avg_exit_price = (
                    float(weighted_exit_numerator)
                    / float(total_closed_size)
                )

            notional = (
                float(position["entry_price"])
                * float(position["original_size"])
            )

            cur.execute(
                """
                INSERT INTO trades (
                    position_id,
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
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, NOW()
                )
                RETURNING trade_id
                """,
                (
                    position["position_id"],
                    position["account_id"],
                    position["symbol"],
                    position["side"],
                    position["entry_price"],
                    avg_exit_price,
                    position["original_size"],
                    position["leverage"],
                    notional,
                    realized_pnl,
                    total_fees,
                    position["opened_at"],
                ),
            )
            trade_id = int(cur.fetchone()[0])

            apply_completed_trade_result_tx(
                cur=cur,
                account_id=position["account_id"],
                trade_id=trade_id,
                realized_pnl=realized_pnl,
            )

        conn.commit()

    return trade_id
