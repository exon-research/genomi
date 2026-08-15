from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evidence import envelope as _env
from .external import utc_now
from .paths import genomi_data_root

JsonObject = dict[str, Any]
JOBS_DIR_NAME = "jobs"
DEFAULT_BACKGROUND_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.25
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed"}

# A running worker bumps `heartbeat_at` this often on a side thread, even while
# the operation itself makes no externally visible progress. An observer can
# watch the heartbeat advance to confirm the job is alive (vs. stuck), and a
# running job whose heartbeat has not advanced in HEARTBEAT_STALE_AFTER_SECONDS
# is treated as dead. The staleness check catches the two cases a pid probe
# cannot: a SIGKILLed worker that left no status, and a zombie/defunct worker
# that still answers `os.kill(pid, 0)`.
HEARTBEAT_INTERVAL_SECONDS = 5.0
HEARTBEAT_STALE_AFTER_SECONDS = 60.0


def background_enabled() -> bool:
    """Whether long operations should run as detached background jobs.

    Mirrors the MCP layer's `GENOMI_MCP_BACKGROUND` switch (default on). When
    off — the unit-test / synchronous-CLI default — callers that would normally
    enqueue a job run it inline instead, so the work finishes within the call.
    """
    env_value = os.environ.get("GENOMI_MCP_BACKGROUND", "1").strip().lower()
    return env_value not in {"0", "false", "no", "off", "disabled"}


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
        if active.get("job_path"):
            try:
                write_job(active["job_path"], active)
            except OSError:
                pass
        return active

    job_root = jobs_dir()
    job_root.mkdir(parents=True, exist_ok=True)
    job_id = _new_job_id(operation)
    job_path = job_root / f"{job_id}.json"
    log_path = job_root / f"{job_id}.log"
    job = {
        "job_id": job_id,
        "operation": operation,
        "params": safe_params,
        "params_digest": digest,
        "context_fingerprint": operation_context_fingerprint(operation, safe_params),
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
    reason = _dead_worker_reason(job)
    if reason is not None:
        now = utc_now()
        job.update({"status": "failed", "finished_at": now, "updated_at": now, "error": reason})
        write_job(path, job)
    return job


def record_heartbeat(job_path: str | Path) -> None:
    """Bump a running job's heartbeat. Best-effort: never raises.

    Called periodically by the job worker so observers can see liveness and so
    a stalled/dead worker can be told apart from a slow-but-progressing one.
    No-op once the job has reached a terminal status.
    """
    try:
        job = _read_job_file(job_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if job.get("status") not in ACTIVE_STATUSES:
        return
    now = utc_now()
    job["heartbeat_at"] = now
    job["updated_at"] = now
    try:
        write_job(job_path, job)
    except OSError:
        pass


def _dead_worker_reason(job: JsonObject) -> JsonObject | None:
    """Why a job that still claims to be active should be considered dead.

    Returns the error payload to record, or None if the worker still looks
    alive. Only `running` jobs are probed — a `queued` job has no worker yet.
    """
    if job.get("status") != "running":
        return None
    if _process_finished(job):
        return {
            "code": "background_job_stopped",
            "message": "The background worker stopped before writing a completed result.",
        }
    # `os.kill(pid, 0)` succeeds for a zombie/defunct worker, so fall back to
    # the heartbeat: if the worker has not bumped it (or, before its first
    # heartbeat, since it started) within the stale window, treat it as dead.
    age = _seconds_since(job.get("heartbeat_at") or job.get("started_at"))
    if age is not None and age > HEARTBEAT_STALE_AFTER_SECONDS:
        return {
            "code": "background_job_stalled",
            "message": (
                f"The background worker has sent no heartbeat in {int(age)}s "
                f"(stale after {int(HEARTBEAT_STALE_AFTER_SECONDS)}s); treating it as stopped."
            ),
        }
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _seconds_since(value: Any) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return (datetime.now(tz=timezone.utc) - parsed).total_seconds()


def public_job_status(job: JsonObject, *, timeout_seconds: float | None = None) -> JsonObject:
    status = str(job.get("status") or "unknown")
    operation = str(job.get("operation") or "")
    job_id = str(job.get("job_id") or "")
    payload: JsonObject = {
        "status": "in_progress" if status in ACTIVE_STATUSES else status,
        "job_id": job_id,
        "operation": operation,
        "reused_existing": bool(job.get("reused_existing")),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "heartbeat_at": job.get("heartbeat_at"),
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
    if status in ACTIVE_STATUSES:
        # Surface how long since the last heartbeat so a caller can tell an
        # alive-but-slow job (heartbeat advancing) from a stuck one without
        # knowing the worker's internals.
        age = _seconds_since(job.get("heartbeat_at"))
        if age is not None:
            payload["seconds_since_heartbeat"] = round(age, 1)
    payload = _drop_none(payload)
    if payload.get("status") in {"in_progress", "failed"}:
        payload["evidence_envelope"] = _env.derive_default_envelope(operation or "background_job", payload)
    return payload


def operation_params_digest(operation: str, params: JsonObject) -> str:
    encoded = json.dumps(
        {
            "operation": operation,
            "params": params,
            "context_fingerprint": operation_context_fingerprint(operation, params),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def operation_context_fingerprint(operation: str, params: JsonObject) -> JsonObject | None:
    target_operation, target_params = _effective_operation(operation, params)
    if not _operation_reads_active_genome_index(target_operation, target_params):
        return None
    from . import context as runtime_context

    run = _target_agi_record(target_params)
    if not isinstance(run, dict):
        return {
            "context_scope": runtime_context.context_scope(),
            "active_agi_id": None,
        }
    return {
        "context_scope": runtime_context.context_scope(),
        "active_agi_id": run.get("agi_id"),
        "sample_slug": run.get("sample_slug"),
        "agi_path": run.get("agi_path"),
    }


def _effective_operation(operation: str, params: JsonObject) -> tuple[str, JsonObject]:
    if operation == "genomi.invoke":
        tool = params.get("tool")
        inner = params.get("params")
        if isinstance(tool, str) and isinstance(inner, dict):
            return tool, dict(inner)
    return operation, params


def _operation_reads_active_genome_index(operation: str, params: JsonObject) -> bool:
    if operation in {
        "active_genome_index.summarize",
        "clinvar.match_variants",
        "clinvar.scan_candidates",
        "pharmacogenomics.run_pharmcat",
        "pharmacogenomics.preflight_pharmcat",
        "decode.build_dashboard_evidence",
        "decode.render_dashboard",
    }:
        return True
    if operation == "pharmacogenomics.review_medication":
        if any(params.get(key) not in (None, "") for key in ("agi_id", "agi_path", "db", "matches")):
            return True
        if "include_active_genome_index" in params:
            return bool(params.get("include_active_genome_index"))
        from . import context as runtime_context

        return runtime_context.active_agi_record() is not None
    try:
        from ..operations import get_operation

        registered = get_operation(operation)
    except Exception:
        return False
    return bool(registered.agi_need)


def _target_agi_record(params: JsonObject) -> JsonObject | None:
    from . import context as runtime_context

    agi_path = params.get("agi_path")
    if agi_path not in (None, ""):
        target = str(Path(str(agi_path)).expanduser().resolve(strict=False))
        context = runtime_context.load_context()
        registry = runtime_context.load_registry()
        for container in (context.get("agis"), registry.get("agis")):
            if not isinstance(container, dict):
                continue
            for run in container.values():
                if not isinstance(run, dict) or not run.get("agi_path"):
                    continue
                if str(Path(str(run["agi_path"])).expanduser().resolve(strict=False)) == target:
                    return run
        return {"agi_path": target}

    agi_id = params.get("agi_id")
    if agi_id not in (None, ""):
        return runtime_context.find_agi(str(agi_id))
    return runtime_context.active_agi_record()


def find_active_job(operation: str, params_digest: str) -> JsonObject | None:
    return find_latest_job(operation, params_digest, statuses=ACTIVE_STATUSES)


def find_latest_job(operation: str, params_digest: str, *, statuses: set[str] | frozenset[str] | None = None) -> JsonObject | None:
    root = jobs_dir()
    if not root.exists():
        return None
    candidates: list[JsonObject] = []
    allowed_statuses = set(statuses) if statuses is not None else None
    for path in root.glob("*.json"):
        try:
            job = read_job(job_path=path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if job.get("operation") != operation or job.get("params_digest") != params_digest:
            continue
        if allowed_statuses is not None and job.get("status") not in allowed_statuses:
            continue
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
