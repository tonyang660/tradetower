"""
Phase 4 Step 12 compatibility diagnostics.

Runs without Scheduler cycle, Risk service, or Paper Execution service.
It validates the in-process payload builders used at the Scheduler/Risk boundary.
"""

from cycle_utils import (
    build_paper_execution_payload,
    build_risk_payload_from_strategy,
    normalize_position_side,
)


def sample_strategy_signal():
    return {
        "ok": True,
        "schema_version": "strategy_signal_v2",
        "symbol": "ETHUSDT",
        "v2_decision": "trade_candidate",
        "decision": "trade",
        "legacy_decision": "trade",
        "decision_side": "long",
        "position_side": "long",
        "selected_strategy": "trend_following",
        "regime": "Uptrend",
        "score": 82,
        "confidence": 82,
        "entry_order_type": "limit",
        "entry_price": 3100.0,
        "stop_loss": 3000.0,
        "take_profits": {
            "tp1": {"price": 3250.0, "close_percent": 50, "ratio": 1.5},
            "tp2": {"price": 3350.0, "close_percent": 30, "ratio": 2.5},
            "tp3": {"price": 3450.0, "close_percent": 20, "ratio": 3.5},
        },
        "reason_tags": ["SCORE_MEETS_TRADE_THRESHOLD"],
    }


def main():
    strategy = sample_strategy_signal()

    assert normalize_position_side(strategy) == "long"

    risk_payload = build_risk_payload_from_strategy(1, strategy)
    assert risk_payload["position_side"] == "long"
    assert risk_payload["position_side"] != "trade"
    assert risk_payload["entry_order_type"] == "limit"
    assert risk_payload["entry_price"] == 3100.0
    assert risk_payload["stop_loss"] == 3000.0
    assert risk_payload["take_profits"]["tp1"]["ratio"] == 1.5
    assert risk_payload["take_profits"]["tp1"]["close_percent"] == 50

    risk_result = {
        "ok": True,
        "approved": True,
        "symbol": "ETHUSDT",
        "position_side": "long",
        "entry_order_type": "limit",
        "entry_price": 3100.0,
        "stop_loss": 3000.0,
        "tp1_price": 3250.0,
        "tp2_price": 3350.0,
        "tp3_price": 3450.0,
        "tp1_close_percent": 50,
        "tp2_close_percent": 30,
        "tp3_close_percent": 20,
        "size": 1.0,
        "risk_amount": 100.0,
        "leverage": 10,
    }

    paper_payload = build_paper_execution_payload(
        account_id=1,
        strategy_result=strategy,
        risk_result=risk_result,
        cycle_id="phase4-step12-test",
    )

    assert paper_payload["position_side"] == "long"
    assert paper_payload["order_type"] == "limit"
    assert paper_payload["tp1_price"] == 3250.0
    assert paper_payload["tp1_close_percent"] == 50
    assert paper_payload["v2_decision"] == "trade_candidate"

    print({
        "ok": True,
        "risk_payload_position_side": risk_payload["position_side"],
        "paper_payload_position_side": paper_payload["position_side"],
        "tp_policy": "v1_1.5_2.5_3.5_close_50_30_20",
    })


if __name__ == "__main__":
    main()
