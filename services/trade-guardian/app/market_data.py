import requests

from config import API_GATEWAY_BASE_URL, API_GATEWAY_LATEST_PRICE_PATH
from guardian_state import evaluate_and_refresh_guardian_state, fetch_guardian_status
from positions import fetch_all_open_positions
from db import get_conn


def fetch_latest_price(symbol: str):
    try:
        r = requests.get(
            f"{API_GATEWAY_BASE_URL}{API_GATEWAY_LATEST_PRICE_PATH}",
            params={"symbol": symbol},
            timeout=10,
        )
        payload = r.json()
    except Exception as e:
        return None, f"latest_price_request_failed: {str(e)}"

    if not payload.get("ok", False):
        return None, payload.get("error", "latest_price_fetch_failed")

    # Prefer mark price if present, otherwise fall back to last traded price.
    price = payload.get("mark_price")
    if price is None:
        price = payload.get("last_price")

    if price is None:
        return None, "latest_price_missing_in_response"

    return float(price), None


def calculate_unrealized_pnl(position_side: str, entry_price: float, current_price: float, remaining_size: float) -> float:
    if position_side == "long":
        return (current_price - entry_price) * remaining_size
    if position_side == "short":
        return (entry_price - current_price) * remaining_size
    raise ValueError("unsupported_position_side")


def update_account_mark_to_market(account_id: int, unrealized_pnl: float, reserved_margin_total: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE account_balances
                SET unrealized_pnl = %s,
                    equity = cash_balance + %s + %s,
                    updated_at = NOW()
                WHERE account_id = %s
                """,
                (unrealized_pnl, reserved_margin_total, unrealized_pnl, account_id),
            )
        conn.commit()


def refresh_mark_to_market(account_id: int):
    positions = fetch_all_open_positions(account_id)

    enriched_positions = []
    total_unrealized_pnl = 0.0
    reserved_margin_total = 0.0
    pricing_errors = []

    for pos in positions:
        symbol = pos["symbol"]
        current_price, price_error = fetch_latest_price(symbol)

        if price_error:
            pricing_errors.append({
                "symbol": symbol,
                "error": price_error,
            })
            continue

        remaining_size = float(pos["remaining_size"])
        entry_price = float(pos["entry_price"])
        side = pos["side"]

        unrealized_pnl = calculate_unrealized_pnl(
            side,
            entry_price,
            current_price,
            remaining_size,
        )

        notional = entry_price * remaining_size
        pnl_pct = (unrealized_pnl / notional * 100.0) if notional > 0 else 0.0

        total_unrealized_pnl += unrealized_pnl
        reserved_margin_total += float(pos.get("margin_used", 0.0) or 0.0)

        enriched_positions.append({
            **pos,
            "current_price": round(current_price, 8),
            "unrealized_pnl": round(unrealized_pnl, 8),
            "unrealized_pnl_pct": round(pnl_pct, 4),
            "notional": round(notional, 8),
        })

    update_account_mark_to_market(account_id, total_unrealized_pnl, reserved_margin_total)

    refreshed_status = fetch_guardian_status(account_id)
    if refreshed_status:
        refreshed_status = evaluate_and_refresh_guardian_state(refreshed_status)

    return {
        "ok": True,
        "account_id": account_id,
        "positions_checked": len(positions),
        "positions_priced": len(enriched_positions),
        "pricing_errors": pricing_errors,
        "total_unrealized_pnl": round(total_unrealized_pnl, 8),
        "positions": enriched_positions,
        "account_status": refreshed_status,
    }
