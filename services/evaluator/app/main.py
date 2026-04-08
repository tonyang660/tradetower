from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
import json
import os

import psycopg
import requests


SERVICE_NAME = "evaluator"
PORT = int(os.getenv("PORT", "8080"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "trading_platform")
POSTGRES_USER = os.getenv("POSTGRES_USER", "trading")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "trading")

TRADE_GUARDIAN_BASE_URL = os.getenv("TRADE_GUARDIAN_BASE_URL", "http://trade-guardian:8080")


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_conn():
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        autocommit=True,
    )


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def json_dumps(value):
    return json.dumps(value if value is not None else [])


def fetch_trade_guardian_status(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/status",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_status_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_status_failed")

    return payload, None

def fetch_trade_guardian_open_positions(account_id: int):
    try:
        r = requests.get(
            f"{TRADE_GUARDIAN_BASE_URL}/positions/open",
            params={"account_id": account_id},
            timeout=10
        )
        payload = r.json()
    except Exception as e:
        return None, f"trade_guardian_open_positions_failed: {str(e)}"

    if not payload.get("ok"):
        return None, payload.get("error", "trade_guardian_open_positions_failed")

    return payload.get("positions", []), None

def get_recent_closed_positions(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    trade_id,
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
                FROM trades
                WHERE account_id = %s
                  AND closed_at IS NOT NULL
                ORDER BY closed_at DESC
                LIMIT %s
                """,
                (account_id, limit),
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        trade_id, symbol, side, entry_price, exit_price, size, realized_pnl, fees_paid, opened_at, closed_at = row

        notional = float(entry_price) * float(size) if entry_price is not None and size is not None else 0.0
        pnl_pct = (float(realized_pnl) / notional * 100.0) if notional > 0 else 0.0

        items.append({
            "trade_id": int(trade_id),
            "symbol": symbol,
            "direction": side,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "exit_price": float(exit_price) if exit_price is not None else None,
            "size": float(size) if size is not None else None,
            "notional": round(notional, 8),
            "realized_pnl": float(realized_pnl) if realized_pnl is not None else 0.0,
            "fees_paid": float(fees_paid) if fees_paid is not None else 0.0,
            "pnl_pct": round(pnl_pct, 4),
            "win_loss": "WIN" if float(realized_pnl or 0.0) > 0 else ("LOSS" if float(realized_pnl or 0.0) < 0 else "BREAKEVEN"),
            "opened_at": opened_at.isoformat().replace("+00:00", "Z") if opened_at else None,
            "closed_at": closed_at.isoformat().replace("+00:00", "Z") if closed_at else None,
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }

def upsert_decision_row(cur, row: dict):
    cur.execute(
        """
        INSERT INTO evaluator_decision_history (
            cycle_id,
            account_id,
            symbol,
            candidate_score,
            candidate_bias,
            candidate_reasons_json,
            candidate_sub_scores_json,
            strategy_regime,
            strategy_macro_bias,
            strategy_setup_confidence,
            strategy_decision_confidence,
            best_strategy_candidate,
            best_strategy_score,
            strategy_reason_tags_json,
            final_decision,
            risk_approved,
            guardian_allowed,
            paper_submitted,
            filled
        )
        VALUES (
            %(cycle_id)s,
            %(account_id)s,
            %(symbol)s,
            %(candidate_score)s,
            %(candidate_bias)s,
            %(candidate_reasons_json)s::jsonb,
            %(candidate_sub_scores_json)s::jsonb,
            %(strategy_regime)s,
            %(strategy_macro_bias)s,
            %(strategy_setup_confidence)s,
            %(strategy_decision_confidence)s,
            %(best_strategy_candidate)s,
            %(best_strategy_score)s,
            %(strategy_reason_tags_json)s::jsonb,
            %(final_decision)s,
            %(risk_approved)s,
            %(guardian_allowed)s,
            %(paper_submitted)s,
            %(filled)s
        )
        ON CONFLICT (cycle_id, symbol)
        DO UPDATE SET
            candidate_score = EXCLUDED.candidate_score,
            candidate_bias = EXCLUDED.candidate_bias,
            candidate_reasons_json = EXCLUDED.candidate_reasons_json,
            candidate_sub_scores_json = EXCLUDED.candidate_sub_scores_json,
            strategy_regime = EXCLUDED.strategy_regime,
            strategy_macro_bias = EXCLUDED.strategy_macro_bias,
            strategy_setup_confidence = EXCLUDED.strategy_setup_confidence,
            strategy_decision_confidence = EXCLUDED.strategy_decision_confidence,
            best_strategy_candidate = EXCLUDED.best_strategy_candidate,
            best_strategy_score = EXCLUDED.best_strategy_score,
            strategy_reason_tags_json = EXCLUDED.strategy_reason_tags_json,
            final_decision = EXCLUDED.final_decision,
            risk_approved = EXCLUDED.risk_approved,
            guardian_allowed = EXCLUDED.guardian_allowed,
            paper_submitted = EXCLUDED.paper_submitted,
            filled = EXCLUDED.filled
        """,
        row,
    )


def ingest_cycle_summary(payload: dict):
    cycle_id = payload["cycle_id"]
    account_id = int(payload.get("entry_gate", {}).get("account_id", 1))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_cycle_history (
                    cycle_id,
                    account_id,
                    started_at,
                    completed_at,
                    entry_gate_allowed,
                    enabled_symbols_json,
                    entry_eligible_symbols_json,
                    summary_json
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb
                )
                ON CONFLICT (cycle_id)
                DO UPDATE SET
                    completed_at = EXCLUDED.completed_at,
                    entry_gate_allowed = EXCLUDED.entry_gate_allowed,
                    enabled_symbols_json = EXCLUDED.enabled_symbols_json,
                    entry_eligible_symbols_json = EXCLUDED.entry_eligible_symbols_json,
                    summary_json = EXCLUDED.summary_json
                """,
                (
                    cycle_id,
                    account_id,
                    parse_ts(payload["started_at"]),
                    parse_ts(payload.get("completed_at")),
                    bool(payload.get("entry_gate", {}).get("trade_allowed", False)),
                    json_dumps(payload.get("enabled_symbols", [])),
                    json_dumps(payload.get("entry_eligible_symbols", [])),
                    json.dumps(payload),
                ),
            )

            # Start a symbol map from candidate-filter outputs
            symbol_rows = {}

            candidate_filter = payload.get("candidate_filter", {})
            for item in candidate_filter.get("candidates", []):
                symbol = item["symbol"]
                symbol_rows[symbol] = {
                    "cycle_id": cycle_id,
                    "account_id": account_id,
                    "symbol": symbol,
                    "candidate_score": item.get("score"),
                    "candidate_bias": item.get("bias"),
                    "candidate_reasons_json": json_dumps(item.get("reasons", [])),
                    "candidate_sub_scores_json": json_dumps(item.get("sub_scores", {})),
                    "strategy_regime": None,
                    "strategy_macro_bias": None,
                    "strategy_setup_confidence": None,
                    "strategy_decision_confidence": None,
                    "best_strategy_candidate": None,
                    "best_strategy_score": None,
                    "strategy_reason_tags_json": json_dumps([]),
                    "final_decision": None,
                    "risk_approved": None,
                    "guardian_allowed": None,
                    "paper_submitted": None,
                    "filled": None,
                }

            for item in candidate_filter.get("rejected", []):
                symbol = item["symbol"]
                symbol_rows[symbol] = {
                    "cycle_id": cycle_id,
                    "account_id": account_id,
                    "symbol": symbol,
                    "candidate_score": item.get("score"),
                    "candidate_bias": item.get("bias"),
                    "candidate_reasons_json": json_dumps(item.get("reasons", [])),
                    "candidate_sub_scores_json": json_dumps(item.get("sub_scores", {})),
                    "strategy_regime": None,
                    "strategy_macro_bias": None,
                    "strategy_setup_confidence": None,
                    "strategy_decision_confidence": None,
                    "best_strategy_candidate": None,
                    "best_strategy_score": None,
                    "strategy_reason_tags_json": json_dumps([]),
                    "final_decision": "rejected_by_candidate_filter",
                    "risk_approved": False,
                    "guardian_allowed": False,
                    "paper_submitted": False,
                    "filled": False,
                }

            # Merge strategy engine results
            strategy_results = payload.get("strategy_engine", {}).get("results", [])
            for item in strategy_results:
                symbol = item.get("symbol")
                if not symbol:
                    continue

                if symbol not in symbol_rows:
                    symbol_rows[symbol] = {
                        "cycle_id": cycle_id,
                        "account_id": account_id,
                        "symbol": symbol,
                        "candidate_score": None,
                        "candidate_bias": None,
                        "candidate_reasons_json": json_dumps([]),
                        "candidate_sub_scores_json": json_dumps({}),
                        "strategy_regime": None,
                        "strategy_macro_bias": None,
                        "strategy_setup_confidence": None,
                        "strategy_decision_confidence": None,
                        "best_strategy_candidate": None,
                        "best_strategy_score": None,
                        "strategy_reason_tags_json": json_dumps([]),
                        "final_decision": None,
                        "risk_approved": None,
                        "guardian_allowed": None,
                        "paper_submitted": None,
                        "filled": None,
                    }

                symbol_rows[symbol]["strategy_regime"] = item.get("regime")
                symbol_rows[symbol]["strategy_macro_bias"] = item.get("macro_bias")
                symbol_rows[symbol]["strategy_setup_confidence"] = item.get("setup_confidence")
                symbol_rows[symbol]["strategy_decision_confidence"] = item.get("decision_confidence")
                symbol_rows[symbol]["best_strategy_candidate"] = item.get("best_strategy_candidate")
                symbol_rows[symbol]["best_strategy_score"] = item.get("best_strategy_score")
                symbol_rows[symbol]["strategy_reason_tags_json"] = json_dumps(item.get("reason_tags", []))
                symbol_rows[symbol]["final_decision"] = item.get("decision")

            # Merge risk engine results
            risk_results = payload.get("risk_engine", {}).get("results", [])
            for item in risk_results:
                symbol = item.get("symbol")
                if not symbol or symbol not in symbol_rows:
                    continue
                symbol_rows[symbol]["risk_approved"] = bool(item.get("approved", False))

            # Merge final guardian results
            gate_results = payload.get("final_entry_gate", {}).get("results", [])
            for item in gate_results:
                symbol = item.get("symbol")
                if not symbol or symbol not in symbol_rows:
                    continue
                symbol_rows[symbol]["guardian_allowed"] = bool(item.get("trade_allowed", False))

            # Merge paper execution results
            paper_results = payload.get("paper_execution", {}).get("results", [])
            for item in paper_results:
                symbol = item.get("symbol")
                if not symbol or symbol not in symbol_rows:
                    continue
                symbol_rows[symbol]["paper_submitted"] = True
                symbol_rows[symbol]["filled"] = bool(item.get("filled", False))

            for row in symbol_rows.values():
                upsert_decision_row(cur, row)

    return {"ok": True, "cycle_id": cycle_id, "account_id": account_id}


def ingest_equity_snapshot(payload: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_equity_history (
                    account_id,
                    recorded_at,
                    cash_balance,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    fees_paid_total,
                    trading_enabled,
                    manual_halt,
                    daily_kill_switch,
                    weekly_kill_switch
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    int(payload["account_id"]),
                    parse_ts(payload["recorded_at"]),
                    payload["cash_balance"],
                    payload["equity"],
                    payload["realized_pnl"],
                    payload["unrealized_pnl"],
                    payload["fees_paid_total"],
                    payload["trading_enabled"],
                    payload["manual_halt"],
                    payload["daily_kill_switch"],
                    payload["weekly_kill_switch"],
                ),
            )

    return {"ok": True, "account_id": int(payload["account_id"])}

def build_overview(account_id: int):
    tg_status, tg_error = fetch_trade_guardian_status(account_id)
    if tg_error:
        return None, tg_error

    open_positions, open_positions_error = fetch_trade_guardian_open_positions(account_id)
    if open_positions_error:
        open_positions = []

    recent_positions_payload = get_recent_closed_positions(account_id, 10)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT recorded_at, equity
                FROM evaluator_equity_history
                WHERE account_id = %s
                ORDER BY recorded_at DESC
                LIMIT 100
                """,
                (account_id,),
            )
            equity_rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*)
                FROM evaluator_trade_analytics
                WHERE account_id = %s
                  AND closed_at::date = NOW()::date
                """,
                (account_id,),
            )
            daily_completed_trades = cur.fetchone()[0]

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(realized_pnl), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END), 0)
                FROM evaluator_trade_analytics
                WHERE account_id = %s
                  AND closed_at::date = NOW()::date
                """,
                (account_id,),
            )
            daily_pnl, daily_wins, daily_losses = cur.fetchone()

            cur.execute(
                """
                SELECT cycle_id, started_at, completed_at, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (account_id,),
            )
            latest_cycle = cur.fetchone()

    open_positions_count = len(open_positions)

    equity_series = [
        {
            "recorded_at": row[0].isoformat().replace("+00:00", "Z"),
            "equity": float(row[1]),
        }
        for row in reversed(equity_rows)
    ]

    latest_cycle_payload = None
    if latest_cycle:
        latest_cycle_payload = {
            "cycle_id": latest_cycle[0],
            "started_at": latest_cycle[1].isoformat().replace("+00:00", "Z") if latest_cycle[1] else None,
            "completed_at": latest_cycle[2].isoformat().replace("+00:00", "Z") if latest_cycle[2] else None,
            "summary": latest_cycle[3],
        }

    total_daily_trades = int(daily_wins) + int(daily_losses)
    daily_win_rate = (float(daily_wins) / total_daily_trades * 100.0) if total_daily_trades > 0 else 0.0

    return {
        "ok": True,
        "account_id": account_id,
        "overview_generated_at": iso_now(),
        "account_status": tg_status,
        "equity_series": equity_series,
        "open_positions": open_positions,
        "recent_positions": recent_positions_payload["items"],
        "micro_metrics": {
            "daily_pnl": float(daily_pnl),
            "daily_completed_trades": int(daily_completed_trades),
            "daily_wins": int(daily_wins),
            "daily_losses": int(daily_losses),
            "daily_win_rate": round(daily_win_rate, 2),
            "open_positions_count": open_positions_count,
        },
        "latest_cycle": latest_cycle_payload,
    }, None

def get_equity_history(account_id: int, limit: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    recorded_at,
                    cash_balance,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    fees_paid_total
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
            "cash_balance": float(row[1]),
            "equity": float(row[2]),
            "realized_pnl": float(row[3]),
            "unrealized_pnl": float(row[4]),
            "fees_paid_total": float(row[5]),
        })

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "items": items,
    }


def get_latest_cycle(account_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cycle_id, started_at, completed_at, summary_json
                FROM evaluator_cycle_history
                WHERE account_id = %s
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (account_id,),
            )
            row = cur.fetchone()

    if not row:
        return {
            "ok": True,
            "account_id": account_id,
            "cycle": None,
        }

    return {
        "ok": True,
        "account_id": account_id,
        "cycle": {
            "cycle_id": row[0],
            "started_at": row[1].isoformat().replace("+00:00", "Z") if row[1] else None,
            "completed_at": row[2].isoformat().replace("+00:00", "Z") if row[2] else None,
            "summary": row[3],
        }
    }


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
                FROM evaluator_trade_analytics
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
        }
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "timestamp": iso_now()
            })
            return

        if parsed.path == "/overview":
            account_id = int(query.get("account_id", ["1"])[0])
            payload, error = build_overview(account_id)
            if error:
                self._send_json({
                    "ok": False,
                    "error": error
                }, status=500)
                return
            self._send_json(payload)
            return
        
        if parsed.path == "/positions/open":
            account_id = int(query.get("account_id", ["1"])[0])
            positions, error = fetch_trade_guardian_open_positions(account_id)
            if error:
                self._send_json({
                    "ok": False,
                    "error": error
                }, status=500)
                return

            self._send_json({
                "ok": True,
                "account_id": account_id,
                "count": len(positions),
                "items": positions
            })
            return
        
        if parsed.path == "/positions/recent":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["20"])[0])
            self._send_json(get_recent_closed_positions(account_id, limit))
            return

        if parsed.path == "/equity/history":
            account_id = int(query.get("account_id", ["1"])[0])
            limit = int(query.get("limit", ["100"])[0])
            self._send_json(get_equity_history(account_id, limit))
            return

        if parsed.path == "/cycles/latest":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_latest_cycle(account_id))
            return

        if parsed.path == "/performance/summary":
            account_id = int(query.get("account_id", ["1"])[0])
            self._send_json(get_performance_summary(account_id))
            return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_json({
                "ok": False,
                "error": "invalid_json",
                "details": str(e)
            }, status=400)
            return

        if self.path == "/ingest/cycle-summary":
            try:
                result = ingest_cycle_summary(payload)
                self._send_json(result)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "cycle_ingest_failed",
                    "details": str(e)
                }, status=500)
                return

        if self.path == "/ingest/equity-snapshot":
            try:
                result = ingest_equity_snapshot(payload)
                self._send_json(result)
                return
            except Exception as e:
                self._send_json({
                    "ok": False,
                    "error": "equity_ingest_failed",
                    "details": str(e)
                }, status=500)
                return

        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path
        }, status=404)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()