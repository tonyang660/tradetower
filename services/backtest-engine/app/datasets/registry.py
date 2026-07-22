
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db import get_conn
from datasets.config import (
    DEFAULT_DATASET_SOURCE,
    DEFAULT_MARKET_TYPE,
    DEFAULT_QUOTE_ASSET,
    DEFAULT_STORAGE_ROOT,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    TIMEFRAME_MINUTES,
    normalize_symbols,
    normalize_timeframes,
)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _parse_time(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dataset_key(
    *,
    source_id: str,
    market_type: str,
    quote_asset: str,
    start_time: datetime,
    end_time: datetime,
    symbols: list[str],
    timeframes: list[str],
) -> str:
    sym_hash = "-".join(symbols[:5]) + (f"-plus{len(symbols)-5}" if len(symbols) > 5 else "")
    tf_hash = "-".join(timeframes)
    return (
        f"{source_id}:{market_type}:{quote_asset}:"
        f"{start_time.date()}:{end_time.date()}:{tf_hash}:{sym_hash}"
    )


def expected_rows_for_timeframe(start_time: datetime, end_time: datetime, timeframe: str) -> int:
    minutes = TIMEFRAME_MINUTES.get(timeframe)
    if not minutes:
        return 0
    delta_minutes = max(0.0, (end_time - start_time).total_seconds() / 60.0)
    return int(delta_minutes // minutes) + 1


def list_dataset_sources() -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_to_json(s)
            FROM historical_dataset_sources s
            ORDER BY priority, source_id
            """
        )
        return [row[0] for row in cur.fetchall()]


def list_datasets(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_to_json(d)
            FROM historical_datasets d
            ORDER BY dataset_id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]


def get_dataset(dataset_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(d) FROM historical_datasets d WHERE dataset_id=%s", (dataset_id,))
        row = cur.fetchone()
        if not row:
            return None

        dataset = row[0]
        cur.execute(
            """
            SELECT row_to_json(a)
            FROM historical_dataset_assets a
            WHERE dataset_id=%s
            ORDER BY symbol, timeframe
            """,
            (dataset_id,),
        )
        dataset["assets"] = [asset[0] for asset in cur.fetchall()]

        cur.execute(
            """
            SELECT row_to_json(i)
            FROM historical_dataset_quality_issues i
            WHERE dataset_id=%s
            ORDER BY severity, issue_id
            LIMIT 500
            """,
            (dataset_id,),
        )
        dataset["quality_issues"] = [issue[0] for issue in cur.fetchall()]
        return dataset


def register_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    source_id = str(payload.get("source_id") or DEFAULT_DATASET_SOURCE)
    if source_id != "binance":
        raise ValueError("Phase 16A supports only source_id=binance")

    market_type = str(payload.get("market_type") or DEFAULT_MARKET_TYPE)
    quote_asset = str(payload.get("quote_asset") or DEFAULT_QUOTE_ASSET)
    symbols = normalize_symbols(payload.get("symbols") or DEFAULT_SYMBOLS)
    timeframes = normalize_timeframes(payload.get("timeframes") or DEFAULT_TIMEFRAMES)

    start_default = datetime(2021, 1, 1, tzinfo=timezone.utc)
    end_default = datetime.now(timezone.utc)

    start_time = _parse_time(payload.get("start_time"), start_default)
    end_time = _parse_time(payload.get("end_time"), end_default)

    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")

    key = payload.get("dataset_key") or dataset_key(
        source_id=source_id,
        market_type=market_type,
        quote_asset=quote_asset,
        start_time=start_time,
        end_time=end_time,
        symbols=symbols,
        timeframes=timeframes,
    )

    expected_total = 0
    asset_specs = []
    for symbol in symbols:
        for timeframe in timeframes:
            expected = expected_rows_for_timeframe(start_time, end_time, timeframe)
            expected_total += expected
            asset_specs.append((symbol, timeframe, expected))

    manifest = {
        "phase": "16A",
        "source_id": source_id,
        "source_policy": "binance_only",
        "market_type": market_type,
        "quote_asset": quote_asset,
        "symbols": symbols,
        "timeframes": timeframes,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "storage_format": "parquet",
        "storage_root": payload.get("storage_root") or DEFAULT_STORAGE_ROOT,
        "expected_total_rows": expected_total,
        "notes": payload.get("notes"),
        "candidate_filter_phase": "16F",
    }

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO historical_datasets (
                dataset_key, source_id, market_type, quote_asset, symbols, timeframes,
                start_time, end_time, storage_format, storage_root,
                expected_row_count, manifest_json, notes
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'parquet',%s,%s,%s::jsonb,%s)
            ON CONFLICT (dataset_key)
            DO UPDATE SET
                symbols=EXCLUDED.symbols,
                timeframes=EXCLUDED.timeframes,
                start_time=EXCLUDED.start_time,
                end_time=EXCLUDED.end_time,
                expected_row_count=EXCLUDED.expected_row_count,
                manifest_json=EXCLUDED.manifest_json,
                notes=EXCLUDED.notes,
                updated_at=NOW()
            RETURNING dataset_id
            """,
            (
                key,
                source_id,
                market_type,
                quote_asset,
                symbols,
                timeframes,
                start_time,
                end_time,
                payload.get("storage_root") or DEFAULT_STORAGE_ROOT,
                expected_total,
                _json(manifest),
                payload.get("notes"),
            ),
        )
        dataset_id = int(cur.fetchone()[0])

        for symbol, timeframe, expected in asset_specs:
            storage_path = (
                f"{payload.get('storage_root') or DEFAULT_STORAGE_ROOT}/"
                f"{market_type}/{symbol}/{timeframe}"
            )
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
                    storage_path=EXCLUDED.storage_path,
                    metadata_json=EXCLUDED.metadata_json,
                    updated_at=NOW()
                """,
                (
                    dataset_id,
                    symbol,
                    timeframe,
                    start_time,
                    end_time,
                    expected,
                    storage_path,
                    _json({
                        "source_id": source_id,
                        "market_type": market_type,
                        "quote_asset": quote_asset,
                        "phase": "16A_registered_only",
                    }),
                ),
            )

    return {
        "ok": True,
        "dataset_id": dataset_id,
        "dataset_key": key,
        "expected_row_count": expected_total,
        "asset_count": len(asset_specs),
        "manifest": manifest,
    }


def create_download_job(payload: dict[str, Any]) -> dict[str, Any]:
    source_id = str(payload.get("source_id") or DEFAULT_DATASET_SOURCE)
    if source_id != "binance":
        raise ValueError("Phase 16A supports only source_id=binance")

    market_type = str(payload.get("market_type") or DEFAULT_MARKET_TYPE)
    symbols = normalize_symbols(payload.get("symbols") or DEFAULT_SYMBOLS)
    timeframes = normalize_timeframes(payload.get("timeframes") or DEFAULT_TIMEFRAMES)
    start_time = _parse_time(payload.get("start_time"), datetime(2021, 1, 1, tzinfo=timezone.utc))
    end_time = _parse_time(payload.get("end_time"), datetime.now(timezone.utc))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO historical_dataset_download_jobs (
                dataset_id, source_id, market_type, symbols, timeframes,
                start_time, end_time, requested_by, progress_json
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            RETURNING job_id
            """,
            (
                payload.get("dataset_id"),
                source_id,
                market_type,
                symbols,
                timeframes,
                start_time,
                end_time,
                payload.get("requested_by"),
                _json({"phase": "16A_queued_only", "message": "Downloader implemented in Phase 16B."}),
            ),
        )
        job_id = int(cur.fetchone()[0])

    return {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "message": "Download job registered. Actual Binance downloader is Phase 16B.",
    }


def dataset_defaults() -> dict[str, Any]:
    return {
        "source_id": DEFAULT_DATASET_SOURCE,
        "market_type": DEFAULT_MARKET_TYPE,
        "quote_asset": DEFAULT_QUOTE_ASSET,
        "storage_root": DEFAULT_STORAGE_ROOT,
        "symbols": DEFAULT_SYMBOLS,
        "timeframes": DEFAULT_TIMEFRAMES,
        "strategy_parity_timeframes": {
            "entry": "5m",
            "primary": "15m",
            "context": "1h",
            "htf": "4h",
        },
        "candidate_filter": {
            "replicate_in_phase": "16F",
            "role": "upstream universe/candidate ranking before strategy evaluation",
        },
    }
