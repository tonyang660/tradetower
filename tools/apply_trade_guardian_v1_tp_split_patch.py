#!/usr/bin/env python3
"""
TradeTower v1 TP close split patch.

Run from repository root:
    python tools/apply_trade_guardian_v1_tp_split_patch.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Patch anchor not found for {label}")
    return text.replace(old, new)


def patch_paper_execution() -> None:
    path = "services/paper-execution/app/main.py"
    text = read(path)

    helper = '''

def get_tp_close_percent(payload: dict, key: str, default: float) -> float:
    """Read TP close percent from flattened or nested Strategy/Risk payload."""
    flat_key = f"{key}_close_percent"
    if payload.get(flat_key) is not None:
        return float(payload[flat_key])

    take_profits = payload.get("take_profits") or {}
    if isinstance(take_profits, dict):
        item = take_profits.get(key) or {}
        if isinstance(item, dict) and item.get("close_percent") is not None:
            return float(item["close_percent"])

    return float(default)
'''
    if "def get_tp_close_percent(" not in text:
        text = must_replace(
            text,
            "def calc_fee(notional: float, fee_pct: float) -> float:\n    return notional * (fee_pct / 100.0)\n",
            "def calc_fee(notional: float, fee_pct: float) -> float:\n    return notional * (fee_pct / 100.0)\n" + helper,
            "paper_execution_add_tp_close_helper",
        )

    old = '        "tp3_price": float(payload["tp3_price"]),\n        "risk_amount": float(payload["risk_amount"]),'
    new = '        "tp3_price": float(payload["tp3_price"]),\n        "tp1_close_percent": get_tp_close_percent(payload, "tp1", 50),\n        "tp2_close_percent": get_tp_close_percent(payload, "tp2", 30),\n        "tp3_close_percent": get_tp_close_percent(payload, "tp3", 20),\n        "risk_amount": float(payload["risk_amount"]),'
    if '"tp1_close_percent": get_tp_close_percent(payload, "tp1", 50)' not in text:
        count = text.count(old)
        if count < 2:
            raise RuntimeError(f"Expected at least 2 paper execution ENTRY anchors, found {count}")
        text = text.replace(old, new)

    write(path, text)


def patch_orders() -> None:
    path = "services/trade-guardian/app/orders.py"
    text = read(path)

    if "import os" not in text.split("\n")[:10]:
        text = must_replace(text, "import json\n", "import json\nimport os\n", "orders_import_os")

    constants = '''
DEFAULT_TP1_CLOSE_PERCENT = float(os.getenv("TP1_CLOSE_PERCENT", "50"))
DEFAULT_TP2_CLOSE_PERCENT = float(os.getenv("TP2_CLOSE_PERCENT", "30"))
DEFAULT_TP3_CLOSE_PERCENT = float(os.getenv("TP3_CLOSE_PERCENT", "20"))


def normalize_tp_close_percents(
    tp1_close_percent: float | None = None,
    tp2_close_percent: float | None = None,
    tp3_close_percent: float | None = None,
) -> tuple[float, float, float]:
    """Return validated TP close percentages. Defaults are v1 50/30/20."""
    p1 = DEFAULT_TP1_CLOSE_PERCENT if tp1_close_percent is None else float(tp1_close_percent)
    p2 = DEFAULT_TP2_CLOSE_PERCENT if tp2_close_percent is None else float(tp2_close_percent)
    p3 = DEFAULT_TP3_CLOSE_PERCENT if tp3_close_percent is None else float(tp3_close_percent)

    if p1 <= 0 or p2 <= 0 or p3 <= 0:
        raise ValueError("tp_close_percent_must_be_positive")

    total = p1 + p2 + p3
    if abs(total - 100.0) > 0.000001:
        raise ValueError(f"tp_close_percent_total_must_equal_100: {total}")

    return p1, p2, p3


def build_tp_close_sizes(
    original_size: float,
    tp1_close_percent: float | None = None,
    tp2_close_percent: float | None = None,
    tp3_close_percent: float | None = None,
) -> dict:
    p1, p2, p3 = normalize_tp_close_percents(
        tp1_close_percent,
        tp2_close_percent,
        tp3_close_percent,
    )

    tp1_size = round(original_size * (p1 / 100.0), 8)
    tp2_size = round(original_size * (p2 / 100.0), 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)

    return {
        "tp1_size": tp1_size,
        "tp2_size": tp2_size,
        "tp3_size": tp3_size,
        "tp1_close_percent": p1,
        "tp2_close_percent": p2,
        "tp3_close_percent": p3,
    }
'''
    if "DEFAULT_TP1_CLOSE_PERCENT" not in text:
        text = must_replace(text, "from db import get_conn\n", "from db import get_conn\n" + constants, "orders_add_tp_policy")

    text = must_replace(
        text,
        '''def create_protective_orders_for_position(
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):''',
        '''def create_protective_orders_for_position(
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
    tp1_close_percent: float | None = None,
    tp2_close_percent: float | None = None,
    tp3_close_percent: float | None = None,
):''',
        "orders_protective_signature",
    )

    text = must_replace(
        text,
        '''    tp1_size = round(original_size * 0.40, 8)
    tp2_size = round(original_size * 0.40, 8)
    tp3_size = round(max(original_size - tp1_size - tp2_size, 0.0), 8)''',
        '''    close_plan = build_tp_close_sizes(
        original_size,
        tp1_close_percent,
        tp2_close_percent,
        tp3_close_percent,
    )
    tp1_size = close_plan["tp1_size"]
    tp2_size = close_plan["tp2_size"]
    tp3_size = close_plan["tp3_size"]''',
        "orders_protective_sizes",
    )

    text = must_replace(
        text,
        '''def create_protective_orders_for_position_tx(
    cur,
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
):''',
        '''def create_protective_orders_for_position_tx(
    cur,
    account_id: int,
    symbol: str,
    position_side: str,
    original_size: float,
    stop_loss: float,
    tp1_price: float,
    tp2_price: float,
    tp3_price: float,
    linked_position_id: int,
    tp1_close_percent: float | None = None,
    tp2_close_percent: float | None = None,
    tp3_close_percent: float | None = None,
):''',
        "orders_protective_tx_signature",
    )

    write(path, text)


def patch_execution() -> None:
    path = "services/trade-guardian/app/execution.py"
    text = read(path)

    if "import os" not in text.split("\n")[:10]:
        text = "import os\n" + text

    helper = '''
DEFAULT_TP1_CLOSE_PERCENT = float(os.getenv("TP1_CLOSE_PERCENT", "50"))
DEFAULT_TP2_CLOSE_PERCENT = float(os.getenv("TP2_CLOSE_PERCENT", "30"))
DEFAULT_TP3_CLOSE_PERCENT = float(os.getenv("TP3_CLOSE_PERCENT", "20"))


def payload_float(payload: dict, key: str, default: float | None = None):
    value = payload.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def tp_close_size_from_payload(payload: dict, open_position: dict, remaining_size: float, default_percent: float) -> float:
    """Use execution fill size first; fallback to configured percent of original."""
    explicit_size = payload_float(payload, "filled_size", None)
    if explicit_size is not None and explicit_size > 0:
        return round(min(explicit_size, remaining_size), 8)

    original_size = float(open_position["original_size"])
    fallback = round(original_size * (default_percent / 100.0), 8)
    return round(min(fallback, remaining_size), 8)
'''
    if "def tp_close_size_from_payload(" not in text:
        text = must_replace(text, "from db import get_conn\n", "from db import get_conn\n" + helper, "execution_add_tp_helpers")

    text = must_replace(
        text,
        '''                    protective_orders = create_protective_orders_for_position_tx(
                        cur=cur,
                        account_id=account_id,
                        symbol=symbol,
                        position_side=position_side,
                        original_size=filled_size,
                        stop_loss=stop_loss,
                        tp1_price=tp1_price,
                        tp2_price=tp2_price,
                        tp3_price=tp3_price,
                        linked_position_id=position_id,
                    )''',
        '''                    protective_orders = create_protective_orders_for_position_tx(
                        cur=cur,
                        account_id=account_id,
                        symbol=symbol,
                        position_side=position_side,
                        original_size=filled_size,
                        stop_loss=stop_loss,
                        tp1_price=tp1_price,
                        tp2_price=tp2_price,
                        tp3_price=tp3_price,
                        linked_position_id=position_id,
                        tp1_close_percent=payload_float(payload, "tp1_close_percent", None),
                        tp2_close_percent=payload_float(payload, "tp2_close_percent", None),
                        tp3_close_percent=payload_float(payload, "tp3_close_percent", None),
                    )''',
        "execution_pass_close_percents",
    )

    text = must_replace(
        text,
        '''        close_size = round(original_size * 0.40, 8)
        if close_size > remaining_size:
            close_size = remaining_size''',
        '''        close_size = tp_close_size_from_payload(
            payload,
            open_position,
            remaining_size,
            DEFAULT_TP1_CLOSE_PERCENT,
        )''',
        "execution_tp1_close_size",
    )

    text = must_replace(
        text,
        '''        close_size = round(original_size * 0.40, 8)
        if close_size > remaining_size:
            close_size = remaining_size''',
        '''        close_size = tp_close_size_from_payload(
            payload,
            open_position,
            remaining_size,
            DEFAULT_TP2_CLOSE_PERCENT,
        )''',
        "execution_tp2_close_size",
    )

    write(path, text)


def main() -> int:
    patch_paper_execution()
    patch_orders()
    patch_execution()
    print("Applied Trade Guardian v1 TP close split patch: 50/30/20 configurable defaults.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
