
from __future__ import annotations

from typing import Any

from strategies.registry import canonical_strategy_name, get_strategy_detail


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _parameter_schema(strategy_detail: dict[str, Any]) -> dict[str, Any]:
    config = strategy_detail.get("config", {}) or {}
    return config.get("parameters", {}) or {}


def _validate_parameter_type(name: str, spec: dict[str, Any], value: Any) -> str | None:
    expected = str(spec.get("type", "")).lower()

    if expected in {"float", "number"}:
        try:
            float(value)
        except Exception:
            return f"parameter {name} must be a float"

    if expected in {"int", "integer"}:
        try:
            int(value)
        except Exception:
            return f"parameter {name} must be an integer"

    if expected in {"bool", "boolean"} and not isinstance(value, bool):
        return f"parameter {name} must be a boolean"

    min_value = spec.get("min")
    max_value = spec.get("max")
    if expected in {"float", "number", "int", "integer"}:
        try:
            numeric = float(value)
            if min_value is not None and numeric < float(min_value):
                return f"parameter {name} must be >= {min_value}"
            if max_value is not None and numeric > float(max_value):
                return f"parameter {name} must be <= {max_value}"
        except Exception:
            pass

    return None


def validate_strategy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate strategy selection and compatibility.

    This validator is intentionally warning-friendly because the current backtest
    engine still uses Phase 14 sample data. Exact production parity requires
    multi-timeframe datasets later.
    """
    errors: list[str] = []
    warnings: list[str] = []

    raw_strategy_name = payload.get("strategy_name", "tradetower_baseline_v1")
    try:
        strategy_name = canonical_strategy_name(raw_strategy_name)
        detail = get_strategy_detail(strategy_name)
    except Exception as exc:
        return {
            "valid": False,
            "strategy_name": raw_strategy_name,
            "canonical_strategy_name": None,
            "errors": [str(exc)],
            "warnings": [],
            "strategy": None,
        }

    requested_timeframes = _as_list(payload.get("timeframes"))
    cycle_timeframe = payload.get("cycle_timeframe")
    if cycle_timeframe and str(cycle_timeframe) not in requested_timeframes:
        requested_timeframes.append(str(cycle_timeframe))

    metadata_required = _as_list(detail.get("required_timeframes"))
    config = detail.get("config", {}) or {}
    active_phase_timeframes = _as_list(config.get("active_phase15b_timeframes"))

    # Phase 15 is allowed to run 15m synthetic tests while metadata declares the
    # full production target. Strict mode will enforce the real requirements.
    strict_timeframes = bool(payload.get("strategy_validation_strict_timeframes", False))
    missing_required = [tf for tf in metadata_required if tf not in requested_timeframes]

    if missing_required:
        if strict_timeframes:
            errors.append(
                "missing_required_timeframes:"
                + ",".join(missing_required)
            )
        else:
            warnings.append(
                "strategy target requires timeframes "
                + ",".join(metadata_required)
                + "; current request has "
                + ",".join(requested_timeframes or ["<none>"])
                + ". Allowed as non-strict Phase 15 validation."
            )

    if active_phase_timeframes:
        active_missing = [tf for tf in active_phase_timeframes if tf not in requested_timeframes]
        if active_missing:
            warnings.append(
                "active phase test timeframes missing:"
                + ",".join(active_missing)
            )

    parameter_schema = _parameter_schema(detail)
    parameter_errors: list[str] = []
    parameter_warnings: list[str] = []

    for name, spec in parameter_schema.items():
        if name not in payload:
            continue
        issue = _validate_parameter_type(name, spec, payload[name])
        if issue:
            parameter_errors.append(issue)

    # Unknown strategy-like keys are not rejected; this lets backtest run config
    # carry non-strategy settings such as fees, Guardian policy, data mode, etc.
    if parameter_errors:
        errors.extend(parameter_errors)

    return {
        "valid": len(errors) == 0,
        "strategy_name": raw_strategy_name,
        "canonical_strategy_name": strategy_name,
        "errors": errors,
        "warnings": warnings + parameter_warnings,
        "requested_timeframes": requested_timeframes,
        "required_timeframes": metadata_required,
        "active_phase_timeframes": active_phase_timeframes,
        "strict_timeframes": strict_timeframes,
        "parameter_schema_keys": sorted(parameter_schema.keys()),
        "strategy": detail,
    }


def validate_strategy_run_config(config: dict[str, Any]) -> dict[str, Any]:
    return validate_strategy_payload(config)
