from db import get_conn
from json_utils import safe_float, session_name_from_hour


def get_performance_summary(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(AVG(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(MAX(realized_pnl), 0),
                    COALESCE(MIN(realized_pnl), 0),
                    COALESCE(SUM(fees_paid), 0)
                FROM trades
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cur.fetchone()

    total_trades = int(row[0])
    wins = int(row[3])
    losses = int(row[4])
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

    return {
        "ok": True,
        "account_id": account_id,
        "performance": {
            "completed_trades": total_trades,
            "net_realized_pnl": float(row[1]),
            "average_trade_pnl": float(row[2]),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "best_trade": float(row[5]),
            "worst_trade": float(row[6]),
            "fees_paid_total": float(row[7]),
        },
    }


def get_performance_summary_extended(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(COUNT(*), 0),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(fees_paid), 0),
                    COALESCE(AVG(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END), 0),
                    COALESCE(AVG(CASE WHEN realized_pnl < 0 THEN realized_pnl END), 0),
                    COALESCE(MAX(realized_pnl), 0),
                    COALESCE(MIN(realized_pnl), 0)
                FROM trades
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT equity
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at ASC
                """,
                (account_id,),
            )
            equity_rows = [float(x[0]) for x in cur.fetchall()]

    total_trades = int(row[0])
    gross_pnl = safe_float(row[1])
    total_fees = safe_float(row[2])
    net_pnl = gross_pnl - total_fees
    avg_trade = safe_float(row[3])
    wins = int(row[4])
    losses = int(row[5])
    avg_win = safe_float(row[6])
    avg_loss = safe_float(row[7])
    best_trade = safe_float(row[8])
    worst_trade = safe_float(row[9])

    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    expectancy = avg_trade

    gross_losses_abs = abs(avg_loss) * losses if losses > 0 else 0.0
    gross_wins = gross_pnl
    profit_factor = (gross_wins / gross_losses_abs) if gross_losses_abs > 0 else None

    average_rr = (avg_win / abs(avg_loss)) if avg_loss < 0 else None

    sharpe_ratio = None
    if total_trades > 1:
        trade_returns = []
        for v in [best_trade, worst_trade]:
            pass

    # simple trade-level Sharpe proxy based on realized pnl distribution
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT realized_pnl
                FROM trades
                WHERE account_id = %s
                ORDER BY closed_at ASC
                """,
                (account_id,),
            )
            pnl_values = [float(x[0]) for x in cur.fetchall()]

    if len(pnl_values) > 1:
        mean_val = sum(pnl_values) / len(pnl_values)
        variance = sum((x - mean_val) ** 2 for x in pnl_values) / (len(pnl_values) - 1)
        std_dev = variance ** 0.5
        if std_dev > 0:
            sharpe_ratio = mean_val / std_dev

    max_drawdown_value = 0.0
    max_drawdown_pct = 0.0
    equity_change_pct = 0.0

    if equity_rows:
        start_equity = equity_rows[0]
        end_equity = equity_rows[-1]
        if start_equity > 0:
            equity_change_pct = ((end_equity - start_equity) / start_equity) * 100.0

        peak = equity_rows[0]
        for eq in equity_rows:
            if eq > peak:
                peak = eq
            dd_value = peak - eq
            dd_pct = (dd_value / peak * 100.0) if peak > 0 else 0.0
            if dd_value > max_drawdown_value:
                max_drawdown_value = dd_value
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

    return {
        "ok": True,
        "account_id": account_id,
        "summary": {
            "gross_pnl": round(gross_pnl, 8),
            "net_pnl": round(net_pnl, 8),
            "total_fees_paid": round(total_fees, 8),
            "equity_change_pct": round(equity_change_pct, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "max_drawdown_value": round(max_drawdown_value, 8),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 4),
            "expectancy": round(expectancy, 8),
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "average_win": round(avg_win, 8),
            "average_loss": round(avg_loss, 8),
            "average_rr": round(average_rr, 4) if average_rr is not None else None,
            "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
            "best_trade": round(best_trade, 8),
            "worst_trade": round(worst_trade, 8),
            "wins": wins,
            "losses": losses,
        },
    }


def get_drawdown_series(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, equity
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at ASC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    peak = None

    for recorded_at, equity in rows:
        eq = float(equity)
        if peak is None or eq > peak:
            peak = eq

        drawdown_value = max(0.0, peak - eq)
        drawdown_pct = (drawdown_value / peak * 100.0) if peak and peak > 0 else 0.0

        items.append({
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "equity": eq,
            "peak_equity": round(peak, 8),
            "drawdown_value": round(drawdown_value, 8),
            "drawdown_pct": round(drawdown_pct, 4),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }


def get_directional_breakdown(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    side,
                    COUNT(*),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(AVG(realized_pnl), 0)
                FROM trades
                WHERE account_id = %s
                GROUP BY side
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    result = {
        "long": {"trades": 0, "pnl": 0.0, "win_rate": 0.0, "expectancy": 0.0},
        "short": {"trades": 0, "pnl": 0.0, "win_rate": 0.0, "expectancy": 0.0},
    }

    for side, count, pnl, wins, expectancy in rows:
        total = int(count)
        wr = (int(wins) / total * 100.0) if total > 0 else 0.0

        result[side] = {
            "trades": total,
            "pnl": round(float(pnl), 8),
            "win_rate": round(wr, 4),
            "expectancy": round(float(expectancy), 8),
        }

    return {
        "ok": True,
        "account_id": account_id,
        "directional_breakdown": result,
    }


def get_hourly_performance(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(HOUR FROM closed_at AT TIME ZONE 'UTC')::int AS hour_utc,
                    COUNT(*),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                GROUP BY hour_utc
                ORDER BY hour_utc ASC
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    by_hour = {h: {"hour": h, "pnl": 0.0, "trades": 0, "win_rate": 0.0} for h in range(24)}

    for hour_utc, trades, pnl, wins in rows:
        trades_i = int(trades)
        by_hour[int(hour_utc)] = {
            "hour": int(hour_utc),
            "pnl": round(float(pnl), 8),
            "trades": trades_i,
            "win_rate": round((int(wins) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
        }

    return {
        "ok": True,
        "account_id": account_id,
        "items": [by_hour[h] for h in range(24)],
    }


def get_weekday_performance(account_id: int):
    weekday_names = {
        0: "Monday",
        1: "Tuesday",
        2: "Wednesday",
        3: "Thursday",
        4: "Friday",
        5: "Saturday",
        6: "Sunday",
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(DOW FROM closed_at AT TIME ZONE 'UTC')::int AS dow_pg,
                    COUNT(*),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                GROUP BY dow_pg
                ORDER BY dow_pg ASC
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    # postgres DOW: Sunday=0 ... Saturday=6
    result = {name: {"weekday": name, "pnl": 0.0, "trades": 0, "win_rate": 0.0} for name in weekday_names.values()}

    for dow_pg, trades, pnl, wins in rows:
        # remap to Monday-first naming
        if int(dow_pg) == 0:
            name = "Sunday"
        elif int(dow_pg) == 1:
            name = "Monday"
        elif int(dow_pg) == 2:
            name = "Tuesday"
        elif int(dow_pg) == 3:
            name = "Wednesday"
        elif int(dow_pg) == 4:
            name = "Thursday"
        elif int(dow_pg) == 5:
            name = "Friday"
        else:
            name = "Saturday"

        trades_i = int(trades)
        result[name] = {
            "weekday": name,
            "pnl": round(float(pnl), 8),
            "trades": trades_i,
            "win_rate": round((int(wins) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
        }

    ordered = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    return {
        "ok": True,
        "account_id": account_id,
        "items": [result[name] for name in ordered],
    }


def get_session_performance(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(HOUR FROM closed_at AT TIME ZONE 'UTC')::int AS hour_utc,
                    realized_pnl
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                ORDER BY closed_at ASC
                """,
                (account_id,),
            )
            rows = cur.fetchall()

    bucket = {
        "Asia": {"session": "Asia", "pnl": 0.0, "trades": 0, "wins": 0},
        "London": {"session": "London", "pnl": 0.0, "trades": 0, "wins": 0},
        "New York": {"session": "New York", "pnl": 0.0, "trades": 0, "wins": 0},
        "Late": {"session": "Late", "pnl": 0.0, "trades": 0, "wins": 0},
    }

    for hour_utc, realized_pnl in rows:
        session = session_name_from_hour(int(hour_utc))
        pnl = float(realized_pnl)

        bucket[session]["pnl"] += pnl
        bucket[session]["trades"] += 1
        if pnl > 0:
            bucket[session]["wins"] += 1

    items = []
    for session in ["Asia", "London", "New York", "Late"]:
        trades = bucket[session]["trades"]
        wins = bucket[session]["wins"]
        items.append({
            "session": session,
            "pnl": round(bucket[session]["pnl"], 8),
            "trades": trades,
            "win_rate": round((wins / trades * 100.0), 4) if trades > 0 else 0.0,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "items": items,
    }


def get_calendar_performance(account_id: int, limit_days: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (closed_at AT TIME ZONE 'UTC')::date AS trade_day,
                    COUNT(*),
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                GROUP BY trade_day
                ORDER BY trade_day DESC
                LIMIT %s
                """,
                (account_id, limit_days),
            )
            rows = cur.fetchall()

    items = []
    for trade_day, trades, pnl, wins in reversed(rows):
        trades_i = int(trades)
        items.append({
            "date": str(trade_day),
            "pnl": round(float(pnl), 8),
            "trades": trades_i,
            "win_rate": round((int(wins) / trades_i * 100.0), 4) if trades_i > 0 else 0.0,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }


def get_monthly_summary(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR((closed_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month_key,
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(COUNT(*), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                GROUP BY month_key
                ORDER BY month_key DESC
                LIMIT 1
                """,
                (account_id,),
            )
            month_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    (closed_at AT TIME ZONE 'UTC')::date AS trade_day,
                    COALESCE(SUM(realized_pnl), 0)
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                  AND TO_CHAR((closed_at AT TIME ZONE 'UTC'), 'YYYY-MM') = (
                      SELECT TO_CHAR(MAX(closed_at AT TIME ZONE 'UTC'), 'YYYY-MM')
                      FROM trades
                      WHERE account_id = %s
                        AND closed_at IS NOT NULL
                  )
                GROUP BY trade_day
                ORDER BY trade_day ASC
                """,
                (account_id, account_id),
            )
            daily_rows = cur.fetchall()

            cur.execute(
                """
                SELECT equity
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at ASC
                LIMIT 1
                """,
                (account_id,),
            )
            first_equity_row = cur.fetchone()

    if not month_row:
        return {
            "ok": True,
            "account_id": account_id,
            "monthly_summary": None,
        }

    month_key, pnl, _ = month_row
    pnl_val = float(pnl)

    winning_days = 0
    losing_days = 0
    flat_days = 0
    best_day = None
    worst_day = None

    for _, day_pnl in daily_rows:
        value = float(day_pnl)
        if value > 0:
            winning_days += 1
        elif value < 0:
            losing_days += 1
        else:
            flat_days += 1

        if best_day is None or value > best_day:
            best_day = value
        if worst_day is None or value < worst_day:
            worst_day = value

    base_equity = float(first_equity_row[0]) if first_equity_row else 0.0
    pnl_pct = (pnl_val / base_equity * 100.0) if base_equity > 0 else 0.0

    return {
        "ok": True,
        "account_id": account_id,
        "monthly_summary": {
            "month": month_key,
            "pnl": round(pnl_val, 8),
            "pnl_pct": round(pnl_pct, 4),
            "winning_days": winning_days,
            "losing_days": losing_days,
            "flat_days": flat_days,
            "best_day": round(best_day, 8) if best_day is not None else None,
            "worst_day": round(worst_day, 8) if worst_day is not None else None,
        },
    }


def get_performance_pnl_series(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, equity, realized_pnl, unrealized_pnl
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in reversed(rows):
        items.append({
            "recorded_at": row[0].isoformat().replace("+00:00", "Z"),
            "equity": float(row[1]),
            "realized_pnl": float(row[2]),
            "unrealized_pnl": float(row[3]),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }
