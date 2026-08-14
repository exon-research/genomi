from __future__ import annotations

import json
from typing import Any

from . import portal_artifact_reproduction, portal_turns

JsonObject = dict[str, Any]

REVIEW_KIND = "artifact_version_review"
REVIEW_RUN_KIND = "artifact_review_run"
STATUS_PASSED = "passed"
STATUS_WARNING = "warning"
STATUS_FAILED = "failed"
STATUS_NOT_RUN = "not_run"
STATUS_COMPLETED = "completed"
STATUS_RUNNING = "running"
CHECK_NOT_APPLICABLE = "not_applicable"
PUBLIC_REVIEW_STATUSES = {STATUS_PASSED, STATUS_WARNING, STATUS_FAILED, STATUS_NOT_RUN}
PUBLIC_CHECK_STATUSES = {STATUS_PASSED, STATUS_WARNING, STATUS_FAILED, CHECK_NOT_APPLICABLE}
PUBLIC_REVIEW_RUN_STATUSES = {STATUS_COMPLETED, STATUS_RUNNING}


def artifact_version_review(
    *,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary: JsonObject,
    public_payload: JsonObject | None,
    version: JsonObject,
    reproduction: JsonObject | None,
    created_at: str,
) -> JsonObject:
    safe_result = _safe_object(result)
    safe_summary = _safe_object(summary)
    public_reproduction = portal_artifact_reproduction.public_reproduction(reproduction)
    checks = [
        _snapshot_check(version),
        _evidence_envelope_check(
            artifact_kind=artifact_kind,
            renderer=renderer,
            operation=operation,
            result=safe_result,
            summary=safe_summary,
        ),
        _reproduction_check(public_reproduction),
        _public_payload_safety_check({"artifact": _safe_payload_source(public_payload), "reproduction": reproduction}),
    ]
    review = {
        "kind": REVIEW_KIND,
        "status": _overall_status(checks),
        "generated_at": created_at,
        "check_count": len(checks),
        "counts": _status_counts(checks),
        "checks": checks,
        "limitations": [
            "These are deterministic artifact and evidence-boundary checks, not clinical validation.",
        ],
    }
    public = public_review(review)
    return public if public is not None else {"kind": REVIEW_KIND, "status": STATUS_NOT_RUN, "checks": []}


def public_review(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    status = _safe_text(source.get("status"))
    if status not in PUBLIC_REVIEW_STATUSES:
        return None
    checks = [_public_check(item) for item in source.get("checks", [])] if isinstance(source.get("checks"), list) else []
    checks = [item for item in checks if item is not None]
    counts = _public_counts(source.get("counts"), checks)
    public: JsonObject = {
        "kind": _safe_text(source.get("kind")) or REVIEW_KIND,
        "status": status,
        "generated_at": _safe_text(source.get("generated_at")),
        "check_count": len(checks),
        "counts": counts,
        "checks": checks,
        "limitations": _public_text_list(source.get("limitations")),
    }
    return _compact(public)


def artifact_review_run(
    *,
    review: JsonObject,
    review_run_id: str,
    version: JsonObject,
    started_at: str,
    completed_at: str,
) -> JsonObject:
    public = public_review(review) or {"kind": REVIEW_KIND, "status": STATUS_NOT_RUN, "checks": []}
    run = {
        "kind": REVIEW_RUN_KIND,
        "review_run_id": review_run_id,
        "status": STATUS_COMPLETED,
        "check_status": _safe_text(public.get("status")) or STATUS_NOT_RUN,
        "started_at": started_at,
        "completed_at": completed_at,
        "version_id": _safe_text(version.get("version_id")),
        "check_count": public.get("check_count"),
        "counts": public.get("counts"),
        "summary": "Deterministic artifact checks completed for this result version.",
        "review": public,
        "limitations": [
            "This check run re-evaluates Genomi's stored artifact and evidence-boundary checks. It is not clinical validation.",
        ],
    }
    public_run = public_review_run(run)
    return public_run if public_run is not None else {"kind": REVIEW_RUN_KIND, "status": STATUS_COMPLETED}


def artifact_review_run_pending(
    *,
    review_run_id: str,
    version: JsonObject,
    started_at: str,
) -> JsonObject:
    run = {
        "kind": REVIEW_RUN_KIND,
        "review_run_id": review_run_id,
        "status": STATUS_RUNNING,
        "check_status": STATUS_RUNNING,
        "started_at": started_at,
        "version_id": _safe_text(version.get("version_id")),
        "summary": "Review checks are running for this artifact version.",
        "limitations": [
            "This check run is deterministic artifact and evidence-boundary review. It is not clinical validation.",
        ],
    }
    public_run = public_review_run(run)
    return public_run if public_run is not None else {"kind": REVIEW_RUN_KIND, "status": STATUS_RUNNING}


def public_review_run(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    status = _safe_text(source.get("status"))
    if status not in PUBLIC_REVIEW_RUN_STATUSES:
        return None
    review = public_review(source.get("review"))
    run: JsonObject = {
        "kind": _safe_text(source.get("kind")) or REVIEW_RUN_KIND,
        "review_run_id": _safe_text(source.get("review_run_id")),
        "status": status,
        "check_status": _safe_text(source.get("check_status")),
        "started_at": _safe_text(source.get("started_at")),
        "completed_at": _safe_text(source.get("completed_at")),
        "version_id": _safe_text(source.get("version_id")),
        "check_count": source.get("check_count") if isinstance(source.get("check_count"), int) else None,
        "counts": _public_counts(source.get("counts"), review.get("checks", []) if isinstance(review, dict) else []),
        "summary": _safe_text(source.get("summary")),
        "limitations": _public_text_list(source.get("limitations")),
    }
    if review is not None:
        run["review"] = review
    return _compact(run)


def public_review_runs(value: Any) -> list[JsonObject]:
    items = value if isinstance(value, list) else []
    runs = [public_review_run(item) for item in items]
    return [run for run in runs if run is not None]


def _snapshot_check(version: JsonObject) -> JsonObject:
    checksum = _safe_text(version.get("checksum"))
    content_type = _safe_text(version.get("content_type"))
    size_bytes = version.get("size_bytes")
    size_number = size_bytes if isinstance(size_bytes, int) and size_bytes >= 0 else None
    if checksum and content_type and size_number is not None:
        status = STATUS_PASSED
        summary = "Immutable artifact file metadata is attached to this version."
    else:
        status = STATUS_FAILED
        summary = "The artifact version is missing file metadata needed for a stable review."
    observed: JsonObject = {
        "version_id": _safe_text(version.get("version_id")),
        "content_type": content_type,
        "checksum": checksum,
        "size_bytes": size_number,
    }
    return _check(
        check_id="artifact_file_snapshot",
        title="Artifact file snapshot",
        status=status,
        severity="error" if status == STATUS_FAILED else "info",
        summary=summary,
        observed=observed,
    )


def _evidence_envelope_check(
    *,
    artifact_kind: str,
    renderer: str,
    operation: str,
    result: JsonObject,
    summary: JsonObject,
) -> JsonObject:
    envelope = _first_object(summary.get("evidence_envelope"), result.get("evidence_envelope"))
    finding_state = _safe_text(envelope.get("finding_state"))
    answer_readiness = _safe_text(envelope.get("answer_readiness"))
    is_evidence_artifact = (
        _safe_text(artifact_kind) == "evidence_packet"
        or _safe_text(renderer) == "evidence_packet"
        or _safe_text(operation) == "research.build_target_packet"
    )
    if finding_state or answer_readiness:
        return _check(
            check_id="evidence_envelope_present",
            title="Evidence envelope",
            status=STATUS_PASSED,
            severity="info",
            summary="Evidence finding state and answer-readiness fields are available for review.",
            observed={"finding_state": finding_state, "answer_readiness": answer_readiness},
        )
    if is_evidence_artifact:
        return _check(
            check_id="evidence_envelope_present",
            title="Evidence envelope",
            status=STATUS_WARNING,
            severity="warning",
            summary="This evidence artifact does not expose an evidence envelope in its stored summary.",
        )
    return _check(
        check_id="evidence_envelope_present",
        title="Evidence envelope",
        status=CHECK_NOT_APPLICABLE,
        severity="info",
        summary="This artifact type does not require an evidence envelope.",
    )


def _reproduction_check(reproduction: JsonObject | None) -> JsonObject:
    if not isinstance(reproduction, dict):
        return _check(
            check_id="rebuild_recipe",
            title="Rebuild recipe",
            status=CHECK_NOT_APPLICABLE,
            severity="info",
            summary="No rebuild recipe was attached to this artifact version.",
        )
    status = _safe_text(reproduction.get("status"))
    if status == portal_artifact_reproduction.READY_STATUS:
        return _check(
            check_id="rebuild_recipe",
            title="Rebuild recipe",
            status=STATUS_PASSED,
            severity="info",
            summary="The artifact version has an executable public rebuild recipe.",
            observed={"operation": _safe_text(reproduction.get("operation")), "params_redacted": False},
        )
    if status == portal_artifact_reproduction.PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS:
        return _check(
            check_id="rebuild_recipe",
            title="Rebuild recipe",
            status=STATUS_WARNING,
            severity="warning",
            summary="The rebuild recipe is partial because private parameters were redacted.",
            observed={"operation": _safe_text(reproduction.get("operation")), "params_redacted": True},
        )
    return _check(
        check_id="rebuild_recipe",
        title="Rebuild recipe",
        status=STATUS_WARNING,
        severity="warning",
        summary="The rebuild recipe status is not recognized.",
        observed={"status": status},
    )


def _public_payload_safety_check(value: JsonObject) -> JsonObject:
    safe_value = portal_turns.prompt_safe_value(value)
    redacted = _json_fingerprint(value) != _json_fingerprint(safe_value)
    if redacted:
        return _check(
            check_id="public_payload_safety",
            title="Public payload safety",
            status=STATUS_WARNING,
            severity="warning",
            summary="Private or local-path fields were redacted before public artifact display.",
            observed={"redacted": True},
        )
    return _check(
        check_id="public_payload_safety",
        title="Public payload safety",
        status=STATUS_PASSED,
        severity="info",
        summary="No private local-path fields were present in the reviewed public payload.",
        observed={"redacted": False},
    )


def _safe_payload_source(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _check(
    *,
    check_id: str,
    title: str,
    status: str,
    severity: str,
    summary: str,
    observed: JsonObject | None = None,
) -> JsonObject:
    check: JsonObject = {
        "check_id": check_id,
        "title": title,
        "status": status,
        "severity": severity,
        "summary": summary,
    }
    if observed:
        check["observed"] = observed
    public = _public_check(check)
    return public if public is not None else {"check_id": check_id, "title": title, "status": status}


def _public_check(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    check_id = _safe_text(source.get("check_id"))
    status = _safe_text(source.get("status"))
    if not check_id or status not in PUBLIC_CHECK_STATUSES:
        return None
    check: JsonObject = {
        "check_id": check_id,
        "title": _safe_text(source.get("title")),
        "status": status,
        "severity": _safe_text(source.get("severity")),
        "summary": _safe_text(source.get("summary")),
    }
    observed = portal_turns.prompt_safe_value(source.get("observed"))
    if isinstance(observed, dict):
        check["observed"] = observed
    return _compact(check)


def _status_counts(checks: list[JsonObject]) -> JsonObject:
    counts: JsonObject = {
        STATUS_PASSED: 0,
        STATUS_WARNING: 0,
        STATUS_FAILED: 0,
        CHECK_NOT_APPLICABLE: 0,
    }
    for check in checks:
        status = _safe_text(check.get("status"))
        if status in counts:
            counts[status] += 1
    return counts


def _public_counts(value: Any, checks: list[JsonObject]) -> JsonObject:
    source = value if isinstance(value, dict) else _status_counts(checks)
    counts: JsonObject = {}
    for key in (STATUS_PASSED, STATUS_WARNING, STATUS_FAILED, CHECK_NOT_APPLICABLE):
        count = source.get(key)
        if isinstance(count, bool):
            continue
        if isinstance(count, int) and count >= 0:
            counts[key] = count
    return counts or _status_counts(checks)


def _overall_status(checks: list[JsonObject]) -> str:
    statuses = {_safe_text(check.get("status")) for check in checks}
    if STATUS_FAILED in statuses:
        return STATUS_FAILED
    if STATUS_WARNING in statuses:
        return STATUS_WARNING
    if STATUS_PASSED in statuses:
        return STATUS_PASSED
    return STATUS_NOT_RUN


def _first_object(*values: Any) -> JsonObject:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _safe_object(value: Any) -> JsonObject:
    safe = portal_turns.prompt_safe_value(value if isinstance(value, dict) else {})
    return safe if isinstance(safe, dict) else {}


def _public_text_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [text for text in (_safe_text(item) for item in items) if text]


def _compact(value: JsonObject) -> JsonObject:
    return {
        key: child
        for key, child in value.items()
        if child not in (None, "", [], {})
    }


def _safe_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _json_fingerprint(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=True)
