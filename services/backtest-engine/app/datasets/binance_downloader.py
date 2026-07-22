
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from db import get_conn
from datasets.config import (
    BINANCE_DATA_BASE_URL,
    BINANCE_UM_DAILY_KLINES_PATH,
    BINANCE_UM_FUTURES_AVAILABLE_FROM,
    BINANCE_UM_MONTHLY_KLINES_PATH,
    DEFAULT_MARKET_TYPE,
    DEFAULT_STORAGE_ROOT,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    TIMEFRAME_MINUTES,
    available_from,
    normalize_symbols,
    normalize_timeframes,
)


@dataclass(frozen=True)
class DownloadAssetResult:
    symbol: str
    timeframe: str
    status: str
    files_downloaded: int
    files_missing: int
    rows: int
    first_timestamp: str | None
    last_timestamp: str | None
    storage_path: str | None
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_time(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _month_iter(start: datetime, end: datetime):
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        yield current.year, current.month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def _date_iter(start: datetime, end: datetime):
    current = start.date()
    last = end.date()
    while current <= last:
        yield current
        current = date.fromordinal(current.toordinal() + 1)


def _binance_monthly_url(symbol: str, timeframe: str, year: int, month: int) -> str:
    filename = f"{symbol}-{timeframe}-{year}-{month:02d}.zip"
    return f"{BINANCE_DATA_BASE_URL}/{BINANCE_UM_MONTHLY_KLINES_PATH}/{symbol}/{timeframe}/{filename}"


def _binance_daily_url(symbol: str, timeframe: str, day: date) -> str:
    filename = f"{symbol}-{timeframe}-{day.isoformat()}.zip"
    return f"{BINANCE_DATA_BASE_URL}/{BINANCE_UM_DAILY_KLINES_PATH}/{symbol}/{timeframe}/{filename}"


def _read_url_bytes(url: str, timeout: int = 60) -> bytes | None:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except URLError:
        raise


def _rows_from_zip_bytes(raw: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            return []
        with archive.open(csv_names[0]) as f:
            text = io.TextIOWrapper(f, encoding="utf-8")
            rows = list(csv.reader(text))
    # Binance kline CSV usually has no header. If a header appears, remove it.
    if rows and rows[0] and not str(rows[0][0]).isdigit():
        rows = rows[1:]
    return rows


def _row_timestamp_ms(row: list[str]) -> int:
    return int(float(row[0]))


def _write_csv_atomic(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        writer = csv.writer(tmp)
        writer.writerow([
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ])
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _asset_storage_path(storage_root: str, market_type: str, symbol: str, timeframe: str) -> Path:
    return Path(storage_root) / market_type / symbol / timeframe


def _filter_rows_for_range(rows: list[list[str]], start: datetime, end: datetime) -> list[list[str]]:
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    return [row for row in rows if start_ms <= _row_timestamp_ms(row) <= end_ms]


def _expected_rows(start: datetime, end: datetime, timeframe: str) -> int:
    minutes = TIMEFRAME_MINUTES.get(timeframe, 0)
    if not minutes:
        return 0
    return int(max(0, (end - start).total_seconds() // 60) // minutes) + 1


def download_binance_asset(
    *,
    symbol: str,
    timeframe: str,
    start_time: datetime,
    end_time: datetime,
    storage_root: str = DEFAULT_STORAGE_ROOT,
    market_type: str = DEFAULT_MARKET_TYPE,
    prefer_monthly: bool = True,
    max_files: int | None = None,
) -> DownloadAssetResult:
    symbol = symbol.upper()
    warnings: list[str] = []
    errors: list[str] = []

    available = available_from(symbol)
    if available is None:
        return DownloadAssetResult(symbol, timeframe, "unsupported_symbol", 0, 0, 0, None, None, None, [], [f"unsupported_symbol:{symbol}"])

    available_dt = _parse_time(available + "T00:00:00Z", datetime(1970, 1, 1, tzinfo=timezone.utc))
    if start_time < available_dt:
        warnings.append(f"start_time_clamped_to_available_from:{available}")
        start_time = available_dt

    if end_time <= start_time:
        return DownloadAssetResult(symbol, timeframe, "empty_range", 0, 0, 0, None, None, None, warnings, ["end_time_before_available_start"])

    rows_all: list[list[str]] = []
    files_downloaded = 0
    files_missing = 0

    if prefer_monthly:
        periods = list(_month_iter(start_time, end_time))
        for year, month in periods:
            if max_files is not None and files_downloaded + files_missing >= max_files:
                warnings.append("max_files_reached")
                break
            url = _binance_monthly_url(symbol, timeframe, year, month)
            raw = _read_url_bytes(url)
            if raw is None:
                files_missing += 1
                continue
            rows_all.extend(_rows_from_zip_bytes(raw))
            files_downloaded += 1
    else:
        days = list(_date_iter(start_time, end_time))
        for day in days:
            if max_files is not None and files_downloaded + files_missing >= max_files:
                warnings.append("max_files_reached")
                break
            url = _binance_daily_url(symbol, timeframe, day)
            raw = _read_url_bytes(url)
            if raw is None:
                files_missing += 1
                continue
            rows_all.extend(_rows_from_zip_bytes(raw))
            files_downloaded += 1

    rows = _filter_rows_for_range(rows_all, start_time, end_time)
    rows.sort(key=_row_timestamp_ms)

    # De-duplicate by open_time.
    deduped = {}
    for row in rows:
        deduped[_row_timestamp_ms(row)] = row
    rows = [deduped[key] for key in sorted(deduped.keys())]

    storage_dir = _asset_storage_path(storage_root, market_type, symbol, timeframe)
    output_path = storage_dir / "candles.csv"
    if rows:
        _write_csv_atomic(output_path, rows)

    first_ts = datetime.fromtimestamp(_row_timestamp_ms(rows[0]) / 1000, tz=timezone.utc).isoformat() if rows else None
    last_ts = datetime.fromtimestamp(_row_timestamp_ms(rows[-1]) / 1000, tz=timezone.utc).isoformat() if rows else None
    expected = _expected_rows(start_time, end_time, timeframe)
    missing_estimate = max(0, expected - len(rows))

    if missing_estimate:
        warnings.append(f"estimated_missing_candles:{missing_estimate}")

    status = "downloaded" if rows else "no_rows_downloaded"

    return DownloadAssetResult(
        symbol=symbol,
        timeframe=timeframe,
        status=status,
        files_downloaded=files_downloaded,
        files_missing=files_missing,
        rows=len(rows),
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        storage_path=str(output_path) if rows else str(storage_dir),
        warnings=warnings,
        errors=errors,
    )


def update_asset_metadata(dataset_id: int, result: DownloadAssetResult, expected_rows: int | None = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_dataset_assets
            SET
                row_count=%s,
                expected_row_count=COALESCE(%s, expected_row_count),
                missing_candles_count=GREATEST(COALESCE(%s, expected_row_count) - %s, 0),
                file_count=%s,
                storage_path=%s,
                status=%s,
                metadata_json=%s::jsonb,
                updated_at=NOW()
            WHERE dataset_id=%s
              AND symbol=%s
              AND timeframe=%s
            """,
            (
                result.rows,
                expected_rows,
                expected_rows,
                result.rows,
                result.files_downloaded,
                result.storage_path,
                result.status,
                json.dumps(result.to_dict()),
                dataset_id,
                result.symbol,
                result.timeframe,
            ),
        )


def refresh_dataset_rollup(dataset_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_datasets d
            SET
                row_count = COALESCE(a.row_count, 0),
                expected_row_count = COALESCE(a.expected_row_count, 0),
                missing_candles_count = COALESCE(a.missing_candles_count, 0),
                status = CASE
                    WHEN COALESCE(a.row_count, 0) > 0 THEN 'downloaded'
                    ELSE d.status
                END,
                updated_at = NOW()
            FROM (
                SELECT
                    dataset_id,
                    SUM(row_count)::bigint AS row_count,
                    SUM(expected_row_count)::bigint AS expected_row_count,
                    SUM(missing_candles_count)::bigint AS missing_candles_count
                FROM historical_dataset_assets
                WHERE dataset_id=%s
                GROUP BY dataset_id
            ) a
            WHERE d.dataset_id = a.dataset_id
            """,
            (dataset_id,),
        )


def run_download_job(payload: dict[str, Any]) -> dict[str, Any]:
    dataset_id = payload.get("dataset_id")
    if dataset_id is None:
        raise ValueError("dataset_id is required for Phase 16B downloads")

    market_type = str(payload.get("market_type") or DEFAULT_MARKET_TYPE)
    storage_root = str(payload.get("storage_root") or DEFAULT_STORAGE_ROOT)
    symbols = normalize_symbols(payload.get("symbols") or DEFAULT_SYMBOLS)
    timeframes = normalize_timeframes(payload.get("timeframes") or DEFAULT_TIMEFRAMES)
    start_time = _parse_time(payload.get("start_time"), datetime(2021, 1, 1, tzinfo=timezone.utc))
    end_time = _parse_time(payload.get("end_time"), datetime.now(timezone.utc))
    prefer_monthly = bool(payload.get("prefer_monthly", True))
    max_files_per_asset = payload.get("max_files_per_asset")
    max_files_per_asset = int(max_files_per_asset) if max_files_per_asset is not None else None

    results: list[dict[str, Any]] = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO historical_dataset_download_jobs (
                dataset_id, source_id, market_type, symbols, timeframes,
                start_time, end_time, status, requested_by, progress_json, started_at
            )
            VALUES (%s,'binance',%s,%s,%s,%s,%s,'running',%s,%s::jsonb,NOW())
            RETURNING job_id
            """,
            (
                dataset_id,
                market_type,
                symbols,
                timeframes,
                start_time,
                end_time,
                payload.get("requested_by", "manual"),
                json.dumps({"phase": "16B", "status": "running"}),
            ),
        )
        job_id = int(cur.fetchone()[0])

    ok = True
    error = None

    try:
        for symbol in symbols:
            for timeframe in timeframes:
                asset_start = start_time
                available = BINANCE_UM_FUTURES_AVAILABLE_FROM.get(symbol)
                if available:
                    available_dt = _parse_time(available + "T00:00:00Z", start_time)
                    if asset_start < available_dt:
                        asset_start = available_dt

                expected = _expected_rows(asset_start, end_time, timeframe)
                result = download_binance_asset(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=asset_start,
                    end_time=end_time,
                    storage_root=storage_root,
                    market_type=market_type,
                    prefer_monthly=prefer_monthly,
                    max_files=max_files_per_asset,
                )
                update_asset_metadata(int(dataset_id), result, expected_rows=expected)
                results.append(result.to_dict())

        refresh_dataset_rollup(int(dataset_id))
        status = "completed"

    except Exception as exc:
        ok = False
        error = str(exc)
        status = "failed"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_dataset_download_jobs
            SET status=%s,
                completed_at=NOW(),
                error=%s,
                progress_json=%s::jsonb
            WHERE job_id=%s
            """,
            (
                status,
                error,
                json.dumps({
                    "phase": "16B",
                    "ok": ok,
                    "asset_results": results,
                }),
                job_id,
            ),
        )

    return {
        "ok": ok,
        "job_id": job_id,
        "dataset_id": dataset_id,
        "status": status,
        "results": results,
        "error": error,
    }
