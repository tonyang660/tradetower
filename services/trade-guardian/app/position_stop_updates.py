"""
Position stop update helpers.

Kept separate from positions.py to avoid a large full-file replacement while
Phase 6 position-management logic is being introduced.
"""

from db import get_conn


def update_position_stop_loss(
    *,
    account_id: int,
    position_id: int,
    new_stop_loss: float,
):
    query = """
    UPDATE positions
    SET stop_loss = %s
    WHERE account_id = %s
      AND position_id = %s
      AND status = 'open'
    RETURNING position_id, stop_loss
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    float(new_stop_loss),
                    int(account_id),
                    int(position_id),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "position_id": int(row[0]),
        "stop_loss": float(row[1]),
    }
