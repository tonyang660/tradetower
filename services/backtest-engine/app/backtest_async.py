
from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from runner import run_backtest

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _public(job: dict[str, Any]) -> dict[str, Any]:
    """Return only JSON-safe/public job fields.

    Do not deepcopy the whole job because it contains thread/cancel_event objects,
    and those contain internal locks that cannot be copied or JSON-serialized.
    """
    public_keys = [
        "ok",
        "job_id",
        "status",
        "run_id",
        "created_at",
        "started_at",
        "completed_at",
        "elapsed_seconds",
        "estimated_remaining_seconds",
        "progress_pct",
        "candles_processed",
        "cycles_processed",
        "trades_generated",
        "current_simulated_date",
        "current_status",
        "logs",
        "payload",
        "result",
        "error",
        "cancel_requested",
    ]

    return {key: job.get(key) for key in public_keys if key in job}


def _elapsed(job: dict[str, Any]) -> float:
    start = job.get("started_at_monotonic")
    if not start:
        return float(job.get("elapsed_seconds") or 0.0)
    return max(0.0, time.monotonic() - float(start))


def start_backtest_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    job: dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "run_id": None,
        "created_at": _now(),
        "started_at": None,
        "completed_at": None,
        "started_at_monotonic": None,
        "elapsed_seconds": 0.0,
        "estimated_remaining_seconds": None,
        "progress_pct": 0.0,
        "candles_processed": 0,
        "cycles_processed": 0,
        "trades_generated": 0,
        "current_simulated_date": None,
        "current_status": "queued",
        "logs": [{"timestamp": _now(), "level": "INFO", "event_type": "ASYNC_JOB_CREATED", "message": "Backtest async job queued."}],
        "payload": deepcopy(payload),
        "result": None,
        "error": None,
        "cancel_requested": False,
        "cancel_event": cancel_event,
        "thread": None,
    }

    def progress_callback(event: dict[str, Any]) -> None:
        with _LOCK:
            existing = _JOBS.get(job_id)
            if not existing:
                return
            elapsed = _elapsed(existing)
            pct = max(0.0, min(100.0, float(event.get("progress_pct", existing.get("progress_pct", 0.0)) or 0.0)))
            eta = None
            if 0 < pct < 100 and elapsed > 0:
                eta = max(0.0, elapsed * (100.0 - pct) / pct)
            existing.update({
                "status": event.get("status", existing.get("status", "running")),
                "run_id": event.get("run_id", existing.get("run_id")),
                "elapsed_seconds": elapsed,
                "estimated_remaining_seconds": eta,
                "progress_pct": pct,
                "candles_processed": int(event.get("candles_processed", existing.get("candles_processed", 0)) or 0),
                "cycles_processed": int(event.get("cycles_processed", existing.get("cycles_processed", 0)) or 0),
                "trades_generated": int(event.get("trades_generated", existing.get("trades_generated", 0)) or 0),
                "current_simulated_date": event.get("current_simulated_date", existing.get("current_simulated_date")),
                "current_status": event.get("message", event.get("status", existing.get("current_status", "running"))),
            })
            log = event.get("log")
            if log:
                existing.setdefault("logs", []).append(log)
                existing["logs"] = existing["logs"][-200:]

    def worker() -> None:
        with _LOCK:
            job = _JOBS[job_id]
            job["status"] = "running"
            job["started_at"] = _now()
            job["started_at_monotonic"] = time.monotonic()
            job["current_status"] = "running"
            job["logs"].append({"timestamp": _now(), "level": "INFO", "event_type": "ASYNC_JOB_STARTED", "message": "Backtest async job started."})
        try:
            result = run_backtest(payload, progress_callback=progress_callback, cancel_event=cancel_event)
            with _LOCK:
                job = _JOBS[job_id]
                cancelled = bool(result.get("cancelled"))
                job.update({
                    "status": "cancelled" if cancelled else "completed" if result.get("ok") else "failed",
                    "current_status": "cancelled" if cancelled else "completed" if result.get("ok") else "failed",
                    "run_id": result.get("run_id") or job.get("run_id"),
                    "completed_at": _now(),
                    "elapsed_seconds": _elapsed(job),
                    "estimated_remaining_seconds": 0.0,
                    "progress_pct": 100.0 if result.get("ok") else job.get("progress_pct", 0.0),
                    "result": result,
                    "error": result.get("error"),
                })
                job["logs"].append({"timestamp": _now(), "level": "INFO" if result.get("ok") else "ERROR", "event_type": "ASYNC_JOB_FINISHED", "message": "Backtest async job finished."})
        except Exception as exc:
            with _LOCK:
                job = _JOBS[job_id]
                job.update({
                    "status": "failed",
                    "current_status": "failed",
                    "completed_at": _now(),
                    "elapsed_seconds": _elapsed(job),
                    "estimated_remaining_seconds": 0.0,
                    "error": str(exc),
                    "result": {"ok": False, "error": "async_worker_failed", "details": str(exc)},
                })
                job["logs"].append({"timestamp": _now(), "level": "ERROR", "event_type": "ASYNC_JOB_EXCEPTION", "message": str(exc)})

    thread = threading.Thread(target=worker, name=f"backtest-job-{job_id[:8]}", daemon=True)
    job["thread"] = thread
    with _LOCK:
        _JOBS[job_id] = job
    thread.start()
    return {"ok": True, "job_id": job_id, "job": _public(job)}


def get_backtest_job(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(str(job_id))
        if not job:
            return {"ok": False, "error": "job_not_found", "job_id": job_id}
        if job.get("status") == "running":
            job["elapsed_seconds"] = _elapsed(job)
        return {"ok": True, "job_id": job_id, "job": _public(job)}


def cancel_backtest_job(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(str(job_id))
        if not job:
            return {"ok": False, "error": "job_not_found", "job_id": job_id}
        job["cancel_requested"] = True
        job["current_status"] = "cancel_requested"
        cancel_event = job.get("cancel_event")
        if cancel_event:
            cancel_event.set()
        job["logs"].append({"timestamp": _now(), "level": "WARN", "event_type": "ASYNC_JOB_CANCEL_REQUESTED", "message": "Cancel requested by dashboard."})
        return {"ok": True, "job_id": job_id, "job": _public(job)}
