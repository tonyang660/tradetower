
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import get_conn
from datasets.config import TIMEFRAME_MINUTES


QUALITY_SCANNER_VERSION = "phase16d_data_quality_scanner"


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt_from_ms(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(float(value)) / 1000, tz=timezone.utc)
    except Exception:
        return None


def _load_dataset(dataset_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(d) FROM historical_datasets d WHERE dataset_id=%s", (dataset_id,))
        row = cur.fetchone()
        return row[0] if row else None


def _load_assets(dataset_id: int, symbols: list[str] | None = None, timeframes: list[str] | None = None) -> list[dict[str, Any]]:
    where = ["dataset_id=%s"]
    params: list[Any] = [dataset_id]
    if symbols:
        where.append("symbol = ANY(%s)")
        params.append([str(s).upper() for s in symbols])
    if timeframes:
        where.append("timeframe = ANY(%s)")
        params.append([str(tf) for tf in timeframes])

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT row_to_json(a)
            FROM historical_dataset_assets a
            WHERE {' AND '.join(where)}
            ORDER BY symbol, timeframe
            """,
            params,
        )
        return [row[0] for row in cur.fetchall()]


def _rows_from_storage(asset: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(str(asset.get("storage_path") or ""))
    metadata = asset.get("metadata_json") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    csv_source = None
    if metadata.get("csv_source_path"):
        csv_source = Path(str(metadata.get("csv_source_path")))
    phase16c = metadata.get("phase16c") or {}
    if phase16c.get("csv_path"):
        csv_source = Path(str(phase16c.get("csv_path")))

    try:
        import pandas as pd  # type: ignore
        if path.exists() and path.suffix == ".parquet":
            return pd.read_parquet(path).to_dict(orient="records")
        if path.exists() and path.suffix == ".jsonl":
            return pd.read_json(path, lines=True).to_dict(orient="records")
    except Exception:
        pass

    fallback = csv_source if csv_source and csv_source.exists() else path
    if fallback.exists() and fallback.suffix == ".csv":
        import csv
        out = []
        with fallback.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    out.append({
                        "open_time": int(float(row["open_time"])),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                        "close_time": int(float(row.get("close_time") or 0)),
                        "number_of_trades": int(float(row.get("number_of_trades") or 0)),
                    })
                except Exception:
                    continue
        return out

    return []


def _expected_count(start: datetime, end: datetime, timeframe: str) -> int:
    minutes = TIMEFRAME_MINUTES.get(timeframe)
    if not minutes or end < start:
        return 0
    return int((end - start).total_seconds() // 60 // minutes) + 1


def _issue(severity: str, code: str, message: str, first=None, last=None, details=None):
    return {
        "severity": severity,
        "issue_code": code,
        "message": message,
        "first_timestamp": first,
        "last_timestamp": last,
        "details": details or {},
    }


def _persist_issues(dataset_id: int, asset_id: int, symbol: str, timeframe: str, issues: list[dict[str, Any]]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM historical_dataset_quality_issues
            WHERE dataset_id=%s
              AND asset_id=%s
              AND details_json->>'quality_scanner_version'=%s
            """,
            (dataset_id, asset_id, QUALITY_SCANNER_VERSION),
        )
        for issue in issues:
            cur.execute(
                """
                INSERT INTO historical_dataset_quality_issues (
                    dataset_id, asset_id, symbol, timeframe, severity,
                    issue_code, message, first_timestamp, last_timestamp, details_json
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    dataset_id,
                    asset_id,
                    symbol,
                    timeframe,
                    issue["severity"],
                    issue["issue_code"],
                    issue["message"],
                    issue.get("first_timestamp"),
                    issue.get("last_timestamp"),
                    json.dumps({
                        **(issue.get("details") or {}),
                        "quality_scanner_version": QUALITY_SCANNER_VERSION,
                    }),
                ),
            )


def _scan_asset(asset: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    dataset_id = int(asset["dataset_id"])
    asset_id = int(asset["asset_id"])
    symbol = str(asset["symbol"])
    timeframe = str(asset["timeframe"])
    rows = sorted(_rows_from_storage(asset), key=lambda r: int(float(r.get("open_time", 0) or 0)))

    issues: list[dict[str, Any]] = []

    if not rows:
        issues.append(_issue("error", "NO_ROWS", f"No rows found for {symbol} {timeframe}."))
        result = {
            "dataset_id": dataset_id, "asset_id": asset_id, "symbol": symbol, "timeframe": timeframe,
            "status": "quality_failed", "row_count": 0, "expected_row_count": int(asset.get("expected_row_count") or 0),
            "actual_missing_candles_count": int(asset.get("expected_row_count") or 0),
            "expected_archive_missing_count": 0, "duplicate_candles_count": 0, "quality_score": 0.0,
            "first_timestamp": None, "last_timestamp": None, "scan_range_start": None, "scan_range_end": None,
            "issues": issues,
        }
        _update_asset_quality(result)
        _persist_issues(dataset_id, asset_id, symbol, timeframe, issues)
        return result

    open_times = [int(float(r["open_time"])) for r in rows]
    unique_times = sorted(set(open_times))
    duplicate_count = len(open_times) - len(unique_times)

    first_dt = _dt_from_ms(unique_times[0])
    last_dt = _dt_from_ms(unique_times[-1])
    dataset_start = _parse_iso(dataset.get("start_time")) or first_dt
    dataset_end = _parse_iso(dataset.get("end_time")) or last_dt
    scan_start = max(first_dt, dataset_start) if first_dt and dataset_start else first_dt
    scan_end = last_dt

    expected_within_actual = _expected_count(scan_start, scan_end, timeframe) if scan_start and scan_end else len(unique_times)
    actual_missing = max(0, expected_within_actual - len(unique_times))
    requested_expected = _expected_count(dataset_start, dataset_end, timeframe) if dataset_start and dataset_end else expected_within_actual
    expected_archive_missing = max(0, requested_expected - expected_within_actual)

    if expected_archive_missing > 0:
        issues.append(_issue(
            "info",
            "ARCHIVE_RANGE_ENDS_BEFORE_REQUESTED_END",
            f"{symbol} {timeframe} ends at {_iso(last_dt)} while dataset requested through {_iso(dataset_end)}.",
            _iso(last_dt),
            _iso(dataset_end),
            {"expected_archive_missing_count": expected_archive_missing},
        ))

    if actual_missing > 0:
        issues.append(_issue(
            "warning",
            "INTERNAL_CANDLE_GAPS",
            f"{symbol} {timeframe} has estimated internal missing candles.",
            _iso(scan_start),
            _iso(scan_end),
            {
                "actual_missing_candles_count": actual_missing,
                "expected_within_actual_range": expected_within_actual,
                "actual_unique_rows": len(unique_times),
            },
        ))

    if duplicate_count > 0:
        issues.append(_issue("warning", "DUPLICATE_OPEN_TIMES", f"{symbol} {timeframe} has duplicate open_time rows.", details={"duplicate_candles_count": duplicate_count}))

    bad_ohlc = 0
    negative_volume = 0
    for r in rows:
        try:
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            v = float(r.get("volume", 0))
            if h < max(o, c) or l > min(o, c) or h < l:
                bad_ohlc += 1
            if v < 0:
                negative_volume += 1
        except Exception:
            bad_ohlc += 1

    if bad_ohlc:
        issues.append(_issue("error", "INVALID_OHLC", f"{symbol} {timeframe} has invalid OHLC rows.", details={"invalid_ohlc_rows": bad_ohlc}))
    if negative_volume:
        issues.append(_issue("error", "NEGATIVE_VOLUME", f"{symbol} {timeframe} has negative volume rows.", details={"negative_volume_rows": negative_volume}))

    completeness = len(unique_times) / expected_within_actual if expected_within_actual else 1.0
    quality_score = round(max(0.0, min(1.0, completeness - min(0.05, duplicate_count / max(len(rows), 1)) - min(0.25, (bad_ohlc + negative_volume) / max(len(rows), 1)))), 6)
    status = "quality_failed" if any(i["severity"] == "error" for i in issues) else "quality_scanned"

    result = {
        "dataset_id": dataset_id,
        "asset_id": asset_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "row_count": len(unique_times),
        "expected_row_count": expected_within_actual,
        "actual_missing_candles_count": actual_missing,
        "expected_archive_missing_count": expected_archive_missing,
        "duplicate_candles_count": duplicate_count,
        "quality_score": quality_score,
        "first_timestamp": _iso(first_dt),
        "last_timestamp": _iso(last_dt),
        "scan_range_start": _iso(scan_start),
        "scan_range_end": _iso(scan_end),
        "issues": issues,
    }

    _update_asset_quality(result)
    _persist_issues(dataset_id, asset_id, symbol, timeframe, issues)
    return result


def _update_asset_quality(result: dict[str, Any]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_dataset_assets
            SET status=%s,
                row_count=%s,
                expected_row_count=%s,
                missing_candles_count=%s,
                duplicate_candles_count=%s,
                quality_score=%s,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            WHERE asset_id=%s
            """,
            (
                result["status"],
                result["row_count"],
                result["expected_row_count"],
                result["actual_missing_candles_count"],
                result["duplicate_candles_count"],
                result["quality_score"],
                json.dumps({"phase16d": result, "quality_scanner_version": QUALITY_SCANNER_VERSION}),
                result["asset_id"],
            ),
        )


def refresh_dataset_quality(dataset_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE historical_datasets d
            SET row_count=COALESCE(a.row_count,d.row_count),
                expected_row_count=COALESCE(a.expected_row_count,d.expected_row_count),
                missing_candles_count=COALESCE(a.missing_candles_count,d.missing_candles_count),
                duplicate_candles_count=COALESCE(a.duplicate_candles_count,d.duplicate_candles_count),
                quality_score=a.quality_score,
                status=CASE
                    WHEN EXISTS (SELECT 1 FROM historical_dataset_assets x WHERE x.dataset_id=d.dataset_id AND x.status='quality_failed')
                    THEN 'quality_failed'
                    ELSE 'quality_scanned'
                END,
                manifest_json = COALESCE(d.manifest_json, '{}'::jsonb) || %s::jsonb,
                updated_at=NOW()
            FROM (
                SELECT dataset_id,
                       SUM(row_count)::bigint AS row_count,
                       SUM(expected_row_count)::bigint AS expected_row_count,
                       SUM(missing_candles_count)::bigint AS missing_candles_count,
                       SUM(duplicate_candles_count)::bigint AS duplicate_candles_count,
                       AVG(quality_score)::numeric(10,6) AS quality_score
                FROM historical_dataset_assets
                WHERE dataset_id=%s
                GROUP BY dataset_id
            ) a
            WHERE d.dataset_id=a.dataset_id
            """,
            (json.dumps({"phase16d": {"quality_scanner_version": QUALITY_SCANNER_VERSION}}), dataset_id),
        )


def scan_dataset_quality(dataset_id: int, symbols: list[str] | None = None, timeframes: list[str] | None = None) -> dict[str, Any]:
    dataset = _load_dataset(dataset_id)
    if not dataset:
        raise ValueError(f"dataset_not_found:{dataset_id}")
    assets = _load_assets(dataset_id, symbols=symbols, timeframes=timeframes)
    results = [_scan_asset(asset, dataset) for asset in assets]
    refresh_dataset_quality(dataset_id)
    error_count = sum(1 for r in results for i in r["issues"] if i["severity"] == "error")
    warning_count = sum(1 for r in results for i in r["issues"] if i["severity"] == "warning")
    info_count = sum(1 for r in results for i in r["issues"] if i["severity"] == "info")
    return {
        "ok": error_count == 0,
        "dataset_id": dataset_id,
        "asset_count": len(results),
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "quality_scanner_version": QUALITY_SCANNER_VERSION,
        "results": results,
    }


def quality_summary(dataset_id: int) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT row_to_json(d) FROM historical_datasets d WHERE dataset_id=%s", (dataset_id,))
        row = cur.fetchone()
        dataset = row[0] if row else None

        cur.execute(
            """
            SELECT severity, issue_code, COUNT(*)
            FROM historical_dataset_quality_issues
            WHERE dataset_id=%s
            GROUP BY severity, issue_code
            ORDER BY severity, issue_code
            """,
            (dataset_id,),
        )
        issues = [{"severity": r[0], "issue_code": r[1], "count": int(r[2])} for r in cur.fetchall()]

        cur.execute(
            """
            SELECT symbol, timeframe, status, row_count, expected_row_count,
                   missing_candles_count, duplicate_candles_count, quality_score,
                   metadata_json->'phase16d'->>'last_timestamp'
            FROM historical_dataset_assets
            WHERE dataset_id=%s
            ORDER BY symbol, timeframe
            """,
            (dataset_id,),
        )
        assets = [
            {
                "symbol": r[0], "timeframe": r[1], "status": r[2],
                "row_count": int(r[3] or 0), "expected_row_count": int(r[4] or 0),
                "missing_candles_count": int(r[5] or 0),
                "duplicate_candles_count": int(r[6] or 0),
                "quality_score": float(r[7]) if r[7] is not None else None,
                "last_timestamp": r[8],
            }
            for r in cur.fetchall()
        ]

    return {
        "ok": dataset is not None,
        "dataset": dataset,
        "issue_summary": issues,
        "assets": assets,
        "quality_scanner_version": QUALITY_SCANNER_VERSION,
    }
