
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import get_conn

LOCAL_DATASET_ADAPTER_VERSION = "phase16e_local_historical_dataset_adapter"

@dataclass(frozen=True)
class LocalCandle:
    timestamp: datetime
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    row: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    else:
        raw = str(value)
        if raw.isdigit():
            dt = datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _row_timestamp(row: dict[str, Any]) -> datetime:
    for key in ("timestamp", "open_time", "time", "datetime"):
        if row.get(key) is not None:
            return _parse_datetime(row[key])
    raise ValueError("row_missing_timestamp")

def _load_asset(dataset_id: int, symbol: str, timeframe: str) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_to_json(a)
            FROM historical_dataset_assets a
            WHERE dataset_id=%s AND symbol=%s AND timeframe=%s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (dataset_id, symbol.upper(), timeframe),
        )
        row = cur.fetchone()
        return row[0] if row else None

def _read_storage(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if p.suffix == ".parquet":
        import pandas as pd  # type: ignore
        return pd.read_parquet(p).to_dict(orient="records")
    if p.suffix == ".jsonl":
        import pandas as pd  # type: ignore
        return pd.read_json(p, lines=True).to_dict(orient="records")
    if p.suffix == ".csv":
        import csv
        with p.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"unsupported_storage_file:{p}")

def load_candles(
    *,
    dataset_id: int,
    symbol: str,
    timeframe: str,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    limit: int | None = None,
) -> list[LocalCandle]:
    asset = _load_asset(dataset_id, symbol, timeframe)
    if not asset:
        raise ValueError(f"dataset_asset_not_found:{dataset_id}:{symbol}:{timeframe}")

    rows = _read_storage(str(asset["storage_path"]))
    start_dt = _parse_datetime(start_time) if start_time else None
    end_dt = _parse_datetime(end_time) if end_time else None

    out: list[LocalCandle] = []
    for row in rows:
        ts = _row_timestamp(row)
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt:
            continue
        out.append(LocalCandle(
            timestamp=ts,
            symbol=symbol.upper(),
            timeframe=timeframe,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0.0)),
            row=row,
        ))
    out.sort(key=lambda c: c.timestamp)
    if limit is not None:
        out = out[:max(0, int(limit))]
    return out

def dataset_assets_summary(dataset_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol,timeframe,status,COALESCE(storage_format,'parquet'),row_count,quality_score,storage_path,
                   metadata_json->'phase16d'->>'first_timestamp',
                   metadata_json->'phase16d'->>'last_timestamp'
            FROM historical_dataset_assets
            WHERE dataset_id=%s
            ORDER BY symbol,timeframe
            """,
            (dataset_id,),
        )
        rows = cur.fetchall()
    return [{
        "symbol": r[0], "timeframe": r[1], "status": r[2], "storage_format": r[3],
        "row_count": int(r[4] or 0), "quality_score": float(r[5]) if r[5] is not None else None,
        "storage_path": r[6], "first_timestamp": r[7], "last_timestamp": r[8],
    } for r in rows]

def validate_local_dataset_request(
    *,
    dataset_id: int,
    symbols: list[str],
    timeframes: list[str],
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> dict[str, Any]:
    missing = []
    not_ready = []
    coverage: dict[str, dict[str, Any]] = {}
    start_dt = _parse_datetime(start_time) if start_time else None
    end_dt = _parse_datetime(end_time) if end_time else None

    for symbol in [str(s).upper() for s in symbols]:
        coverage[symbol] = {}
        for timeframe in [str(tf) for tf in timeframes]:
            asset = _load_asset(dataset_id, symbol, timeframe)
            if not asset:
                missing.append({"symbol": symbol, "timeframe": timeframe})
                coverage[symbol][timeframe] = {"available": False, "reason": "asset_not_found"}
                continue

            ready = asset.get("status") in {"quality_scanned", "parquet_ready", "downloaded"}
            if not ready:
                not_ready.append({"symbol": symbol, "timeframe": timeframe, "status": asset.get("status")})

            meta = asset.get("metadata_json") or {}
            phase16d = meta.get("phase16d") or {}
            first_ts = phase16d.get("first_timestamp")
            last_ts = phase16d.get("last_timestamp")
            first_dt = _parse_datetime(first_ts) if first_ts else None
            last_dt = _parse_datetime(last_ts) if last_ts else None

            range_warning = None
            range_ok = True
            if start_dt and first_dt and start_dt < first_dt:
                range_ok = False
                range_warning = "request_start_before_asset_start"
            if end_dt and last_dt and end_dt > last_dt:
                range_warning = "request_end_after_asset_end"

            coverage[symbol][timeframe] = {
                "available": True,
                "ready": ready,
                "status": asset.get("status"),
                "storage_format": asset.get("storage_format"),
                "row_count": asset.get("row_count"),
                "quality_score": float(asset["quality_score"]) if asset.get("quality_score") is not None else None,
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
                "range_ok": range_ok,
                "range_warning": range_warning,
            }

    return {
        "ok": not missing and not not_ready,
        "dataset_id": dataset_id,
        "symbols": symbols,
        "timeframes": timeframes,
        "missing": missing,
        "not_ready": not_ready,
        "coverage": coverage,
        "adapter_version": LOCAL_DATASET_ADAPTER_VERSION,
    }
