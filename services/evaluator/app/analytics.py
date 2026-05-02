from db import get_conn
from json_utils import safe_float

def strategy_trade_link_cte():
    return """
    WITH trade_decision_link AS (
        SELECT
            t.trade_id,
            t.account_id,
            t.symbol,
            t.side,
            t.entry_price,
            t.exit_price,
            t.size,
            t.notional,
            t.realized_pnl,
            t.fees_paid,
            t.opened_at,
            t.closed_at,
            edh.candidate_score,
            edh.final_decision,
            edh.strategy_regime,
            edh.strategy_macro_bias,
            edh.best_strategy_candidate,
            edh.strategy_setup_confidence,
            edh.strategy_decision_confidence
        FROM trades t
        LEFT JOIN LATERAL (
            SELECT d.*
            FROM evaluator_decision_history d
            WHERE d.account_id = t.account_id
              AND d.symbol = t.symbol
              AND d.paper_submitted = TRUE
              AND d.decision_timestamp <= t.opened_at
            ORDER BY d.decision_timestamp DESC
            LIMIT 1
        ) edh ON TRUE
        WHERE t.account_id = %s
          AND t.closed_at IS NOT NULL
    )
    """

def get_strategy_analytics_summary(account_id: int):
    cte = strategy_trade_link_cte()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                cte + """
                SELECT
                    COALESCE(COUNT(*), 0) AS total_closed_trades,
                    COALESCE(SUM(realized_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(fees_paid), 0) AS total_fees,
                    COALESCE(AVG(candidate_score), 0) AS avg_trade_score,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - opened_at)) / 60.0), 0) AS avg_hold_minutes
                FROM trade_decision_link
                """,
                (account_id,),
            )
            row = cur.fetchone()

            cur.execute(
                cte + """
                SELECT symbol, COALESCE(SUM(realized_pnl - fees_paid), 0) AS net_pnl
                FROM trade_decision_link
                GROUP BY symbol
                ORDER BY net_pnl DESC
                LIMIT 1
                """,
                (account_id,),
            )
            best_row = cur.fetchone()

            cur.execute(
                cte + """
                SELECT symbol, COALESCE(SUM(realized_pnl - fees_paid), 0) AS net_pnl
                FROM trade_decision_link
                GROUP BY symbol
                ORDER BY net_pnl ASC
                LIMIT 1
                """,
                (account_id,),
            )
            worst_row = cur.fetchone()

    total_closed_trades = int(row[0])
    gross_pnl = safe_float(row[1])
    total_fees = safe_float(row[2])
    net_pnl = gross_pnl - total_fees
    avg_trade_score = safe_float(row[3])
    avg_hold_minutes = safe_float(row[4])
    fee_to_gross_ratio = (total_fees / abs(gross_pnl)) if gross_pnl != 0 else None

    return {
        "ok": True,
        "account_id": account_id,
        "summary": {
            "total_closed_trades": total_closed_trades,
            "gross_pnl": round(gross_pnl, 8),
            "net_pnl": round(net_pnl, 8),
            "total_fees": round(total_fees, 8),
            "avg_trade_score": round(avg_trade_score, 4),
            "avg_hold_minutes": round(avg_hold_minutes, 4),
            "best_symbol": best_row[0] if best_row else None,
            "worst_symbol": worst_row[0] if worst_row else None,
            "fee_to_gross_ratio": round(fee_to_gross_ratio, 6) if fee_to_gross_ratio is not None else None,
        },
    }

def get_strategy_analytics_score_buckets(account_id: int):
    cte = strategy_trade_link_cte()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                cte + """
                SELECT
                    CASE
                        WHEN candidate_score >= 85 THEN '85+'
                        WHEN candidate_score >= 80 THEN '80-84'
                        WHEN candidate_score >= 75 THEN '75-79'
                        WHEN candidate_score >= 70 THEN '70-74'
                        WHEN candidate_score >= 60 THEN '60-69'
                        ELSE '<60'
                    END AS bucket_label,
                    COUNT(*) AS trades,
                    COALESCE(SUM(realized_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(fees_paid), 0) AS total_fees,
                    COALESCE(AVG(realized_pnl - fees_paid), 0) AS expectancy,
                    COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - opened_at)) / 60.0), 0) AS avg_hold_minutes,
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins
                FROM trade_decision_link
                WHERE candidate_score IS NOT NULL
                GROUP BY bucket_label
                ORDER BY
                    CASE bucket_label
                        WHEN '<60' THEN 0
                        WHEN '60-69' THEN 1
                        WHEN '70-74' THEN 2
                        WHEN '75-79' THEN 3
                        WHEN '80-84' THEN 4
                        WHEN '85+' THEN 5
                        ELSE 6
                    END
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    items = []
    for bucket_label, trades, gross_pnl, total_fees, expectancy, avg_hold_minutes, wins in rows:
        trades_i = int(trades)
        win_rate = (int(wins) / trades_i * 100.0) if trades_i > 0 else 0.0
        net_pnl = float(gross_pnl) - float(total_fees)
        items.append({
            "bucket_label": bucket_label,
            "trades": trades_i,
            "gross_pnl": round(float(gross_pnl), 8),
            "net_pnl": round(net_pnl, 8),
            "total_fees": round(float(total_fees), 8),
            "win_rate": round(win_rate, 4),
            "expectancy": round(float(expectancy), 8),
            "avg_hold_minutes": round(float(avg_hold_minutes), 4),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "items": items,
    }

def get_strategy_analytics_symbols(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH trade_base AS (
                    SELECT
                        t.trade_id,
                        t.account_id,
                        t.symbol,
                        t.side,
                        t.realized_pnl,
                        t.fees_paid,
                        t.opened_at,
                        t.closed_at,
                        EXTRACT(EPOCH FROM (t.closed_at - t.opened_at)) / 60.0 AS hold_minutes
                    FROM trades t
                    WHERE t.account_id = %s
                      AND t.closed_at IS NOT NULL
                ),
                outcome_flags AS (
                    SELECT
                        p.symbol,
                        COUNT(*) FILTER (WHERE ge.event_type = 'STOP_LOSS_HIT') AS stop_hits,
                        COUNT(*) FILTER (WHERE ge.event_type = 'TP1_HIT') AS tp1_hits,
                        COUNT(*) FILTER (WHERE ge.event_type = 'TP2_HIT') AS tp2_hits,
                        COUNT(*) FILTER (WHERE ge.event_type = 'TP3_HIT') AS tp3_hits
                    FROM guardian_events ge
                    JOIN positions p
                      ON (ge.details_json->>'position_id')::int = p.position_id
                    WHERE ge.account_id = %s
                      AND ge.event_type IN ('STOP_LOSS_HIT', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT')
                    GROUP BY p.symbol
                )
                SELECT
                    tb.symbol,
                    COUNT(*) AS trades,
                    COALESCE(SUM(tb.realized_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(tb.fees_paid), 0) AS total_fees,
                    COALESCE(AVG(tb.realized_pnl - tb.fees_paid), 0) AS expectancy,
                    COALESCE(AVG(tb.hold_minutes), 0) AS avg_hold_minutes,
                    COALESCE(SUM(CASE WHEN tb.realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(of.stop_hits, 0),
                    COALESCE(of.tp1_hits, 0),
                    COALESCE(of.tp2_hits, 0),
                    COALESCE(of.tp3_hits, 0)
                FROM trade_base tb
                LEFT JOIN outcome_flags of
                  ON of.symbol = tb.symbol
                GROUP BY tb.symbol, of.stop_hits, of.tp1_hits, of.tp2_hits, of.tp3_hits
                ORDER BY (COALESCE(SUM(tb.realized_pnl), 0) - COALESCE(SUM(tb.fees_paid), 0)) DESC
                """,
                (account_id, account_id),
            )
            rows = cur.fetchall()

    items = []
    for symbol, trades, gross_pnl, total_fees, expectancy, avg_hold_minutes, wins, stop_hits, tp1_hits, tp2_hits, tp3_hits in rows:
        trades_i = int(trades)
        gross = float(gross_pnl)
        fees = float(total_fees)
        net = gross - fees
        win_rate = (int(wins) / trades_i * 100.0) if trades_i > 0 else 0.0
        items.append({
            "symbol": symbol,
            "trades": trades_i,
            "gross_pnl": round(gross, 8),
            "net_pnl": round(net, 8),
            "total_fees": round(fees, 8),
            "win_rate": round(win_rate, 4),
            "expectancy": round(float(expectancy), 8),
            "avg_hold_minutes": round(float(avg_hold_minutes), 4),
            "stop_out_rate": round((int(stop_hits) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
            "tp1_rate": round((int(tp1_hits) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
            "tp2_rate": round((int(tp2_hits) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
            "tp3_rate": round((int(tp3_hits) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
            "fee_to_gross_ratio": round((fees / abs(gross)), 6) if gross != 0 else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "items": items,
    }

def get_strategy_analytics_holding_times(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH trade_holds AS (
                    SELECT
                        realized_pnl,
                        EXTRACT(EPOCH FROM (closed_at - opened_at)) / 60.0 AS hold_minutes
                    FROM trades
                    WHERE account_id = %s
                      AND closed_at IS NOT NULL
                )
                SELECT
                    COALESCE(AVG(hold_minutes), 0),
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hold_minutes), 0),
                    COALESCE(AVG(CASE WHEN realized_pnl > 0 THEN hold_minutes END), 0),
                    COALESCE(AVG(CASE WHEN realized_pnl < 0 THEN hold_minutes END), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl < 0 AND hold_minutes < 5 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 AND hold_minutes < 15 THEN 1 ELSE 0 END), 0)
                FROM trade_holds
                """,
                (account_id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                WITH trade_holds AS (
                    SELECT
                        realized_pnl,
                        EXTRACT(EPOCH FROM (closed_at - opened_at)) / 60.0 AS hold_minutes
                    FROM trades
                    WHERE account_id = %s
                      AND closed_at IS NOT NULL
                )
                SELECT
                    CASE
                        WHEN hold_minutes < 5 THEN '<5m'
                        WHEN hold_minutes < 15 THEN '5-15m'
                        WHEN hold_minutes < 30 THEN '15-30m'
                        WHEN hold_minutes < 60 THEN '30-60m'
                        WHEN hold_minutes < 240 THEN '1-4h'
                        ELSE '4h+'
                    END AS bucket_label,
                    COUNT(*) AS trades,
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0) AS winners,
                    COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0) AS losers,
                    COALESCE(SUM(realized_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(realized_pnl - 0), 0) AS net_placeholder
                FROM trade_holds
                GROUP BY bucket_label
                ORDER BY
                    CASE bucket_label
                        WHEN '<5m' THEN 0
                        WHEN '5-15m' THEN 1
                        WHEN '15-30m' THEN 2
                        WHEN '30-60m' THEN 3
                        WHEN '1-4h' THEN 4
                        WHEN '4h+' THEN 5
                        ELSE 6
                    END
                """,
                (account_id,),
            )
            bucket_rows = cur.fetchall()

    summary = {
        "avg_hold_minutes": round(float(row[0]), 4),
        "median_hold_minutes": round(float(row[1]), 4),
        "avg_winner_hold_minutes": round(float(row[2]), 4),
        "avg_loser_hold_minutes": round(float(row[3]), 4),
        "immediate_stopouts_count": int(row[4]),
        "fast_winners_count": int(row[5]),
    }

    buckets = []
    for bucket_label, trades, winners, losers, gross_pnl, net_placeholder in bucket_rows:
        buckets.append({
            "bucket_label": bucket_label,
            "trades": int(trades),
            "winners": int(winners),
            "losers": int(losers),
            "gross_pnl": round(float(gross_pnl), 8),
            "net_pnl": round(float(net_placeholder), 8),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "summary": summary,
        "items": buckets,
    }

def get_strategy_analytics_exit_outcomes(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    event_type,
                    COUNT(*) AS executions,
                    COALESCE(AVG((details_json->>'realized_pnl')::numeric), 0),
                    COALESCE(SUM((details_json->>'realized_pnl')::numeric), 0),
                    COALESCE(SUM((details_json->>'fee_paid')::numeric), 0)
                FROM guardian_events
                WHERE account_id = %s
                  AND event_type IN ('STOP_LOSS_HIT', 'TP1_HIT', 'TP2_HIT', 'TP3_HIT')
                GROUP BY event_type
                """,
                (account_id,),
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT COALESCE(COUNT(*), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                """,
                (account_id,),
            )
            total_trades = int(cur.fetchone()[0])

    summary = {
        "stop_loss_rate": 0.0,
        "tp1_rate": 0.0,
        "tp2_rate": 0.0,
        "tp3_rate": 0.0,
    }

    items = []
    mapping = {
        "STOP_LOSS_HIT": "STOP_LOSS",
        "TP1_HIT": "TP1",
        "TP2_HIT": "TP2",
        "TP3_HIT": "TP3",
    }

    for event_type, executions, avg_realized_pnl, total_realized_pnl, total_fees in rows:
        label = mapping.get(event_type, event_type)
        exec_i = int(executions)

        if total_trades > 0:
            rate = exec_i / total_trades * 100.0
            if label == "STOP_LOSS":
                summary["stop_loss_rate"] = round(rate, 4)
            elif label == "TP1":
                summary["tp1_rate"] = round(rate, 4)
            elif label == "TP2":
                summary["tp2_rate"] = round(rate, 4)
            elif label == "TP3":
                summary["tp3_rate"] = round(rate, 4)

        items.append({
            "exit_type": label,
            "executions": exec_i,
            "avg_realized_pnl": round(float(avg_realized_pnl), 8),
            "total_realized_pnl": round(float(total_realized_pnl), 8),
            "total_fees": round(float(total_fees), 8),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "summary": summary,
        "items": items,
    }

def get_strategy_analytics_fee_pressure(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    symbol,
                    COUNT(*) AS trades,
                    COALESCE(SUM(realized_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(fees_paid), 0) AS total_fees,
                    COALESCE(AVG(fees_paid), 0) AS avg_fees_per_trade
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                GROUP BY symbol
                ORDER BY symbol ASC
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    items = []
    total_fees = 0.0
    total_gross = 0.0

    for symbol, trades, gross_pnl, fees, avg_fees_per_trade in rows:
        gross = float(gross_pnl)
        fee_val = float(fees)
        total_fees += fee_val
        total_gross += gross

        items.append({
            "symbol": symbol,
            "gross_pnl": round(gross, 8),
            "total_fees": round(fee_val, 8),
            "net_pnl": round(gross - fee_val, 8),
            "avg_fees_per_trade": round(float(avg_fees_per_trade), 8),
            "fee_to_gross_ratio": round((fee_val / abs(gross)), 6) if gross != 0 else None,
        })

    worst_fee_symbol = None
    best_fee_efficiency_symbol = None

    if items:
        worst_fee_symbol = max(items, key=lambda x: x["total_fees"])["symbol"]
        efficiency_candidates = [x for x in items if x["fee_to_gross_ratio"] is not None]
        if efficiency_candidates:
            best_fee_efficiency_symbol = min(efficiency_candidates, key=lambda x: x["fee_to_gross_ratio"])["symbol"]

    return {
        "ok": True,
        "account_id": account_id,
        "summary": {
            "total_fees": round(total_fees, 8),
            "fee_to_gross_ratio": round((total_fees / abs(total_gross)), 6) if total_gross != 0 else None,
            "avg_fees_per_trade": round((total_fees / len(items)), 8) if items else 0.0,
            "worst_fee_symbol": worst_fee_symbol,
            "best_fee_efficiency_symbol": best_fee_efficiency_symbol,
        },
        "items": items,
    }