from balances import apply_entry_balance_update_tx, apply_exit_balance_update
from execution_reports import insert_execution_report, insert_execution_report_tx
from guardian_state import insert_guardian_event, insert_guardian_event_tx
from orders import (
    cancel_open_protective_orders_for_position,
    apply_order_fill,
    apply_order_fill_tx,
    create_protective_orders_for_position_tx,
    finalize_position_closing_order,
    resize_stop_order_for_position,
    reconcile_stop_protection_for_position,
    get_order_role,
)
from position_events import (
    record_position_event,
    record_position_event_tx,
)
from positions import (
    calculate_realized_pnl,
    close_position,
    create_open_position_tx,
    get_open_position,
    update_position_after_partial_exit,
)
from trades import maybe_finalize_trade
from db import get_conn

from partial_close_policy import build_partial_close_accounting

import os

TP1_CLOSE_PERCENT_DEFAULT = float(os.getenv("TP1_CLOSE_PERCENT", "50"))
TP2_CLOSE_PERCENT_DEFAULT = float(os.getenv("TP2_CLOSE_PERCENT", "30"))
TP3_CLOSE_PERCENT_DEFAULT = float(os.getenv("TP3_CLOSE_PERCENT", "20"))



def derive_entry_atr_from_entry_payload(payload: dict, entry_price: float, stop_loss: float) -> float | None:
    for key in ("entry_atr", "atr_at_entry", "opening_atr", "initial_atr"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            value = float(value)
            if value > 0:
                return value
        except Exception:
            pass

    try:
        risk_per_unit = abs(float(entry_price) - float(stop_loss))
        if risk_per_unit > 0:
            return round(risk_per_unit / 2.5, 8)
    except Exception:
        pass

    return None

def get_tp_close_percent(payload: dict, key: str, default: float) -> float:
    try:
        value = payload.get(f"{key}_close_percent")
        if value is not None:
            return float(value)
    except Exception:
        pass

    return float(default)


def apply_execution_report(payload: dict):
    account_id = int(payload["account_id"])
    symbol = payload["symbol"].upper()
    position_side = payload["position_side"].lower()
    execution_type = payload["execution_type"].upper()
    order_type = payload["order_type"].lower()
    fill_price = float(payload["fill_price"])
    filled_size = float(payload["filled_size"])
    fee_paid = float(payload.get("fee_paid", 0))
    slippage_bps = float(payload.get("slippage_bps", 0))
    notes = payload.get("notes")
    order_id = payload.get("order_id")

    if position_side not in ("long", "short"):
        return {"ok": False, "error": "unsupported_position_side"}

    if execution_type not in ("ENTRY", "TP1", "TP2", "TP3", "STOP_LOSS"):
        return {"ok": False, "error": "unsupported_execution_type"}

    if order_type not in ("market", "limit"):
        return {"ok": False, "error": "unsupported_order_type"}

    execution_id = None
    open_position = get_open_position(account_id, symbol)

    # ENTRY
    if execution_type == "ENTRY":
        if open_position is not None:
            return {
                "ok": False,
                "error": "position_already_open",
            }

        stop_loss = float(payload["stop_loss"])
        tp1_price = float(payload["tp1_price"])
        tp2_price = float(payload["tp2_price"])
        tp3_price = float(payload["tp3_price"])
        tp1_close_percent = get_tp_close_percent(payload, "tp1", TP1_CLOSE_PERCENT_DEFAULT)
        tp2_close_percent = get_tp_close_percent(payload, "tp2", TP2_CLOSE_PERCENT_DEFAULT)
        tp3_close_percent = get_tp_close_percent(payload, "tp3", TP3_CLOSE_PERCENT_DEFAULT)
        risk_amount = float(payload["risk_amount"])
        leverage = float(payload.get("leverage", 1.0))
        entry_atr = derive_entry_atr_from_entry_payload(payload, fill_price, stop_loss)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    execution_id = insert_execution_report_tx(
                        cur=cur,
                        account_id=account_id,
                        order_id=order_id,
                        symbol=symbol,
                        fill_price=fill_price,
                        filled_size=filled_size,
                        fee_paid=fee_paid,
                        slippage_bps=slippage_bps,
                        notes=notes,
                        execution_type=execution_type,
                        position_side=position_side,
                    )

                    if order_id is not None:
                        order_fill = apply_order_fill_tx(
                            cur=cur,
                            order_id=int(order_id),
                            fill_size=filled_size,
                            fill_price=fill_price,
                        )
                        if order_fill is None:
                            raise ValueError("entry_order_not_found")

                    position_id, position_margin_used = create_open_position_tx(
                        cur=cur,
                        account_id=account_id,
                        symbol=symbol,
                        position_side=position_side,
                        size=filled_size,
                        entry_price=fill_price,
                        leverage=leverage,
                        stop_loss=stop_loss,
                        tp1_price=tp1_price,
                        tp2_price=tp2_price,
                        tp3_price=tp3_price,
                        risk_amount=risk_amount,
                        entry_atr=entry_atr,
                    )

                    protective_orders = create_protective_orders_for_position_tx(
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
                        tp1_close_percent=tp1_close_percent,
                        tp2_close_percent=tp2_close_percent,
                        tp3_close_percent=tp3_close_percent,
                    )

                    apply_entry_balance_update_tx(
                        cur=cur,
                        account_id=account_id,
                        margin_used=position_margin_used,
                        fee_paid=fee_paid,
                    )

                    record_position_event_tx(
                        cur=cur,
                        position_id=position_id,
                        account_id=account_id,
                        event_type="POSITION_OPENED",
                        order_id=(
                            int(order_id)
                            if order_id is not None
                            else None
                        ),
                        execution_id=execution_id,
                        price=fill_price,
                        size_before=0,
                        size_delta=filled_size,
                        size_after=filled_size,
                        details={
                            "symbol": symbol,
                            "position_side": position_side,
                            "fee_paid": fee_paid,
                            "risk_amount": risk_amount,
                            "leverage": leverage,
                            "entry_atr": entry_atr,
                            "stop_loss": stop_loss,
                            "tp1_price": tp1_price,
                            "tp2_price": tp2_price,
                            "tp3_price": tp3_price,
                            "protective_orders": protective_orders,
                        },
                    )

                    insert_guardian_event_tx(
                        cur=cur,
                        account_id=account_id,
                        event_type="POSITION_OPENED",
                        reason_code="ENTRY_FILLED",
                        details={
                            "symbol": symbol,
                            "position_id": position_id,
                            "execution_id": execution_id,
                            "position_side": position_side,
                            "fill_price": fill_price,
                            "filled_size": filled_size,
                            "fee_paid": fee_paid,
                            "execution_type": execution_type,
                            "order_type": order_type,
                            "risk_amount": risk_amount,
                            "stop_loss": stop_loss,
                            "tp1_price": tp1_price,
                            "tp2_price": tp2_price,
                            "tp3_price": tp3_price,
                            "protective_orders": protective_orders,
                        },
                    )

                conn.commit()

            return {
                "ok": True,
                "action": "position_opened",
                "execution_id": execution_id,
                "position_id": position_id,
                "protective_orders": protective_orders,
            }

        except Exception as e:
            return {
                "ok": False,
                "error": "entry_apply_failed",
                "details": str(e),
            }

    # Maintenance actions below must have an open position
    if open_position is None:
        return {
            "ok": False,
            "error": "no_open_position",
            "execution_id": execution_id,
        }

    original_size = open_position["original_size"]
    remaining_size = open_position["remaining_size"]

    if execution_type == "TP1":
        if open_position["tp1_hit"]:
            return {"ok": False, "error": "tp1_already_hit", "execution_id": execution_id}

        accounting = build_partial_close_accounting(
            execution_type="TP1",
            original_size=original_size,
            remaining_size_before=remaining_size,
            margin_used_before=open_position["margin_used"],
            close_percent=TP1_CLOSE_PERCENT_DEFAULT,
        )

        close_size = accounting["close_size"]
        released_margin = accounting["released_margin"]
        new_remaining = accounting["remaining_size_after"]
        new_remaining_margin = accounting["remaining_margin_after"]

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side,
        )

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)

        update_position_after_partial_exit(
            open_position["position_id"],
            new_remaining,
            new_remaining_margin,
            tp1_hit=True,
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            apply_order_fill(
                order_id=int(order_id),
                fill_size=close_size,
                fill_price=fill_price,
            )

        resize_stop_order_for_position(
            open_position["position_id"],
            new_remaining,
        )

        record_position_event(
            position_id=open_position["position_id"],
            account_id=account_id,
            event_type="TP1_FILLED",
            order_id=(
                int(order_id)
                if order_id is not None
                else None
            ),
            execution_id=execution_id,
            price=fill_price,
            size_before=remaining_size,
            size_delta=-close_size,
            size_after=new_remaining,
            details={
                "symbol": symbol,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        insert_guardian_event(
            account_id,
            "TP1_HIT",
            "TAKE_PROFIT_1",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": new_remaining,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        return {
            "ok": True,
            "action": "tp1_applied",
            "execution_id": execution_id,
            "realized_pnl": realized_pnl,
            "remaining_size": new_remaining,
        }

    if execution_type == "TP2":
        if not open_position["tp1_hit"]:
            return {"ok": False, "error": "tp1_not_hit_yet", "execution_id": execution_id}
        if open_position["tp2_hit"]:
            return {"ok": False, "error": "tp2_already_hit", "execution_id": execution_id}

        accounting = build_partial_close_accounting(
            execution_type="TP2",
            original_size=original_size,
            remaining_size_before=remaining_size,
            margin_used_before=open_position["margin_used"],
            close_percent=TP2_CLOSE_PERCENT_DEFAULT,
        )

        close_size = accounting["close_size"]
        released_margin = accounting["released_margin"]
        new_remaining = accounting["remaining_size_after"]
        new_remaining_margin = accounting["remaining_margin_after"]

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side,
        )

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)

        update_position_after_partial_exit(
            open_position["position_id"],
            new_remaining,
            new_remaining_margin,
            tp2_hit=True,
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            apply_order_fill(
                order_id=int(order_id),
                fill_size=close_size,
                fill_price=fill_price,
            )

        resize_stop_order_for_position(
            open_position["position_id"],
            new_remaining,
        )

        record_position_event(
            position_id=open_position["position_id"],
            account_id=account_id,
            event_type="TP2_FILLED",
            order_id=(
                int(order_id)
                if order_id is not None
                else None
            ),
            execution_id=execution_id,
            price=fill_price,
            size_before=remaining_size,
            size_delta=-close_size,
            size_after=new_remaining,
            details={
                "symbol": symbol,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        insert_guardian_event(
            account_id,
            "TP2_HIT",
            "TAKE_PROFIT_2",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": new_remaining,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        return {
            "ok": True,
            "action": "tp2_applied",
            "execution_id": execution_id,
            "realized_pnl": realized_pnl,
            "remaining_size": new_remaining,
        }

    if execution_type == "TP3":
        if open_position["tp3_hit"]:
            return {"ok": False, "error": "tp3_already_hit", "execution_id": execution_id}

        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side,
        )

        accounting = build_partial_close_accounting(
            execution_type="TP3",
            original_size=original_size,
            remaining_size_before=remaining_size,
            margin_used_before=open_position["margin_used"],
        )

        close_size = accounting["close_size"]
        released_margin = accounting["released_margin"]

        realized_pnl = calculate_realized_pnl(
            position_side,
            open_position["entry_price"],
            fill_price,
            close_size,
        )

        close_position(
            open_position["position_id"],
            tp3_hit=True,
        )
        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            apply_order_fill(
                order_id=int(order_id),
                fill_size=close_size,
                fill_price=fill_price,
            )

        cancel_open_protective_orders_for_position(
            open_position["position_id"],
            exclude_order_id=int(order_id) if order_id is not None else None,
        )

        record_position_event(
            position_id=open_position["position_id"],
            account_id=account_id,
            event_type="TP3_FILLED",
            order_id=(
                int(order_id)
                if order_id is not None
                else None
            ),
            execution_id=execution_id,
            price=fill_price,
            size_before=remaining_size,
            size_delta=-close_size,
            size_after=0,
            details={
                "symbol": symbol,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        record_position_event(
            position_id=open_position["position_id"],
            account_id=account_id,
            event_type="POSITION_CLOSED",
            order_id=(
                int(order_id)
                if order_id is not None
                else None
            ),
            execution_id=execution_id,
            price=fill_price,
            size_before=remaining_size,
            size_delta=-close_size,
            size_after=0,
            details={
                "symbol": symbol,
                "close_reason": "TP3",
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        insert_guardian_event(
            account_id,
            "TP3_HIT",
            "TAKE_PROFIT_3",
            {
                "symbol": symbol,
                "position_id": open_position["position_id"],
                "execution_id": execution_id,
                "close_size": close_size,
                "remaining_size": 0,
                "fill_price": fill_price,
                "fee_paid": fee_paid,
                "realized_pnl": realized_pnl,
                "partial_close_accounting": accounting,
            },
        )

        refreshed_position = open_position.copy()
        refreshed_position["remaining_size"] = 0
        trade_id = maybe_finalize_trade(refreshed_position)

        return {
            "ok": True,
            "action": "tp3_applied_position_closed",
            "execution_id": execution_id,
            "trade_id": trade_id,
            "realized_pnl": realized_pnl,
        }


    if execution_type == "STOP_LOSS":
        execution_id = insert_execution_report(
            account_id=account_id,
            order_id=order_id,
            symbol=symbol,
            fill_price=fill_price,
            filled_size=filled_size,
            fee_paid=fee_paid,
            slippage_bps=slippage_bps,
            notes=notes,
            execution_type=execution_type,
            position_side=position_side,
        )

        order_role = str(payload.get("order_role") or "").lower()
        if not order_role and order_id is not None:
            order_role = get_order_role(int(order_id)) or "stop_loss"
        if order_role not in ("stop_loss", "sl2"):
            order_role = "stop_loss"

        close_size = round(min(float(filled_size), float(remaining_size)), 8)
        new_remaining = round(max(float(remaining_size) - close_size, 0.0), 8)
        is_full_close = new_remaining <= 0

        released_margin = open_position["margin_used"] if is_full_close else round(open_position["margin_used"] * (close_size / remaining_size), 8)
        new_remaining_margin = 0.0 if is_full_close else round(max(open_position["margin_used"] - released_margin, 0.0), 8)

        accounting = {
            "partial_close_policy_version": "phase7_6_adaptive_defensive_sl2",
            "execution_type": "STOP_LOSS",
            "order_role": order_role,
            "original_size": round(float(original_size), 8),
            "remaining_size_before": round(float(remaining_size), 8),
            "close_size": close_size,
            "remaining_size_after": new_remaining,
            "margin_used_before": round(float(open_position["margin_used"]), 8),
            "released_margin": released_margin,
            "remaining_margin_after": new_remaining_margin,
            "is_full_close": is_full_close,
            "reason": "stop_order_partial_reduce" if not is_full_close else "stop_order_close_remaining",
        }

        realized_pnl = calculate_realized_pnl(position_side, open_position["entry_price"], fill_price, close_size)

        if is_full_close:
            close_position(open_position["position_id"])
        else:
            update_position_after_partial_exit(open_position["position_id"], new_remaining, new_remaining_margin)

        apply_exit_balance_update(account_id, released_margin, realized_pnl, fee_paid)

        if order_id is not None:
            if is_full_close:
                finalize_position_closing_order(order_id=int(order_id), fill_size=close_size, fill_price=fill_price)
            else:
                apply_order_fill(order_id=int(order_id), fill_size=close_size, fill_price=fill_price)

        if is_full_close:
            cancel_open_protective_orders_for_position(open_position["position_id"], exclude_order_id=int(order_id) if order_id is not None else None)
        else:
            reconcile_stop_protection_for_position(account_id=account_id, position_id=open_position["position_id"], remaining_size=new_remaining)

        event_type = "SL2_FILLED" if order_role == "sl2" else "STOP_FILLED"

        record_position_event(
            position_id=open_position["position_id"],
            account_id=account_id,
            event_type=event_type,
            order_id=int(order_id) if order_id is not None else None,
            execution_id=execution_id,
            price=fill_price,
            size_before=remaining_size,
            size_delta=-close_size,
            size_after=new_remaining,
            details={"symbol": symbol, "order_role": order_role, "fee_paid": fee_paid, "realized_pnl": realized_pnl, "partial_close_accounting": accounting},
        )

        if is_full_close:
            record_position_event(
                position_id=open_position["position_id"],
                account_id=account_id,
                event_type="POSITION_CLOSED",
                order_id=int(order_id) if order_id is not None else None,
                execution_id=execution_id,
                price=fill_price,
                size_before=remaining_size,
                size_delta=-close_size,
                size_after=0,
                details={"symbol": symbol, "close_reason": "STOP_LOSS", "order_role": order_role, "fee_paid": fee_paid, "realized_pnl": realized_pnl, "partial_close_accounting": accounting},
            )

        insert_guardian_event(
            account_id,
            "STOP_LOSS_HIT",
            "STOP_LOSS_EXECUTED",
            {"symbol": symbol, "position_id": open_position["position_id"], "execution_id": execution_id, "order_role": order_role, "close_size": close_size, "remaining_size": new_remaining, "fill_price": fill_price, "fee_paid": fee_paid, "realized_pnl": realized_pnl, "partial_close_accounting": accounting},
        )

        if is_full_close:
            refreshed_position = open_position.copy()
            refreshed_position["remaining_size"] = 0
            trade_id = maybe_finalize_trade(refreshed_position)
            action = "stop_loss_applied_position_closed"
        else:
            trade_id = None
            action = "stop_loss_applied_position_reduced"

        return {"ok": True, "action": action, "execution_id": execution_id, "trade_id": trade_id, "realized_pnl": realized_pnl, "remaining_size": new_remaining, "order_role": order_role}

    return {"ok": False, "error": "unhandled_execution_case"}
