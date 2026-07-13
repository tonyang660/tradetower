"""
Phase 5 Step 3-4 no-service diagnostic.

This does not call Trade Guardian. It validates pure intake/sizing helpers.
"""

from main import build_position_sizing, normalize_take_profits, validate_signal_intake


def sample_signal():
    return {
        "account_id": 1,
        "schema_version": "strategy_signal_v2",
        "symbol": "ETHUSDT",
        "v2_decision": "trade_candidate",
        "legacy_decision": "trade",
        "position_side": "long",
        "entry_order_type": "limit",
        "entry_price": 3100.0,
        "stop_loss": 3000.0,
        "take_profits": {
            "tp1": {"price": 3250.0, "close_percent": 50, "ratio": 1.5},
            "tp2": {"price": 3350.0, "close_percent": 30, "ratio": 2.5},
            "tp3": {"price": 3450.0, "close_percent": 20, "ratio": 3.5},
        },
    }


def main():
    payload = sample_signal()
    errors = validate_signal_intake(payload)
    assert errors == [], errors

    sizing = build_position_sizing(equity=2500.0, side="long", entry=3100.0, stop=3000.0)
    assert sizing["ok"] is True
    assert sizing["risk_pct"] == 1.0
    assert sizing["risk_amount"] == 25.0
    assert sizing["stop_distance"] == 100.0
    assert sizing["size"] == 0.25
    assert sizing["notional"] == 775.0

    tps = normalize_take_profits(payload, "long", 3100.0, 3000.0)
    assert tps["tp1"]["ratio"] == 1.5
    assert tps["tp1"]["close_percent"] == 50

    high_equity = build_position_sizing(equity=25000.0, side="long", entry=3100.0, stop=3000.0)
    assert high_equity["risk_pct"] == 0.4

    print({
        "ok": True,
        "runtime": "phase5_step3_4_signal_intake_position_sizing",
        "sample_risk_pct": sizing["risk_pct"],
        "sample_risk_amount": sizing["risk_amount"],
        "sample_size": sizing["size"],
        "high_equity_risk_pct": high_equity["risk_pct"],
    })


if __name__ == "__main__":
    main()
