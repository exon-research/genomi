from __future__ import annotations

import argparse
import contextlib
import os
import signal
import threading
import traceback
from pathlib import Path
from typing import Any

from ..operations import OperationError, call_operation
from .background_jobs import (
    HEARTBEAT_INTERVAL_SECONDS,
    read_job,
    record_heartbeat,
    write_job,
)
from .external import utc_now

JsonObject = dict[str, Any]

# Signals worth catching so a terminated worker records a `failed` status
# instead of leaving the job stuck on `running` forever. SIGKILL cannot be
# caught — the heartbeat-staleness check in background_jobs covers that.
_TERMINATION_SIGNALS = ("SIGTERM", "SIGINT", "SIGHUP")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Genomi operation background job.")
    parser.add_argument("--job", required=True, help="Path to a Genomi background job JSON file.")
    args = parser.parse_args(argv)
    job_path = Path(args.job)

    stop_heartbeat = threading.Event()
    _install_termination_handlers(job_path, stop_heartbeat)

    try:
        job = read_job(job_path=job_path)
        operation = str(job.get("operation") or "")
        params = job.get("params") or {}
        if not operation:
            raise OperationError("invalid_background_job", "background job is missing operation")
        if not isinstance(params, dict):
            raise OperationError("invalid_background_job", "background job params must be an object")

        now = utc_now()
        job.update({"status": "running", "pid": os.getpid(), "started_at": job.get("started_at") or now, "heartbeat_at": now, "updated_at": now})
        write_job(job_path, job)

        # Bump the heartbeat on a side thread so liveness stays visible even
        # while call_operation makes no externally observable progress (e.g. a
        # multi-worker parse whose merge has not started).
        heartbeat = threading.Thread(target=_heartbeat_loop, args=(job_path, stop_heartbeat), daemon=True)
        heartbeat.start()

        try:
            result = call_operation(operation, params)
        finally:
            stop_heartbeat.set()

        job = read_job(job_path=job_path)
        job.update({"status": "completed", "result": result, "finished_at": utc_now(), "updated_at": utc_now()})
        write_job(job_path, job)
        return 0
    except OperationError as exc:
        stop_heartbeat.set()
        _write_failure(job_path, {"code": exc.code, "message": exc.message})
        return 1
    except Exception as exc:
        stop_heartbeat.set()
        _write_failure(
            job_path,
            {
                "code": "background_job_exception",
                "message": str(exc),
                "traceback": traceback.format_exc(limit=12),
            },
        )
        return 1


def _heartbeat_loop(job_path: Path, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
        record_heartbeat(job_path)


def _install_termination_handlers(job_path: Path, stop: threading.Event) -> None:
    def _handle(signum: int, _frame: Any) -> None:
        stop.set()
        _write_failure(
            job_path,
            {
                "code": "background_job_signal",
                "message": f"The background worker received signal {signum} and stopped before completing.",
            },
        )
        os._exit(1)

    for name in _TERMINATION_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        # signal.signal raises in non-main threads / unsupported platforms.
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _handle)


def _write_failure(job_path: Path, error: JsonObject) -> None:
    job: JsonObject
    try:
        job = read_job(job_path=job_path)
    except Exception:
        job = {"job_path": str(job_path)}
    job.update({"status": "failed", "error": error, "finished_at": utc_now(), "updated_at": utc_now()})
    write_job(job_path, job)


if __name__ == "__main__":
    raise SystemExit(main())
