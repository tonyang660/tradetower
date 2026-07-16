import json

from db import get_conn
from json_utils import json_dumps
from time_utils import parse_ts

from cycle_summary_v2 import normalize_cycle_summary_events
from event_store import store_evaluator_events


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


def apply_pending_entry_event(payload: dict):
    account_id = int(payload["account_id"])
    cycle_id = payload.get("cycle_id")
    symbol = str(payload["symbol"]).upper()
    event_type = str(payload.get("event_type", "")).upper()
    attempt_number = int(payload.get("attempt_number", 0))
    source = payload.get("source", "pending_entry_loop")
    details = payload.get("details", {})

    if not cycle_id:
        return {
            "ok": False,
            "error": "missing_cycle_id",
        }

    with get_conn() as conn:
        with conn.cursor() as cur:
            if event_type == "ENTRY_FILLED":
                cur.execute(
                    """
                    UPDATE evaluator_decision_history
                    SET paper_submitted = TRUE,
                        filled = TRUE
                    WHERE cycle_id = %s
                      AND account_id = %s
                      AND symbol = %s
                    """,
                    (cycle_id, account_id, symbol),
                )

            elif event_type == "ENTRY_PENDING":
                cur.execute(
                    """
                    UPDATE evaluator_decision_history
                    SET paper_submitted = TRUE
                    WHERE cycle_id = %s
                      AND account_id = %s
                      AND symbol = %s
                    """,
                    (cycle_id, account_id, symbol),
                )

            elif event_type in ("ENTRY_BLOCKED", "ENTRY_CANCELLED", "CANCELLED_RISK_REJECTED"):
                cur.execute(
                    """
                    UPDATE evaluator_decision_history
                    SET paper_submitted = COALESCE(paper_submitted, FALSE),
                        filled = FALSE
                    WHERE cycle_id = %s
                      AND account_id = %s
                      AND symbol = %s
                    """,
                    (cycle_id, account_id, symbol),
                )

    return {
        "ok": True,
        "account_id": account_id,
        "cycle_id": cycle_id,
        "symbol": symbol,
        "event_type": event_type,
        "attempt_number": attempt_number,
        "source": source,
    }


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

            normalized_events = normalize_cycle_summary_events(payload)
            normalized_event_count = store_evaluator_events(cur, normalized_events)

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
                execution_event = item.get("execution_event", {}) if isinstance(item, dict) else {}

                symbol = item.get("symbol") or execution_event.get("symbol")
                if not symbol:
                    continue

                symbol = str(symbol).upper()

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

                action = str(item.get("action", "")).upper()

                symbol_rows[symbol]["paper_submitted"] = True
                symbol_rows[symbol]["filled"] = action == "ENTRY_FILLED"

            for row in symbol_rows.values():
                upsert_decision_row(cur, row)

    return {
        "ok": True,
        "cycle_id": cycle_id,
        "account_id": account_id,
        "event_model_version": "phase7_step1_evaluator_event_model_v2",
        "cycle_summary_ingestion_version": "phase7_step2_cycle_summary_ingestion_v2",
        "normalized_event_count": normalized_event_count,
    }


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
