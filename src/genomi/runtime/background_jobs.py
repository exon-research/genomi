from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..evidence import envelope as _env
from .external import utc_now
from .paths import genomi_data_root

JsonObject = dict[str, Any]
JOB_SCHEMA = "genomi-background-operation-job-v1"
JOBS_DIR_NAME = "jobs"
DEFAULT_BACKGROUND_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.25
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed"}


def background_timeout_seconds() -> float:
    configured = os.environ.get("GENOMI_MCP_BACKGROUND_TIMEOUT_SECONDS") or os.environ.get("GENOMI_TOOL_BACKGROUND_TIMEOUT_SECONDS")
    if not configured:
        return DEFAULT_BACKGROUND_TIMEOUT_SECONDS
    try:
        return max(0.0, float(configured))
    except ValueError:
        return DEFAULT_BACKGROUND_TIMEOUT_SECONDS


def jobs_dir(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / JOBS_DIR_NAME


def start_operation_job(operation: str, params: JsonObject) -> JsonObject:
    safe_params = dict(params)
    digest = operation_params_digest(operation, safe_params)
    active = find_active_job(operation, digest)
    if active is not None:
        active["reused_existing"] = True
        return active

    job_root = jobs_dir()
    job_root.mkdir(parents=True, exist_ok=True)
    job_id = _new_job_id(operation)
    job_path = job_root / f"{job_id}.json"
    log_path = job_root / f"{job_id}.log"
    job = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "operation": operation,
        "params": safe_params,
        "params_digest": digest,
        "status": "queued",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "job_path": str(job_path),
        "log_path": str(log_path),
    }
    write_job(job_path, job)

    command = [sys.executable, "-m", "genomi.runtime.job_worker", "--job", str(job_path)]
    log_handle = log_path.open("ab")
    try:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as exc:
            job.update(
                {
                    "status": "failed",
                    "finished_at": utc_now(),
                    "updated_at": utc_now(),
                    "error": {"code": "background_job_start_failed", "message": str(exc)},
                }
            )
            write_job(job_path, job)
            raise
    finally:
        log_handle.close()

    current = _read_job_file(job_path)
    if current.get("status") == "queued":
        current.update({"status": "running", "pid": process.pid, "started_at": utc_now(), "updated_at": utc_now()})
        write_job(job_path, current)
        return current
    current.setdefault("pid", process.pid)
    return current


def wait_for_job(job_id: str, *, timeout_seconds: float | None = None) -> JsonObject:
    deadline = time.monotonic() + (background_timeout_seconds() if timeout_seconds is None else max(0.0, timeout_seconds))
    while True:
        job = read_job(job_id=job_id)
        if job.get("status") in TERMINAL_STATUSES:
            return job
        if time.monotonic() >= deadline:
            return job
        time.sleep(POLL_INTERVAL_SECONDS)


def read_job(*, job_id: str | None = None, job_path: str | Path | None = None) -> JsonObject:
    path = resolve_job_path(job_id=job_id, job_path=job_path)
    job = _read_job_file(path)
    if job.get("status") in ACTIVE_STATUSES and _process_finished(job):
        job.update(
            {
                "status": "failed",
                "finished_at": utc_now(),
                "updated_at": utc_now(),
                "error": {
                    "code": "background_job_stopped",
                    "message": "The background worker stopped before writing a completed result.",
                },
            }
        )
        write_job(path, job)
    return job


def public_job_status(job: JsonObject, *, timeout_seconds: float | None = None) -> JsonObject:
    status = str(job.get("status") or "unknown")
    operation = str(job.get("operation") or "")
    job_id = str(job.get("job_id") or "")
    payload: JsonObject = {
        "schema": JOB_SCHEMA,
        "status": "in_progress" if status in ACTIVE_STATUSES else status,
        "job_id": job_id,
        "operation": operation,
        "reused_existing": bool(job.get("reused_existing")),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "pid": job.get("pid"),
        "timeout_seconds": timeout_seconds,
        "check": {
            "operation": "genomi.check_background_job",
            "params": {"job_id": job_id},
        },
        "message": _status_message(operation, status),
    }
    if status == "failed":
        payload["error"] = job.get("error") or {"code": "background_job_failed", "message": "Background job failed."}
    payload = _drop_none(payload)
    if payload.get("status") in {"in_progress", "failed"}:
        payload["evidence_envelope"] = _env.derive_default_envelope(operation or "background_job", payload)
    return payload


def operation_params_digest(operation: str, params: JsonObject) -> str:
    encoded = json.dumps({"operation": operation, "params": params}, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def find_active_job(operation: str, params_digest: str) -> JsonObject | None:
    root = jobs_dir()
    if not root.exists():
        return None
    candidates: list[JsonObject] = []
    for path in root.glob("*.json"):
        try:
            job = read_job(job_path=path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if job.get("operation") != operation or job.get("params_digest") != params_digest:
            continue
        if job.get("status") in ACTIVE_STATUSES:
            candidates.append(job)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]


def resolve_job_path(*, job_id: str | None = None, job_path: str | Path | None = None) -> Path:
    if job_path is not None:
        return Path(job_path).expanduser()
    if not job_id:
        raise ValueError("job_id or job_path is required")
    if "/" in job_id or "\\" in job_id:
        raise ValueError("job_id must not contain path separators")
    return jobs_dir() / f"{job_id}.json"


def write_job(path: str | Path, job: JsonObject) -> None:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = {**job, "updated_at": job.get("updated_at") or utc_now()}
    tmp = resolved.with_suffix(resolved.suffix + f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(resolved)


def _read_job_file(path: str | Path) -> JsonObject:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("background job file must contain a JSON object")
    return value


def _process_finished(job: JsonObject) -> bool:
    pid = job.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


def _new_job_id(operation: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in operation).strip("-").lower()
    safe = "-".join(part for part in safe.split("-") if part)[:48] or "operation"
    return f"{safe}-{int(time.time())}-{uuid.uuid4().hex[:12]}"


def _status_message(operation: str, status: str) -> str:
    if status in ACTIVE_STATUSES:
        return (
            f"{operation} is still running in the background. "
            "Call genomi.check_background_job with this job_id before retrying the same operation."
        )
    if status == "completed":
        return f"{operation} completed in the background."
    if status == "failed":
        return f"{operation} failed in the background."
    return f"{operation} background job status is {status}."


def _drop_none(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items() if value is not None}
