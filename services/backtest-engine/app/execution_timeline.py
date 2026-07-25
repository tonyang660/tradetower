from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

PHASE18_EXECUTION_TIMELINE_VERSION = "phase18a_virtual_1m_execution_on_5m_data"

_TIMEFRAME_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

def timeframe_seconds(timeframe: str) -> int:
    value = str(timeframe or "").strip().lower()
    if value not in _TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported_timeframe_for_execution_timeline: {timeframe}")
    return _TIMEFRAME_SECONDS[value]

@dataclass(frozen=True)
class ExecutionTimelineConfig:
    decision_timeframe: str
    execution_timeframe: str
    execution_data_timeframe: str
    feature_timeframes: list[str]
    virtual_execution: bool
    virtual_execution_steps_per_decision: int
    version: str = PHASE18_EXECUTION_TIMELINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "decision_timeframe": self.decision_timeframe,
            "execution_timeframe": self.execution_timeframe,
            "execution_data_timeframe": self.execution_data_timeframe,
            "feature_timeframes": self.feature_timeframes,
            "virtual_execution": self.virtual_execution,
            "virtual_execution_steps_per_decision": self.virtual_execution_steps_per_decision,
            "notes": [
                "Strategy decisions run on decision_timeframe.",
                "Execution mode is 1m logical execution.",
                "No 1m candles are required in Phase 18A/B.",
                "When execution_data_timeframe is 5m, each 5m candle represents five virtual 1m execution slots.",
            ],
        }

def normalize_execution_timeline_config(payload: dict[str, Any], *, existing_timeframes: list[str], cycle_timeframe: str) -> ExecutionTimelineConfig:
    decision_timeframe = str(payload.get("decision_timeframe") or payload.get("cycle_timeframe") or cycle_timeframe or "5m")
    execution_timeframe = str(payload.get("execution_timeframe") or "1m")
    execution_data_timeframe = str(payload.get("execution_data_timeframe") or decision_timeframe)

    feature_timeframes = payload.get("feature_timeframes") or existing_timeframes or [decision_timeframe]
    if isinstance(feature_timeframes, str):
        feature_timeframes = [feature_timeframes]
    feature_timeframes = [str(item) for item in feature_timeframes]

    decision_seconds = timeframe_seconds(decision_timeframe)
    execution_seconds = timeframe_seconds(execution_timeframe)
    data_seconds = timeframe_seconds(execution_data_timeframe)

    if execution_seconds > decision_seconds:
        raise ValueError("execution_timeframe_must_be_less_than_or_equal_to_decision_timeframe")

    virtual_execution = execution_timeframe != execution_data_timeframe
    if virtual_execution:
        if data_seconds != decision_seconds:
            raise ValueError("virtual_execution_requires_execution_data_timeframe_equal_decision_timeframe")
        steps = max(1, int(decision_seconds / execution_seconds))
    else:
        steps = 1

    return ExecutionTimelineConfig(
        decision_timeframe=decision_timeframe,
        execution_timeframe=execution_timeframe,
        execution_data_timeframe=execution_data_timeframe,
        feature_timeframes=feature_timeframes,
        virtual_execution=virtual_execution,
        virtual_execution_steps_per_decision=steps,
    )

def ensure_timeframes_for_timeline(timeframes: list[str], timeline: ExecutionTimelineConfig) -> list[str]:
    ordered: list[str] = []
    for tf in list(timeframes or []) + [timeline.decision_timeframe] + timeline.feature_timeframes:
        value = str(tf)
        if value not in ordered:
            ordered.append(value)
    return ordered

def virtual_execution_slots(candle_timestamp, timeline: ExecutionTimelineConfig | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(timeline, dict):
        execution_timeframe = timeline.get("execution_timeframe", "1m")
        execution_data_timeframe = timeline.get("execution_data_timeframe", "5m")
        virtual = bool(timeline.get("virtual_execution", True))
        step_count = int(timeline.get("virtual_execution_steps_per_decision", 5) or 5)
    else:
        execution_timeframe = timeline.execution_timeframe
        execution_data_timeframe = timeline.execution_data_timeframe
        virtual = bool(timeline.virtual_execution)
        step_count = int(timeline.virtual_execution_steps_per_decision)

    step_seconds = timeframe_seconds(execution_timeframe)
    slots = []
    for index in range(max(1, step_count)):
        try:
            slot_timestamp = candle_timestamp + timedelta(seconds=step_seconds * index)
        except Exception:
            slot_timestamp = candle_timestamp
        slots.append({
            "slot_index": index,
            "slot_timestamp": slot_timestamp,
            "execution_timeframe": execution_timeframe,
            "source_timeframe": execution_data_timeframe,
            "virtual": virtual,
        })
    return slots
