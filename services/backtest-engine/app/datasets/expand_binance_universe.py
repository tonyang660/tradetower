from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from db import get_conn
from datasets.binance_downloader import run_download_job
from datasets.config import (
    DEFAULT_STORAGE_ROOT,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    available_from,
    normalize_symbols,
    normalize_timeframes,
)
from datasets.parquet_store import convert_dataset_to_parquet
from datasets.quality_scanner import scan_dataset_quality
from datasets.registry import expected_rows_for_timeframe


EXPANSION_SYMBOLS = tuple(
    symbol for symbol in DEFAULT_SYMBOLS
    if symbol not in {"BTCUSDT", "ETHUSDT"}
)
EXPANSION_TIMEFRAMES = tuple(DEFAULT_TIMEFRAMES)
PIPELINE_VERSION = "binance_universe_expansion_v1"


def _parse_time(value: str | datetime | None, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise ValueError("timestamp is required")
        return default
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_end_time() -> datetime:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(microseconds=1)


def _archive_start(symbol: str) -> datetime:
    value = available_from(symbol)
    if not value:
        raise ValueError(f"archive_boundary_missing:{symbol}")
    return _parse_time(f"{value}T00:00:00Z")


def _load_dataset(dataset_id: int) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT row_to_json(d) FROM historical_datasets d WHERE dataset_id=%s",
            (dataset_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"dataset_not_found:{dataset_id}")
    dataset = row[0]
    if str(dataset.get("source_id")) != "binance":
        raise ValueError(f"dataset_source_must_be_binance:{dataset.get('source_id')}")
    if str(dataset.get("market_type")) != "um_futures":
        raise ValueError(f"dataset_market_type_must_be_um_futures:{dataset.get('market_type')}")
    return dataset


def _load_asset(dataset_id: int, symbol: str, timeframe: str) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_to_json(a)
            FROM historical_dataset_assets a
            WHERE dataset_id=%s AND symbol=%s AND timeframe=%s
            """,
            (dataset_id, symbol, timeframe),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _last_scanned_timestamp(asset: dict[str, Any]) -> datetime | None:
    metadata = asset.get("metadata_json") or {}
    phase16d = metadata.get("phase16d") or {}
    value = phase16d.get("last_timestamp")
    return _parse_time(value) if value else None


def _latest_required_open(end_time: datetime, timeframe: str) -> datetime:
    minutes = {
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
    }[timeframe]
    epoch_minutes = int(end_time.timestamp() // 60)
    aligned_minutes = epoch_minutes - (epoch_minutes % minutes)
    return datetime.fromtimestamp(aligned_minutes * 60, tz=timezone.utc)


def _asset_is_complete(asset: dict[str, Any] | None, end_time: datetime, timeframe: str) -> bool:
    if not asset or asset.get("status") != "quality_scanned":
        return False
    storage_path = Path(str(asset.get("storage_path") or ""))
    if storage_path.suffix != ".parquet" or not storage_path.is_file():
        return False
    last_timestamp = _last_scanned_timestamp(asset)
    return bool(last_timestamp and last_timestamp >= _latest_required_open(end_time, timeframe))


def _register_expansion_assets(
    *,
    dataset: dict[str, Any],
    symbols: list[str],
    timeframes: list[str],
    requested_start: datetime | None,
    end_time: datetime,
    storage_root: str,
) -> None:
    dataset_id = int(dataset["dataset_id"])
    market_type = str(dataset["market_type"])
    existing_symbols = [str(symbol).upper() for symbol in (dataset.get("symbols") or [])]
    existing_timeframes = [str(timeframe) for timeframe in (dataset.get("timeframes") or [])]
    merged_symbols = list(dict.fromkeys(existing_symbols + symbols))
    merged_timeframes = list(dict.fromkeys(existing_timeframes + timeframes))
    starts = [max(requested_start, _archive_start(symbol)) if requested_start else _archive_start(symbol) for symbol in symbols]
    expansion_start = min(starts)

    manifest_patch = {
        PIPELINE_VERSION: {
            "symbols": symbols,
            "timeframes": timeframes,
            "archive_available_from": {symbol: available_from(symbol) for symbol in symbols},
            "requested_start": requested_start.isoformat() if requested_start else "per_symbol_archive_start",
            "requested_end": end_time.isoformat(),
            "btc_eth_assets_untouched": True,
        }
    }

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_datasets
            SET symbols=%s,
                timeframes=%s,
                start_time=LEAST(start_time, %s),
                end_time=GREATEST(end_time, %s),
                manifest_json=COALESCE(manifest_json, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            WHERE dataset_id=%s
            """,
            (
                merged_symbols,
                merged_timeframes,
                expansion_start,
                end_time,
                json.dumps(manifest_patch),
                dataset_id,
            ),
        )

        for symbol in symbols:
            asset_start = _archive_start(symbol)
            if requested_start:
                asset_start = max(asset_start, requested_start)
            for timeframe in timeframes:
                expected_rows = expected_rows_for_timeframe(asset_start, end_time, timeframe)
                csv_path = f"{storage_root}/{market_type}/{symbol}/{timeframe}/candles.csv"
                asset_metadata = {
                    PIPELINE_VERSION: {
                        "archive_available_from": available_from(symbol),
                        "requested_start": asset_start.isoformat(),
                        "requested_end": end_time.isoformat(),
                    }
                }
                cur.execute(
                    """
                    INSERT INTO historical_dataset_assets (
                        dataset_id, symbol, timeframe, start_time, end_time,
                        expected_row_count, storage_path, metadata_json
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (dataset_id, symbol, timeframe)
                    DO UPDATE SET
                        start_time=EXCLUDED.start_time,
                        end_time=EXCLUDED.end_time,
                        expected_row_count=EXCLUDED.expected_row_count,
                        metadata_json=COALESCE(historical_dataset_assets.metadata_json, '{}'::jsonb) || EXCLUDED.metadata_json,
                        updated_at=NOW()
                    """,
                    (
                        dataset_id,
                        symbol,
                        timeframe,
                        asset_start,
                        end_time,
                        expected_rows,
                        csv_path,
                        json.dumps(asset_metadata),
                    ),
                )


def expand_binance_universe(
    *,
    dataset_id: int,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    storage_root: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    dataset = _load_dataset(dataset_id)
    selected_symbols = normalize_symbols(symbols or list(EXPANSION_SYMBOLS))
    selected_timeframes = normalize_timeframes(timeframes or list(EXPANSION_TIMEFRAMES))

    unsupported_symbols = sorted(set(selected_symbols) - set(EXPANSION_SYMBOLS))
    if unsupported_symbols:
        raise ValueError(f"expansion_symbols_only:{','.join(unsupported_symbols)}")
    unsupported_timeframes = sorted(set(selected_timeframes) - set(EXPANSION_TIMEFRAMES))
    if unsupported_timeframes:
        raise ValueError(f"expansion_timeframes_only:{','.join(unsupported_timeframes)}")

    selected_symbols = list(dict.fromkeys(selected_symbols))
    selected_timeframes = list(dict.fromkeys(selected_timeframes))
    end_time = end_time or _default_end_time()
    if start_time and end_time <= start_time:
        raise ValueError("end_time must be after start_time")

    resolved_storage_root = str(storage_root or dataset.get("storage_root") or DEFAULT_STORAGE_ROOT)
    plans = []
    for symbol in selected_symbols:
        asset_start = max(start_time, _archive_start(symbol)) if start_time else _archive_start(symbol)
        for timeframe in selected_timeframes:
            existing = _load_asset(dataset_id, symbol, timeframe)
            plans.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "start_time": asset_start,
                "end_time": end_time,
                "already_complete": _asset_is_complete(existing, end_time, timeframe),
            })

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "dataset_id": dataset_id,
            "pipeline_version": PIPELINE_VERSION,
            "asset_count": len(plans),
            "download_count": sum(1 for plan in plans if force or not plan["already_complete"]),
            "skip_count": sum(1 for plan in plans if not force and plan["already_complete"]),
            "plans": [
                {
                    **plan,
                    "start_time": plan["start_time"].isoformat(),
                    "end_time": plan["end_time"].isoformat(),
                }
                for plan in plans
            ],
        }

    _register_expansion_assets(
        dataset=dataset,
        symbols=selected_symbols,
        timeframes=selected_timeframes,
        requested_start=start_time,
        end_time=end_time,
        storage_root=resolved_storage_root,
    )

    completed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, plan in enumerate(plans, start=1):
        symbol = str(plan["symbol"])
        timeframe = str(plan["timeframe"])
        label = f"[{index}/{len(plans)}] {symbol} {timeframe}"
        if not force and plan["already_complete"]:
            print(f"{label} skip: existing quality-scanned Parquet covers requested end", flush=True)
            skipped.append({"symbol": symbol, "timeframe": timeframe, "reason": "already_complete"})
            continue

        try:
            print(f"{label} download", flush=True)
            download = run_download_job({
                "dataset_id": dataset_id,
                "market_type": dataset["market_type"],
                "storage_root": resolved_storage_root,
                "symbols": [symbol],
                "timeframes": [timeframe],
                "start_time": plan["start_time"].isoformat(),
                "end_time": plan["end_time"].isoformat(),
                "prefer_monthly": True,
                "requested_by": PIPELINE_VERSION,
            })
            if not download.get("ok"):
                raise RuntimeError(f"download_failed:{download.get('error')}")
            asset_results = download.get("results") or []
            if not asset_results or asset_results[0].get("status") != "downloaded":
                raise RuntimeError(f"download_no_rows:{asset_results}")

            print(f"{label} convert Parquet", flush=True)
            conversion = convert_dataset_to_parquet(
                dataset_id,
                symbols=[symbol],
                timeframes=[timeframe],
            )
            if not conversion.get("ok"):
                raise RuntimeError(f"conversion_failed:{conversion.get('results')}")
            conversion_results = conversion.get("results") or []
            if not conversion_results or conversion_results[0].get("status") != "parquet_ready":
                raise RuntimeError(f"parquet_not_ready:{conversion_results}")

            print(f"{label} quality scan", flush=True)
            scan = scan_dataset_quality(
                dataset_id,
                symbols=[symbol],
                timeframes=[timeframe],
            )
            if not scan.get("ok"):
                raise RuntimeError(f"quality_scan_failed:{scan.get('results')}")

            completed.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": int(asset_results[0].get("rows") or 0),
                "first_timestamp": asset_results[0].get("first_timestamp"),
                "last_timestamp": asset_results[0].get("last_timestamp"),
                "quality_score": (scan.get("results") or [{}])[0].get("quality_score"),
            })
        except Exception as exc:
            failure = {
                "symbol": symbol,
                "timeframe": timeframe,
                "error": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            print(f"{label} failed: {failure['error']}", flush=True)
            if not continue_on_error:
                break

    return {
        "ok": not failures,
        "dry_run": False,
        "dataset_id": dataset_id,
        "pipeline_version": PIPELINE_VERSION,
        "symbols": selected_symbols,
        "timeframes": selected_timeframes,
        "completed_count": len(completed),
        "skipped_count": len(skipped),
        "failure_count": len(failures),
        "completed": completed,
        "skipped": skipped,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register, download, convert, and quality-scan the 18-symbol Binance USD-M expansion.",
    )
    parser.add_argument("--dataset-id", required=True, type=int)
    parser.add_argument("--symbols", nargs="+", default=list(EXPANSION_SYMBOLS))
    parser.add_argument("--timeframes", nargs="+", default=list(EXPANSION_TIMEFRAMES))
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--storage-root")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    try:
        result = expand_binance_universe(
            dataset_id=args.dataset_id,
            symbols=args.symbols,
            timeframes=args.timeframes,
            start_time=_parse_time(args.start_time) if args.start_time else None,
            end_time=_parse_time(args.end_time) if args.end_time else None,
            storage_root=args.storage_root,
            force=args.force,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "pipeline_version": PIPELINE_VERSION,
        }

    print(json.dumps(result, indent=2, default=str), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
