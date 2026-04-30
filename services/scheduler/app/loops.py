import json
import time

from config import (
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
from time_utils import iso_now


def pending_entry_loop():
    while True:
        try:
            if state.AUTO_LOOP_ENABLED_STATE and len(state.PENDING_ENTRY_ORDERS) > 0:
                result = process_pending_entries_once()
                print(json.dumps({
                    "event": "PENDING_ENTRY_LOOP_COMPLETED",
                    "processed": result["processed"],
                    "timestamp": result["timestamp"],
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
            if state.AUTO_LOOP_ENABLED_STATE and len(state.PENDING_EXIT_ORDERS) > 0:
                result = process_pending_exits_once()
                print(json.dumps({
                    "event": "PENDING_EXIT_LOOP_COMPLETED",
                    "processed": result["processed"],
                    "filled": result["filled"],
                    "timestamp": result["timestamp"],
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
                result = process_open_position_maintenance_once()
                print(json.dumps({
                    "event": "MAINTENANCE_LOOP_COMPLETED",
                    "checked": result.get("checked", 0),
                    "actions_triggered": result.get("actions_triggered", 0),
                    "timestamp": result.get("timestamp"),
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
                result = run_one_cycle()
                print(json.dumps({
                    "event": "CYCLE_COMPLETED",
                    "cycle_id": result["cycle_id"],
                    "ok": result["ok"],
                    "completed_at": result["completed_at"],
                }))
            except Exception as e:
                print(json.dumps({
                    "event": "CYCLE_FAILED",
                    "error": str(e),
                }))
        time.sleep(LOOP_INTERVAL_SECONDS)
