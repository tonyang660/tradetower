from db import get_conn


def get_decision_funnel(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN candidate_score IS NOT NULL THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN final_decision IN ('no_trade', 'observe') THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN risk_approved = TRUE THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN guardian_allowed = TRUE THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN paper_submitted = TRUE THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN filled = TRUE THEN 1 ELSE 0 END), 0)
                FROM evaluator_decision_history
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cur.fetchone()

    return {
        "ok": True,
        "account_id": account_id,
        "funnel": {
            "decision_rows": int(row[0]),
            "candidate_filter_seen": int(row[1]),
            "no_trade": int(row[2]),
            "risk_approved": int(row[3]),
            "guardian_allowed": int(row[4]),
            "paper_submitted": int(row[5]),
            "filled": int(row[6]),
        },
    }
