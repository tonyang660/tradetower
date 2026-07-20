import json
import time

from config import (
    ACCOUNT_ID,
    LOOP_INTERVAL_SECONDS,
    MAINTENANCE_LOOP_INTERVAL_SECONDS,
    PENDING_ENTRY_LOOP_INTERVAL_SECONDS,
    PENDING_EXIT_LOOP_INTERVAL_SECONDS,
)
from cycle import run_one_cycle
from maintenance import process_open_position_maintenance_once
from pending_entries import process_pending_entries_once
from pending_exits import process_pending_exits_once
import state
from accounts import account_ids_for_entry_work, account_ids_for_exit_and_maintenance, PHASE8_SCHEDULER_ACCOUNTS_VERSION
from time_utils import iso_now


def pending_entry_loop():
    while True:
        try:
            if state.AUTO_LOOP_ENABLED_STATE:
                account_ids, accounts_error = account_ids_for_entry_work(ACCOUNT_ID)
                aggregate = {
                    "ok": accounts_error is None,
                    "timestamp": iso_now(),
                    "account_ids": account_ids,
                    "processed": 0,
                    "fills": 0,
                    "pending": 0,
                    "cancelled": 0,
                    "blocked": 0,
                    "errors": 0,
                    "results": [],
                    "accounts_error": accounts_error,
                    "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                }
                for account_id in account_ids:
                    result = process_pending_entries_once(account_id=account_id)
                    aggregate["processed"] += int(result.get("processed", 0))
                    aggregate["fills"] += int(result.get("fills", 0))
                    aggregate["pending"] += int(result.get("pending", 0))
                    aggregate["cancelled"] += int(result.get("cancelled", 0))
                    aggregate["blocked"] += int(result.get("blocked", 0))
                    aggregate["errors"] += int(result.get("errors", 0))
                    aggregate["results"].append(result)
                state.LAST_PENDING_ENTRY_LOOP_RESULT.update(aggregate)
                print(json.dumps({
                    "event": "PENDING_ENTRY_LOOP_COMPLETED",
                    "accounts": account_ids,
                    "processed": aggregate["processed"],
                    "timestamp": aggregate["timestamp"],
                }))
        except Exception as e:
            print(json.dumps({
                "event": "PENDING_ENTRY_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(PENDING_ENTRY_LOOP_INTERVAL_SECONDS)

def pending_exit_loop():
    while True:
        try:
            if state.AUTO_LOOP_ENABLED_STATE:
                account_ids, accounts_error = account_ids_for_exit_and_maintenance(ACCOUNT_ID)
                aggregate = {
                    "ok": accounts_error is None,
                    "timestamp": iso_now(),
                    "account_ids": account_ids,
                    "processed": 0,
                    "filled": 0,
                    "pending": 0,
                    "forced_market": 0,
                    "errors": 0,
                    "results": [],
                    "accounts_error": accounts_error,
                    "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                }
                for account_id in account_ids:
                    result = process_pending_exits_once(account_id=account_id)
                    aggregate["processed"] += int(result.get("processed", 0))
                    aggregate["filled"] += int(result.get("filled", 0))
                    aggregate["pending"] += int(result.get("pending", 0))
                    aggregate["forced_market"] += int(result.get("forced_market", 0))
                    aggregate["errors"] += int(result.get("errors", 0))
                    aggregate["results"].append(result)
                state.LAST_PENDING_EXIT_LOOP_RESULT.update(aggregate)
                print(json.dumps({
                    "event": "PENDING_EXIT_LOOP_COMPLETED",
                    "accounts": account_ids,
                    "processed": aggregate["processed"],
                    "filled": aggregate["filled"],
                    "timestamp": aggregate["timestamp"],
                }))
        except Exception as e:
            print(json.dumps({
                "event": "PENDING_EXIT_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(PENDING_EXIT_LOOP_INTERVAL_SECONDS)

def open_position_maintenance_loop():
    while True:
        try:
            if state.AUTO_LOOP_ENABLED_STATE:
                account_ids, accounts_error = account_ids_for_exit_and_maintenance(ACCOUNT_ID)
                aggregate = {
                    "ok": accounts_error is None,
                    "timestamp": iso_now(),
                    "account_ids": account_ids,
                    "checked": 0,
                    "actions_triggered": 0,
                    "no_action": 0,
                    "blocked": 0,
                    "errors": 0,
                    "results": [],
                    "accounts_error": accounts_error,
                    "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                }
                for account_id in account_ids:
                    result = process_open_position_maintenance_once(account_id=account_id)
                    aggregate["checked"] += int(result.get("checked", 0))
                    aggregate["actions_triggered"] += int(result.get("actions_triggered", 0))
                    aggregate["no_action"] += int(result.get("no_action", 0))
                    aggregate["blocked"] += int(result.get("blocked", 0))
                    aggregate["errors"] += int(result.get("errors", 0))
                    aggregate["results"].append(result)
                state.LAST_MAINTENANCE_LOOP_RESULT.update(aggregate)
                print(json.dumps({
                    "event": "MAINTENANCE_LOOP_COMPLETED",
                    "accounts": account_ids,
                    "checked": aggregate.get("checked", 0),
                    "actions_triggered": aggregate.get("actions_triggered", 0),
                    "timestamp": aggregate.get("timestamp"),
                }))
        except Exception as e:
            print(json.dumps({
                "event": "MAINTENANCE_LOOP_FAILED",
                "error": str(e),
                "timestamp": iso_now(),
            }))

        time.sleep(MAINTENANCE_LOOP_INTERVAL_SECONDS)

def scheduler_loop():
    while True:
        if state.AUTO_LOOP_ENABLED_STATE:
            try:
                account_ids, accounts_error = account_ids_for_entry_work(ACCOUNT_ID)
                for account_id in account_ids:
                    result = run_one_cycle(account_id=account_id)
                    print(json.dumps({
                        "event": "CYCLE_COMPLETED",
                        "account_id": account_id,
                        "cycle_id": result["cycle_id"],
                        "ok": result["ok"],
                        "completed_at": result["completed_at"],
                        "accounts_error": accounts_error,
                        "phase8_scheduler_accounts_version": PHASE8_SCHEDULER_ACCOUNTS_VERSION,
                    }))
            except Exception as e:
                print(json.dumps({
                    "event": "CYCLE_FAILED",
                    "error": str(e),
                }))
        time.sleep(LOOP_INTERVAL_SECONDS)
