from __future__ import annotations

from typing import Any

from production_runtime import load_production_module


BACKTEST_CANDIDATE_ADAPTER_VERSION = "backtest_production_candidate_filter_adapter_v1"


def rank_market_snapshots(
    snapshots: dict[str, dict[str, Any]],
    *,
    excluded_symbols: set[str] | None = None,
) -> dict[str, Any]:
    candidate_filter = load_production_module("candidate_filter", "main")
    excluded = {str(symbol).upper() for symbol in (excluded_symbols or set())}
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for symbol, snapshot in snapshots.items():
        symbol = str(symbol).upper()
        if symbol in excluded:
            rejected.append(candidate_filter.build_rejected_item(
                symbol=symbol,
                reason="SYMBOL_ALREADY_HAS_ACTIVE_EXPOSURE",
            ))
            continue

        quality_error = candidate_filter.validate_snapshot_data_quality(snapshot)
        if quality_error:
            unavailable.append(candidate_filter.build_unavailable_item(
                symbol=symbol,
                reason=quality_error.get("reason", "MARKET_DATA_UNHEALTHY"),
                details=quality_error.get("details", {}),
                snapshot_data_quality=(quality_error.get("details", {}) or {}).get(
                    "data_quality", snapshot.get("data_quality", {})
                ),
            ))
            continue

        score, bias, reasons, sub_scores, path_hints = candidate_filter.score_snapshot(snapshot)
        item = candidate_filter.build_candidate_item(
            symbol,
            score,
            bias,
            reasons,
            sub_scores,
            snapshot,
            path_hints,
        )
        if score >= candidate_filter.MIN_SCORE:
            candidates.append(item)
        else:
            item["candidate_status"] = "rejected"
            item["candidate_tier"] = "rejected"
            item["reject_reason"] = "LOW_CONVICTION"
            rejected.append(item)

    candidates.sort(key=lambda item: item["candidate_score"], reverse=True)
    rejected.sort(key=lambda item: float(item.get("candidate_score", 0.0) or 0.0), reverse=True)
    selected = candidates[: int(candidate_filter.MAX_CANDIDATES)]
    return {
        "schema_version": candidate_filter.CANDIDATE_FILTER_SCHEMA_VERSION,
        "candidate_filter_version": candidate_filter.CANDIDATE_FILTER_VERSION,
        "runtime_version": candidate_filter.CANDIDATE_FILTER_RUNTIME_VERSION,
        "backtest_adapter_version": BACKTEST_CANDIDATE_ADAPTER_VERSION,
        "candidate_filter_mode": candidate_filter.CANDIDATE_FILTER_MODE,
        "input_symbols_count": len(snapshots),
        "candidates": selected,
        "rejected": rejected,
        "unavailable": unavailable,
        "by_symbol": {item["symbol"]: item for item in selected},
    }
