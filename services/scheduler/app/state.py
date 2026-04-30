from config import AUTO_LOOP_DEFAULT

AUTO_LOOP_ENABLED_STATE = AUTO_LOOP_DEFAULT

PENDING_ENTRY_ORDERS = {}
LAST_PENDING_ENTRY_LOOP_RESULT = {
    "timestamp": None,
    "processed": 0,
    "fills": 0,
    "pending": 0,
    "cancelled": 0,
    "blocked": 0,
    "errors": 0,
    "results": [],
}

LAST_MAINTENANCE_LOOP_RESULT = {
    "timestamp": None,
    "checked": 0,
    "actions_triggered": 0,
    "no_action": 0,
    "blocked": 0,
    "errors": 0,
    "results": [],
}

PENDING_EXIT_ORDERS = {}
LAST_PENDING_EXIT_LOOP_RESULT = {
    "timestamp": None,
    "processed": 0,
    "filled": 0,
    "pending": 0,
    "forced_market": 0,
    "errors": 0,
    "results": [],
}
