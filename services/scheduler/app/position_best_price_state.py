from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

POSITION_BEST_PRICE_STATE_VERSION = "phase6_step11_position_best_price_state"

STATE_PATH = Path(os.getenv(
    "POSITION_BEST_PRICE_STATE_PATH",
    "/tmp/tradetower_position_best_prices.json",
))


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _key(account_id: int, symbol: str, position_id: int | None = None) -> str:
    suffix = str(position_id) if position_id is not None else "unknown"
    return f"{int(account_id)}:{str(symbol).upper()}:{suffix}"


def update_best_price_for_position(
    *,
    account_id: int,
    position: dict[str, Any],
    current_price: float,
) -> dict[str, Any]:
    state = _load_state()

    symbol = str(position.get("symbol", "")).upper()
    position_id = position.get("position_id")
    side = str(position.get("side") or position.get("position_side") or "").lower()
    entry_price = float(position.get("entry_price") or current_price)

    key = _key(account_id, symbol, int(position_id) if position_id is not None else None)
    existing = state.get(key, {})

    previous_best = existing.get("best_price")
    if previous_best is None:
        previous_best = entry_price

    previous_best = float(previous_best)
    current = float(current_price)

    if side == "long":
        best = max(previous_best, entry_price, current)
    elif side == "short":
        best = min(previous_best, entry_price, current)
    else:
        best = current

    record = {
        "position_best_price_state_version": POSITION_BEST_PRICE_STATE_VERSION,
        "account_id": int(account_id),
        "symbol": symbol,
        "position_id": position_id,
        "side": side,
        "entry_price": entry_price,
        "best_price": best,
        "previous_best_price": previous_best,
        "current_price": current,
    }
    state[key] = record
    _save_state(state)
    return record


def prune_best_price_state(open_positions: list[dict[str, Any]], account_id: int) -> None:
    state = _load_state()
    open_keys = {
        _key(
            account_id,
            str(position.get("symbol", "")).upper(),
            int(position["position_id"]) if position.get("position_id") is not None else None,
        )
        for position in open_positions
    }

    changed = False
    for key in list(state.keys()):
        if key.startswith(f"{int(account_id)}:") and key not in open_keys:
            state.pop(key, None)
            changed = True

    if changed:
        _save_state(state)
