"""
No-cycle diagnostics for Phase 4 Step 11.

Run inside the strategy-engine container:

    python /app/app/phase4_no_cycle_diagnostics.py
"""

from __future__ import annotations

import json
from pathlib import Path

from regime_router import route_regime
from snapshot_v1_adapter import build_snapshot_refs, validate_snapshot_for_strategy
from v1_decision_policy import decide_strategy_signal
from v1_entry_logic import check_v1_entry
from v1_history_access import build_history_diagnostics
from v1_signal_scorer import score_v1_signal
from v1_trade_levels import build_proposed_trade


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phase4_step11_market_snapshot_v2_trend_fixture.json"


def run_fixture(snapshot: dict) -> dict:
    valid, reasons = validate_snapshot_for_strategy(snapshot)
    route = route_regime(snapshot)
    direction = route.get("direction_hint", "neutral")
    strategy = route.get("selected_strategy", "none")

    entry_validation = check_v1_entry(snapshot, strategy, direction)
    score_result = score_v1_signal(snapshot, direction, strategy, snapshot.get("symbol", ""))

    proposed_trade = None
    if entry_validation.get("valid"):
        proposed_trade = build_proposed_trade(
            snapshot,
            symbol=snapshot.get("symbol", ""),
            direction=direction,
            selected_strategy=strategy,
            regime=route.get("regime", "unknown"),
            score=score_result.get("score"),
        )

    signal = decide_strategy_signal(
        symbol=snapshot.get("symbol", ""),
        regime_route=route,
        entry_validation=entry_validation,
        score_result=score_result,
        snapshot_refs=build_snapshot_refs(snapshot),
        proposed_trade=proposed_trade,
    )

    return {
        "snapshot_valid": valid,
        "snapshot_reasons": reasons,
        "history": build_history_diagnostics(snapshot),
        "route": route,
        "entry_validation": entry_validation,
        "score": score_result,
        "proposed_trade_valid": bool(proposed_trade and proposed_trade.get("valid")),
        "decision": signal.get("decision"),
        "v2_decision": signal.get("v2_decision", signal.get("decision")),
        "score_thresholds": signal.get("score_thresholds"),
        "reason_tags": signal.get("reason_tags", []),
    }


def main() -> int:
    snapshot = json.loads(FIXTURE_PATH.read_text())
    result = run_fixture(snapshot)
    print(json.dumps(result, indent=2, sort_keys=True))

    required = [
        result["snapshot_valid"],
        result["history"]["timeframes"]["entry"]["has_v1_tail_requirements"],
        result["history"]["timeframes"]["primary"]["has_v1_tail_requirements"],
        result["route"].get("selected_strategy") == "trend_following",
        "macd_hist_tail" in result["entry_validation"].get("details", {}).get("primary_macd", {}),
        result["score"].get("breakdown", {}).get("momentum", {}).get("max") == 20,
    ]

    return 0 if all(required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
