from db import get_conn


def apply_entry_balance_update(account_id: int, margin_used: float, fee_paid: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET cash_balance = cash_balance - %s - %s,
                    equity = equity - %s,
                    fees_paid_total = fees_paid_total + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (margin_used, fee_paid, fee_paid, fee_paid, account_id),
            )
        conn.commit()


def apply_exit_balance_update(account_id: int, released_margin: float, realized_pnl: float, fee_paid: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET cash_balance = cash_balance + %s + %s - %s,
                    equity = equity + %s - %s,
                    realized_pnl = realized_pnl + %s,
                    fees_paid_total = fees_paid_total + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (
                    released_margin,
                    realized_pnl,
                    fee_paid,
                    realized_pnl,
                    fee_paid,
                    realized_pnl,
                    fee_paid,
                    account_id,
                ),
            )
        conn.commit()


def apply_entry_balance_update_tx(cur, account_id: int, margin_used: float, fee_paid: float):
    cur.execute(
        """
        UPDATE account_balances
        SET cash_balance = cash_balance - %s - %s,
            equity = equity - %s,
            fees_paid_total = fees_paid_total + %s,
            updated_at = NOW()
        WHERE account_id = %s
        """,
        (margin_used, fee_paid, fee_paid, fee_paid, account_id),
    )
