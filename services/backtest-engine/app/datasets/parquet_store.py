from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import get_conn

PARQUET_STORE_VERSION = "phase16c_parquet_candle_store"

CSV_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume", "ignore",
]
NUMERIC_COLUMNS = [
    "open", "high", "low", "close", "volume", "quote_asset_volume",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume",
]


@dataclass(frozen=True)
class ParquetConvertResult:
    dataset_id: int
    asset_id: int
    symbol: str
    timeframe: str
    status: str
    csv_path: str
    parquet_path: str | None
    row_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    quality_score: float | None
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso_from_ms(value: int | float | str | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(float(value)) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            try:
                clean: dict[str, Any] = {key: row.get(key) for key in CSV_COLUMNS}
                clean["open_time"] = int(float(clean["open_time"]))
                clean["close_time"] = int(float(clean["close_time"]))
                clean["number_of_trades"] = int(float(clean["number_of_trades"] or 0))
                for col in NUMERIC_COLUMNS:
                    clean[col] = float(clean[col])
                clean["timestamp"] = _iso_from_ms(clean["open_time"])
                rows.append(clean)
            except Exception:
                continue
    rows.sort(key=lambda item: item["open_time"])
    deduped: dict[int, dict[str, Any]] = {}
    for row in rows:
        deduped[int(row["open_time"])] = row
    return [deduped[key] for key in sorted(deduped.keys())]


def _write_parquet_or_json(rows: list[dict[str, Any]], output_path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pandas as pd  # type: ignore
        df = pd.DataFrame(rows)
        try:
            df.to_parquet(output_path, index=False)
            return str(output_path), warnings
        except Exception as exc:
            fallback = output_path.with_suffix(".jsonl")
            warnings.append(f"parquet_engine_unavailable_jsonl_fallback:{exc}")
            df.to_json(fallback, orient="records", lines=True)
            return str(fallback), warnings
    except Exception as exc:
        fallback = output_path.with_suffix(".jsonl")
        warnings.append(f"pandas_unavailable_jsonl_fallback:{exc}")
        with fallback.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, default=str) + "\n")
        return str(fallback), warnings


def _quality_score(row_count: int, expected_row_count: int | None) -> float | None:
    if not expected_row_count or expected_row_count <= 0:
        return None
    return round(min(1.0, max(0.0, row_count / expected_row_count)), 6)


def list_dataset_assets(dataset_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_to_json(a)
            FROM historical_dataset_assets a
            WHERE dataset_id=%s
            ORDER BY symbol, timeframe
            """,
            (dataset_id,),
        )
        return [row[0] for row in cur.fetchall()]


def convert_asset_to_parquet(asset: dict[str, Any]) -> ParquetConvertResult:
    dataset_id = int(asset["dataset_id"])
    asset_id = int(asset["asset_id"])
    symbol = str(asset["symbol"])
    timeframe = str(asset["timeframe"])
    csv_path = Path(str(asset.get("storage_path") or ""))

    if not csv_path.exists():
        return ParquetConvertResult(dataset_id, asset_id, symbol, timeframe, "missing_csv", str(csv_path), None, 0, None, None, None, [], [f"csv_not_found:{csv_path}"])

    rows = _read_csv_rows(csv_path)
    if not rows:
        return ParquetConvertResult(dataset_id, asset_id, symbol, timeframe, "no_rows", str(csv_path), None, 0, None, None, 0.0, [], ["no_rows_loaded_from_csv"])

    parquet_path = csv_path.parent / "candles.parquet"
    written_path, warnings = _write_parquet_or_json(rows, parquet_path)
    row_count = len(rows)

    try:
        expected_int = int(asset.get("expected_row_count")) if asset.get("expected_row_count") is not None else None
    except Exception:
        expected_int = None

    score = _quality_score(row_count, expected_int)
    status = "parquet_ready" if written_path.endswith(".parquet") else "jsonl_fallback_ready"

    result = ParquetConvertResult(
        dataset_id=dataset_id,
        asset_id=asset_id,
        symbol=symbol,
        timeframe=timeframe,
        status=status,
        csv_path=str(csv_path),
        parquet_path=written_path,
        row_count=row_count,
        first_timestamp=_iso_from_ms(rows[0]["open_time"]),
        last_timestamp=_iso_from_ms(rows[-1]["open_time"]),
        quality_score=score,
        warnings=warnings,
        errors=[],
    )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_dataset_assets
            SET storage_path=%s,
                storage_format=%s,
                row_count=%s,
                quality_score=%s,
                status=%s,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            WHERE asset_id=%s
            """,
            (
                written_path,
                "parquet" if status == "parquet_ready" else "jsonl",
                row_count,
                score,
                status,
                json.dumps({"phase16c": result.to_dict(), "csv_source_path": str(csv_path), "parquet_store_version": PARQUET_STORE_VERSION}),
                asset_id,
            ),
        )
    return result


def refresh_dataset_after_conversion(dataset_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_datasets d
            SET storage_format='parquet',
                status = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM historical_dataset_assets a
                        WHERE a.dataset_id=d.dataset_id
                          AND a.status IN ('parquet_ready', 'jsonl_fallback_ready')
                    ) THEN 'parquet_ready'
                    ELSE d.status
                END,
                row_count = COALESCE(a.row_count, d.row_count),
                quality_score = a.quality_score,
                manifest_json = COALESCE(d.manifest_json, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            FROM (
                SELECT dataset_id,
                       SUM(row_count)::bigint AS row_count,
                       AVG(quality_score)::numeric(10,6) AS quality_score
                FROM historical_dataset_assets
                WHERE dataset_id=%s
                GROUP BY dataset_id
            ) a
            WHERE d.dataset_id=a.dataset_id
            """,
            (json.dumps({"phase16c": {"parquet_store_version": PARQUET_STORE_VERSION}}), dataset_id),
        )


def convert_dataset_to_parquet(dataset_id: int, symbols: list[str] | None = None, timeframes: list[str] | None = None) -> dict[str, Any]:
    assets = list_dataset_assets(dataset_id)
    if symbols:
        symbols_set = {str(s).upper() for s in symbols}
        assets = [asset for asset in assets if str(asset["symbol"]).upper() in symbols_set]
    if timeframes:
        tf_set = {str(tf) for tf in timeframes}
        assets = [asset for asset in assets if str(asset["timeframe"]) in tf_set]

    results = [convert_asset_to_parquet(asset).to_dict() for asset in assets]
    refresh_dataset_after_conversion(dataset_id)
    return {
        "ok": all(not result.get("errors") for result in results),
        "dataset_id": dataset_id,
        "asset_count": len(results),
        "results": results,
        "parquet_store_version": PARQUET_STORE_VERSION,
    }


def read_candles(*, symbol: str, timeframe: str, dataset_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 5000))
    with get_conn() as conn, conn.cursor() as cur:
        if dataset_id:
            cur.execute(
                """
                SELECT storage_path, metadata_json->>'csv_source_path' AS csv_source_path
                FROM historical_dataset_assets
                WHERE dataset_id=%s AND symbol=%s AND timeframe=%s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (dataset_id, symbol.upper(), timeframe),
            )
        else:
            cur.execute(
                """
                SELECT storage_path, metadata_json->>'csv_source_path' AS csv_source_path
                FROM historical_dataset_assets
                WHERE symbol=%s AND timeframe=%s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol.upper(), timeframe),
            )
        row = cur.fetchone()
    if not row:
        return []

    storage_path = Path(row[0])
    csv_source = Path(row[1]) if row[1] else None
    try:
        import pandas as pd  # type: ignore
        if storage_path.suffix == ".parquet" and storage_path.exists():
            return pd.read_parquet(storage_path).tail(limit).to_dict(orient="records")
        if storage_path.suffix == ".jsonl" and storage_path.exists():
            return pd.read_json(storage_path, lines=True).tail(limit).to_dict(orient="records")
    except Exception:
        pass

    fallback = csv_source if csv_source and csv_source.exists() else storage_path
    if fallback.exists() and fallback.suffix == ".csv":
        return _read_csv_rows(fallback)[-limit:]
    return []
