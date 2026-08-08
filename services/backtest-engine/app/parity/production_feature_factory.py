from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
from threading import Lock
import time
from typing import Any
import zlib

from production_runtime import load_production_module


BACKTEST_PRODUCTION_FEATURE_ADAPTER_VERSION = "backtest_production_feature_factory_adapter_v2"
BACKTEST_SHARED_FEATURE_COMPUTATION_VERSION = "exact_production_call_memoization_v1"
PERSISTENT_FEATURE_CACHE_VERSION = "production_feature_block_cache_v1"

_active_shared_calculation: ContextVar[dict[str, Any] | None] = ContextVar(
    "backtest_active_shared_feature_calculation",
    default=None,
)


def _install_shared_calculation_adapter(factory) -> None:
    """Memoize repeated pure indicator calls inside one production block.

    The production module is a private read-only copy loaded only by the
    backtest service. Its public compute functions and call order remain exact;
    wrappers merely return the first result when the same pure function is
    invoked again for the same candle frame in that block. ContextVar keeps
    caches isolated if callers explicitly enable multiple feature workers.
    """
    if getattr(factory, "_backtest_shared_calculation_adapter", None) == BACKTEST_SHARED_FEATURE_COMPUTATION_VERSION:
        return

    for function_name in ("compute_ema", "compute_rsi", "compute_atr", "compute_adx", "compute_macd"):
        original = getattr(factory, function_name)

        def wrapper(*args, __name=function_name, __original=original, **kwargs):
            active = _active_shared_calculation.get()
            if active is None:
                return __original(*args, **kwargs)
            # Production uses each wrapped function with one candle close/frame
            # per timeframe block. Parameters fully identify repeated calls
            # inside that isolated context.
            key = (__name, args[1:], tuple(sorted(kwargs.items())))
            cached = active["values"].get(key)
            if cached is not None:
                active["hits"] += 1
                return cached
            result = __original(*args, **kwargs)
            active["values"][key] = result
            active["misses"] += 1
            return result

        setattr(factory, function_name, wrapper)

    factory._backtest_shared_calculation_adapter = BACKTEST_SHARED_FEATURE_COMPUTATION_VERSION


@contextmanager
def _shared_calculation_scope(factory):
    _install_shared_calculation_adapter(factory)
    state: dict[str, Any] = {"values": {}, "hits": 0, "misses": 0}
    token = _active_shared_calculation.set(state)
    try:
        yield state
    finally:
        _active_shared_calculation.reset(token)


class PersistentFeatureBlockCache:
    """Disk-backed cache of exact production-computed timeframe payloads."""

    def __init__(self, path: str, namespace: str, flush_every: int = 128):
        self.path = str(path)
        self.namespace = namespace
        self.flush_every = max(1, int(flush_every))
        self._lock = Lock()
        self._pending: dict[str, bytes] = {}
        self._conn: sqlite3.Connection | None = None
        self._disabled_reason: str | None = None
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.errors = 0
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_blocks (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(namespace, cache_key)
                ) WITHOUT ROWID
                """
            )
            self._conn.commit()
        except Exception as exc:
            self._disabled_reason = f"{type(exc).__name__}:{exc}"
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def get(self, cache_key: str) -> dict[str, Any] | None:
        if self._conn is None:
            return None
        with self._lock:
            blob = self._pending.get(cache_key)
            if blob is None:
                try:
                    row = self._conn.execute(
                        "SELECT payload FROM feature_blocks WHERE namespace=? AND cache_key=?",
                        (self.namespace, cache_key),
                    ).fetchone()
                    blob = row[0] if row else None
                except Exception:
                    self.errors += 1
                    blob = None
            if blob is None:
                self.misses += 1
                return None
            try:
                value = pickle.loads(zlib.decompress(blob))
            except Exception:
                self.errors += 1
                self.misses += 1
                return None
            self.hits += 1
            return value

    def put(self, cache_key: str, payload: dict[str, Any]) -> None:
        if self._conn is None:
            return
        try:
            blob = zlib.compress(pickle.dumps(payload, protocol=5), level=3)
        except Exception:
            self.errors += 1
            return
        with self._lock:
            self._pending[cache_key] = blob
            if len(self._pending) >= self.flush_every:
                self._flush_locked()

    def _flush_locked(self) -> None:
        if self._conn is None or not self._pending:
            return
        pending = list(self._pending.items())
        try:
            self._conn.executemany(
                "INSERT OR IGNORE INTO feature_blocks(namespace, cache_key, payload) VALUES (?, ?, ?)",
                [(self.namespace, key, sqlite3.Binary(blob)) for key, blob in pending],
            )
            self._conn.commit()
            self.writes += len(pending)
            self._pending.clear()
        except Exception:
            self.errors += 1

    def diagnostics(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "path": self.path,
            "namespace": self.namespace,
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "pending_writes": len(self._pending),
            "errors": self.errors,
            "disabled_reason": self._disabled_reason,
        }

    def close(self) -> None:
        with self._lock:
            self._flush_locked()
            if self._conn is not None:
                self._conn.close()
                self._conn = None


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


def _production_cache_namespace(factory) -> str:
    source_path = Path(str(getattr(factory, "__file__", "")))
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path.is_file() else "unknown"
    contract = {
        "cache_version": PERSISTENT_FEATURE_CACHE_VERSION,
        "shared_computation_version": BACKTEST_SHARED_FEATURE_COMPUTATION_VERSION,
        "production_source_sha256": source_digest,
        "snapshot_schema": getattr(factory, "SNAPSHOT_SCHEMA_VERSION", None),
        "feature_factory_version": getattr(factory, "FEATURE_FACTORY_VERSION", None),
        "market_snapshot_contract": getattr(factory, "MARKET_SNAPSHOT_CONTRACT_VERSION", None),
        "pandas_version": getattr(getattr(factory, "pd", None), "__version__", None),
        "numpy_version": getattr(getattr(factory, "np", None), "__version__", None),
    }
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _persistent_block_key(symbol: str, timeframe: str, candles: list[dict[str, Any]]) -> str:
    candle_digest = hashlib.sha256(
        json.dumps(candles, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{str(symbol).upper()}:{timeframe}:{candle_digest}"


def _timeframe_block(
    factory,
    timeframe: str,
    source_rows: list[Any],
    *,
    symbol: str = "UNKNOWN",
    persistent_cache: PersistentFeatureBlockCache | None = None,
) -> tuple[dict | None, dict | None, dict[str, Any]]:
    fetch_limit = int(factory.FETCH_WINDOWS[timeframe])
    emit_limit = int(factory.EMIT_WINDOWS[timeframe])
    candles = [_candle(row) for row in source_rows[-fetch_limit:]]
    calculation_diagnostics = {
        "persistent_hit": 0,
        "persistent_miss": 0,
        "shared_series_hits": 0,
        "shared_series_misses": 0,
    }
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
        return (
            None,
            {"timeframe": timeframe, "error": "insufficient_candle_data", "data_quality": quality},
            calculation_diagnostics,
        )

    cache_key = _persistent_block_key(symbol, timeframe, candles)
    computed = persistent_cache.get(cache_key) if persistent_cache is not None else None
    if computed is not None:
        calculation_diagnostics["persistent_hit"] = 1
    else:
        if persistent_cache is not None and persistent_cache.enabled:
            calculation_diagnostics["persistent_miss"] = 1
        frame = factory.to_dataframe(candles)
        with _shared_calculation_scope(factory) as shared:
            indicators = factory.compute_indicators(frame)
            structure = factory.compute_structure(frame, indicators)
            price_action = factory.compute_price_action(frame, indicators, structure)
            volatility = factory.compute_volatility(frame, indicators)
            regime_inputs = factory.compute_regime_inputs(frame, indicators, structure, volatility)
        calculation_diagnostics["shared_series_hits"] = int(shared["hits"])
        calculation_diagnostics["shared_series_misses"] = int(shared["misses"])
        computed = {
            "indicators": indicators,
            "structure": structure,
            "price_action": price_action,
            "volatility": volatility,
            "regime_inputs": regime_inputs,
        }
        if persistent_cache is not None:
            persistent_cache.put(cache_key, computed)

    return {
        "timeframe": timeframe,
        "window_size": emit_limit,
        "fetch_window_size": fetch_limit,
        "data_quality": quality,
        "latest": factory.latest_candle_payload(candles),
        "candles": candles[-emit_limit:],
        **computed,
    }, None, calculation_diagnostics


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


def default_persistent_feature_cache_path(dataset_id: int) -> str:
    root = Path(os.getenv(
        "BACKTEST_FEATURE_CACHE_ROOT",
        "/data/historical/binance/.backtest-feature-cache",
    ))
    return str(root / f"dataset-{max(0, int(dataset_id))}.sqlite3")


class ProductionFeatureSnapshotCache:
    """Reuse exact production timeframe outputs until their closed input changes."""

    def __init__(
        self,
        *,
        persistent_enabled: bool = False,
        persistent_path: str | None = None,
    ):
        # Load the module before worker threads start so import-time state stays
        # deterministic and only pure production calculations run in parallel.
        self.factory = load_production_module("feature_factory", "main")
        _install_shared_calculation_adapter(self.factory)
        self._timeframe_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = Lock()
        self._persistent_cache = (
            PersistentFeatureBlockCache(
                persistent_path or default_persistent_feature_cache_path(0),
                _production_cache_namespace(self.factory),
            )
            if persistent_enabled
            else None
        )

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
            "persistent_hits": 0,
            "persistent_misses": 0,
            "shared_series_hits": 0,
            "shared_series_misses": 0,
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
                calculation_diagnostics = {
                    "persistent_hit": 0,
                    "persistent_miss": 0,
                    "shared_series_hits": 0,
                    "shared_series_misses": 0,
                }
                reused = True
                elapsed = 0.0
            else:
                started_at = time.perf_counter()
                block, error, calculation_diagnostics = _timeframe_block(
                    factory,
                    timeframe,
                    rows,
                    symbol=symbol,
                    persistent_cache=self._persistent_cache,
                )
                elapsed = time.perf_counter() - started_at
                reused = False
                with self._lock:
                    self._timeframe_cache[cache_key] = {
                        "signature": signature,
                        "block": block,
                        "error": error,
                    }

            diagnostics["compute_seconds"] += elapsed
            diagnostics["persistent_hits"] += int(calculation_diagnostics["persistent_hit"])
            diagnostics["persistent_misses"] += int(calculation_diagnostics["persistent_miss"])
            diagnostics["shared_series_hits"] += int(calculation_diagnostics["shared_series_hits"])
            diagnostics["shared_series_misses"] += int(calculation_diagnostics["shared_series_misses"])
            diagnostics["by_timeframe"][timeframe] = {
                "built": 0 if reused else 1,
                "reused": 1 if reused else 0,
                "compute_seconds": elapsed,
                **calculation_diagnostics,
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

    def persistent_diagnostics(self) -> dict[str, Any]:
        if self._persistent_cache is None:
            return {
                "enabled": False,
                "path": None,
                "hits": 0,
                "misses": 0,
                "writes": 0,
                "pending_writes": 0,
                "errors": 0,
                "disabled_reason": "disabled_by_config",
            }
        return self._persistent_cache.diagnostics()

    def close(self) -> None:
        if self._persistent_cache is not None:
            self._persistent_cache.close()


def build_market_snapshot_v2(symbol: str, timeframe_rows: dict[str, list[Any]], timestamp=None) -> dict[str, Any]:
    """Uncached compatibility entrypoint with the original adapter contract."""
    factory = load_production_module("feature_factory", "main")
    symbol = factory.normalize_symbol(symbol)
    blocks: dict[str, dict] = {}
    qualities: dict[str, dict] = {}
    missing: list[dict] = []

    for timeframe in factory.TIMEFRAMES:
        block, error, _ = _timeframe_block(
            factory,
            timeframe,
            list(timeframe_rows.get(timeframe, []) or []),
            symbol=symbol,
        )
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
