from __future__ import annotations

import argparse
import os
import traceback
from pathlib import Path
from typing import Any

from ..operations import OperationError, call_operation
from .background_jobs import read_job, write_job
from .external import utc_now

JsonObject = dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Genomi operation background job.")
    parser.add_argument("--job", required=True, help="Path to a Genomi background job JSON file.")
    args = parser.parse_args(argv)
    job_path = Path(args.job)

    try:
        job = read_job(job_path=job_path)
        operation = str(job.get("operation") or "")
        params = job.get("params") or {}
        if not operation:
            raise OperationError("invalid_background_job", "background job is missing operation")
        if not isinstance(params, dict):
            raise OperationError("invalid_background_job", "background job params must be an object")

        job.update({"status": "running", "pid": os.getpid(), "started_at": job.get("started_at") or utc_now(), "updated_at": utc_now()})
        write_job(job_path, job)

        result = call_operation(operation, params)
        job = read_job(job_path=job_path)
        job.update({"status": "completed", "result": result, "finished_at": utc_now(), "updated_at": utc_now()})
        write_job(job_path, job)
        return 0
    except OperationError as exc:
        _write_failure(job_path, {"code": exc.code, "message": exc.message})
        return 1
    except Exception as exc:
        _write_failure(
            job_path,
            {
                "code": "background_job_exception",
                "message": str(exc),
                "traceback": traceback.format_exc(limit=12),
            },
        )
        return 1


def _write_failure(job_path: Path, error: JsonObject) -> None:
    try:
        job = read_job(job_path=job_path)
    except Exception:
        job = {"job_path": str(job_path)}
    job.update({"status": "failed", "error": error, "finished_at": utc_now(), "updated_at": utc_now()})
    write_job(job_path, job)


if __name__ == "__main__":
    raise SystemExit(main())
