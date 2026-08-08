from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
import time
from typing import Any

from production_runtime import load_production_module


BACKTEST_PRODUCTION_FEATURE_ADAPTER_VERSION = "backtest_production_feature_factory_adapter_v1"


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _candle(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        source = row
    else:
        source = getattr(row, "__dict__", {})
    return {
        "timestamp": _timestamp(source.get("timestamp") or getattr(row, "timestamp", None)),
        "open": float(source.get("open", getattr(row, "open", 0.0))),
        "high": float(source.get("high", getattr(row, "high", 0.0))),
        "low": float(source.get("low", getattr(row, "low", 0.0))),
        "close": float(source.get("close", getattr(row, "close", 0.0))),
        "volume": float(source.get("volume", getattr(row, "volume", 0.0)) or 0.0),
    }


def _timeframe_block(factory, timeframe: str, source_rows: list[Any]) -> tuple[dict | None, dict | None]:
    fetch_limit = int(factory.FETCH_WINDOWS[timeframe])
    emit_limit = int(factory.EMIT_WINDOWS[timeframe])
    candles = [_candle(row) for row in source_rows[-fetch_limit:]]
    metadata = {
        "provider": "backtest_local_dataset",
        "market": "futures_um",
        "stored_rows": len(source_rows),
        "first_timestamp": candles[0]["timestamp"] if candles else None,
        "last_timestamp": candles[-1]["timestamp"] if candles else None,
        "status": {
            "healthy": len(candles) >= fetch_limit,
            "reason_codes": [] if len(candles) >= fetch_limit else ["INSUFFICIENT_CANDLE_DATA"],
            "provider": "backtest_local_dataset",
            "market": "futures_um",
            "stored_rows": len(source_rows),
            "first_timestamp": candles[0]["timestamp"] if candles else None,
            "last_timestamp": candles[-1]["timestamp"] if candles else None,
            "has_min_rows": len(candles) >= fetch_limit,
            "gap_count": 0,
        },
    }
    quality = factory.build_timeframe_data_quality(
        timeframe=timeframe,
        limit=fetch_limit,
        candles=candles,
        metadata=metadata,
        fetch_error=None,
    )
    quality["source"] = "backtest_local_dataset"
    quality["closed_candles_only"] = True
    if len(candles) < fetch_limit:
        return None, {"timeframe": timeframe, "error": "insufficient_candle_data", "data_quality": quality}

    frame = factory.to_dataframe(candles)
    indicators = factory.compute_indicators(frame)
    structure = factory.compute_structure(frame, indicators)
    price_action = factory.compute_price_action(frame, indicators, structure)
    volatility = factory.compute_volatility(frame, indicators)
    regime_inputs = factory.compute_regime_inputs(frame, indicators, structure, volatility)
    return {
        "timeframe": timeframe,
        "window_size": emit_limit,
        "fetch_window_size": fetch_limit,
        "data_quality": quality,
        "latest": factory.latest_candle_payload(candles),
        "candles": candles[-emit_limit:],
        "indicators": indicators,
        "structure": structure,
        "price_action": price_action,
        "volatility": volatility,
        "regime_inputs": regime_inputs,
    }, None


def _rows_signature(source_rows: list[Any]) -> tuple[Any, ...]:
    """Identify immutable closed-candle input without scanning the full history."""
    if not source_rows:
        return (0,)
    first = _candle(source_rows[0])
    last = _candle(source_rows[-1])
    return (
        len(source_rows),
        first["timestamp"],
        last["timestamp"],
        last["open"],
        last["high"],
        last["low"],
        last["close"],
        last["volume"],
    )


def _assemble_market_snapshot(
    factory,
    symbol: str,
    blocks: dict[str, dict],
    qualities: dict[str, dict],
    missing: list[dict],
    timestamp=None,
) -> dict[str, Any]:
    symbol = factory.normalize_symbol(symbol)
    generated_at = _timestamp(timestamp or datetime.now(timezone.utc))
    quality = factory.aggregate_data_quality(qualities)
    quality["source"] = "backtest_local_dataset"
    quality["closed_candles_only"] = True
    quality["missing"] = missing

    return {
        "snapshot_meta": {
            "schema_version": factory.SNAPSHOT_SCHEMA_VERSION,
            "feature_factory_version": factory.FEATURE_FACTORY_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
            "contract_version": factory.MARKET_SNAPSHOT_CONTRACT_VERSION,
            "indicator_contract_version": factory.INDICATOR_CONTRACT_VERSION,
            "structure_contract_version": factory.STRUCTURE_CONTRACT_VERSION,
            "regime_inputs_contract_version": factory.REGIME_INPUTS_CONTRACT_VERSION,
            "multi_timeframe_context_contract_version": factory.MULTI_TIMEFRAME_CONTEXT_CONTRACT_VERSION,
            "backtest_adapter_version": BACKTEST_PRODUCTION_FEATURE_ADAPTER_VERSION,
        },
        "schema_version": factory.SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "snapshot_timestamp": generated_at,
        "source": "backtest_production_feature_factory",
        "v1_parity": factory.build_v1_parity_contract(),
        "data_quality": quality,
        "multi_timeframe_context": factory.build_multi_timeframe_context(blocks) if not missing else {},
        "timeframes": blocks,
    }


class ProductionFeatureSnapshotCache:
    """Reuse exact production timeframe outputs until their closed input changes."""

    def __init__(self):
        # Load the module before worker threads start so import-time state stays
        # deterministic and only pure production calculations run in parallel.
        self.factory = load_production_module("feature_factory", "main")
        self._timeframe_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._timeframe_cache.clear()

    def build_market_snapshot_v2(
        self,
        symbol: str,
        timeframe_rows: dict[str, list[Any]],
        timestamp=None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        factory = self.factory
        symbol = factory.normalize_symbol(symbol)
        blocks: dict[str, dict] = {}
        qualities: dict[str, dict] = {}
        missing: list[dict] = []
        diagnostics = {
            "blocks_built": 0,
            "blocks_reused": 0,
            "compute_seconds": 0.0,
            "by_timeframe": {},
        }

        for timeframe in factory.TIMEFRAMES:
            rows = list(timeframe_rows.get(timeframe, []) or [])
            signature = _rows_signature(rows)
            cache_key = (symbol, timeframe)
            with self._lock:
                cached = self._timeframe_cache.get(cache_key)

            if cached is not None and cached["signature"] == signature:
                block = cached["block"]
                error = cached["error"]
                reused = True
                elapsed = 0.0
            else:
                started_at = time.perf_counter()
                block, error = _timeframe_block(factory, timeframe, rows)
                elapsed = time.perf_counter() - started_at
                reused = False
                with self._lock:
                    self._timeframe_cache[cache_key] = {
                        "signature": signature,
                        "block": block,
                        "error": error,
                    }

            diagnostics["compute_seconds"] += elapsed
            diagnostics["by_timeframe"][timeframe] = {
                "built": 0 if reused else 1,
                "reused": 1 if reused else 0,
                "compute_seconds": elapsed,
            }
            if reused:
                diagnostics["blocks_reused"] += 1
            else:
                diagnostics["blocks_built"] += 1

            if error:
                missing.append(error)
                qualities[timeframe] = error["data_quality"]
            else:
                blocks[timeframe] = block
                qualities[timeframe] = block["data_quality"]

        return _assemble_market_snapshot(
            factory,
            symbol,
            blocks,
            qualities,
            missing,
            timestamp,
        ), diagnostics


def build_market_snapshot_v2(symbol: str, timeframe_rows: dict[str, list[Any]], timestamp=None) -> dict[str, Any]:
    """Uncached compatibility entrypoint with the original adapter contract."""
    factory = load_production_module("feature_factory", "main")
    symbol = factory.normalize_symbol(symbol)
    blocks: dict[str, dict] = {}
    qualities: dict[str, dict] = {}
    missing: list[dict] = []

    for timeframe in factory.TIMEFRAMES:
        block, error = _timeframe_block(factory, timeframe, list(timeframe_rows.get(timeframe, []) or []))
        if error:
            missing.append(error)
            qualities[timeframe] = error["data_quality"]
        else:
            blocks[timeframe] = block
            qualities[timeframe] = block["data_quality"]

    return _assemble_market_snapshot(
        factory,
        symbol,
        blocks,
        qualities,
        missing,
        timestamp,
    )
