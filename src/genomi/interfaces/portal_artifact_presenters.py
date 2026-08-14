from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..runtime import portal_routes
from . import (
    portal_artifact_environment,
    portal_artifact_origins,
    portal_artifact_presentation,
    portal_artifact_reproduction,
    portal_artifact_review,
    portal_artifact_work_steps,
    portal_turns,
)

JsonObject = dict[str, Any]


def public_artifact_version_summary(version: JsonObject) -> JsonObject:
    filename = version.get("filename")
    public = {
        "version_id": version.get("version_id"),
        "artifact_id": version.get("artifact_id"),
        "project_id": version.get("project_id"),
        "created_at": version.get("created_at"),
        "content_type": version.get("content_type"),
        "filename": filename if isinstance(filename, str) and _safe_storage_name(filename) else None,
        "checksum": version.get("checksum"),
        "size_bytes": version.get("size_bytes"),
        "is_intermediate": bool(version.get("is_intermediate", False)),
    }
    version_id = version.get("version_id")
    if isinstance(version_id, str) and version_id:
        project_id = version.get("project_id")
        artifact_id = version.get("artifact_id")
        if isinstance(project_id, str) and isinstance(artifact_id, str) and project_id and artifact_id:
            public["file_url"] = portal_routes.project_artifact_version_file_endpoint(project_id, artifact_id, version_id)
    work_step = portal_artifact_work_steps.public_producing_work_step(version.get("producing_work_step"))
    if work_step is not None:
        public["producing_work_step"] = work_step
    return public


def public_artifact_version_detail(version: JsonObject) -> JsonObject:
    public = public_artifact_version_summary(version)
    reproduction = portal_artifact_reproduction.public_reproduction(version.get("reproduction"))
    if reproduction is not None:
        public["reproduction"] = reproduction
    environment = portal_artifact_environment.public_environment(version.get("environment"))
    if environment is not None:
        public["environment"] = environment
    review = portal_artifact_review.public_review(version.get("review"))
    if review is not None:
        review_runs = portal_artifact_review.public_review_runs(version.get("review_runs"))
        if review_runs:
            review["review_runs"] = review_runs
        public["review"] = review
    return public


def public_artifact_summary(artifact: JsonObject, state: JsonObject) -> JsonObject:
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    summary_lines = artifact.get("summary_lines") if isinstance(artifact.get("summary_lines"), list) else []
    latest_version = _latest_public_version(artifact, state)
    project_id = artifact.get("project_id")
    artifact_id = artifact.get("id")
    latest_file_url = (
        portal_routes.project_artifact_file_endpoint(project_id, artifact_id)
        if isinstance(project_id, str) and isinstance(artifact_id, str) and artifact.get("latest_version_id")
        else None
    )
    external_url = _safe_external_artifact_url(artifact.get("url"))
    public = {
        "id": artifact.get("id"),
        "project_id": artifact.get("project_id"),
        "kind": artifact.get("kind"),
        "renderer": artifact.get("renderer"),
        "title": _safe_public_text(artifact.get("title")),
        "operation": artifact.get("operation"),
        "status": artifact.get("status"),
        "artifact_presentation": portal_artifact_presentation.artifact_presentation(artifact),
        "starred": bool(artifact.get("starred", False)),
        "hidden": bool(artifact.get("hidden", False)),
        "url": external_url or latest_file_url,
        "preview_url": latest_file_url,
        "summary": portal_turns.prompt_safe_value(summary),
        "summary_lines": [
            portal_turns.prompt_safe_text(str(line)).strip()
            for line in summary_lines
            if str(line).strip()
        ],
        "open_label": _safe_public_text(artifact.get("open_label")) or "Open result",
        "latest_version_id": artifact.get("latest_version_id"),
        "version_count": artifact.get("version_count"),
        "latest_version": latest_version,
        "created_at": artifact.get("created_at"),
        "updated_at": artifact.get("updated_at"),
    }
    origin_context = artifact_origin_context(artifact, state)
    if origin_context is not None:
        public["origin_context"] = origin_context
    review = artifact_review(artifact, state)
    if review is not None:
        public["review"] = review
    return public


def public_artifact_detail(artifact: JsonObject, state: JsonObject) -> JsonObject:
    public = public_artifact_summary(artifact, state)
    origin_context = artifact_origin_context(artifact, state)
    if origin_context is not None:
        public["origin_context"] = origin_context
    reproduction = artifact_reproduction(artifact, state)
    if reproduction is not None:
        public["reproduction"] = reproduction
    environment = artifact_environment(artifact, state)
    if environment is not None:
        public["environment"] = environment
    review = artifact_review(artifact, state)
    if review is not None:
        public["review"] = review
    provenance_messages = artifact_provenance_messages(artifact, state)
    if provenance_messages is not None:
        public["provenance_messages"] = provenance_messages
    return public


def artifact_reproduction(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version = _latest_raw_artifact_version(artifact, state)
    if version is None:
        return None
    return portal_artifact_reproduction.public_reproduction(version.get("reproduction"))


def artifact_environment(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version = _latest_raw_artifact_version(artifact, state)
    if version is None:
        return None
    return portal_artifact_environment.public_environment(version.get("environment"))


def artifact_review(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version = _latest_raw_artifact_version(artifact, state)
    if version is None:
        return None
    return portal_artifact_review.public_review(version.get("review"))


def artifact_producing_work_step(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version = _latest_raw_artifact_version(artifact, state)
    if version is None:
        return None
    return portal_artifact_work_steps.public_producing_work_step(version.get("producing_work_step"))


def artifact_origin_context(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    origin = portal_artifact_origins.origin_from_artifact(artifact, state)
    if origin is None:
        return None
    frame_id = str(origin["frame_id"])
    message_ids = [str(message_id) for message_id in origin["message_ids"]]
    context = {
        "frame_id": frame_id,
        "message_ids_count": len(message_ids),
        "run_ids": _origin_run_ids(origin, frame_id, message_ids, state),
    }
    producing_run_id = str(origin.get("producing_run_id") or "").strip()
    if producing_run_id:
        context["producing_run_id"] = producing_run_id
    producing_assistant_message_id = str(origin.get("producing_assistant_message_id") or "").strip()
    if producing_assistant_message_id:
        context["producing_assistant_message_id"] = producing_assistant_message_id
    return context


def artifact_provenance_messages(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    origin = portal_artifact_origins.origin_from_artifact(artifact, state)
    if origin is None:
        return None
    frame_id = str(origin["frame_id"])
    message_ids = list(origin["message_ids"])
    messages = state["messages"].get(frame_id, [])
    if not isinstance(messages, list):
        messages = []
    messages_by_id = {
        str(message.get("id") or ""): message
        for message in messages
        if isinstance(message, dict) and str(message.get("id") or "")
    }
    public_messages = [
        public_message(messages_by_id[message_id], frame_id=frame_id)
        for message_id in message_ids
        if message_id in messages_by_id
    ]
    return {
        "frame_id": frame_id,
        "total": len(message_ids),
        "displayed": len(public_messages),
        "messages": public_messages,
    }


def _origin_run_ids(origin: JsonObject, frame_id: str, message_ids: list[str], state: JsonObject) -> list[str]:
    producing_run_id = str(origin.get("producing_run_id") or "").strip()
    if producing_run_id:
        return [producing_run_id]
    messages = state["messages"].get(frame_id, [])
    if not isinstance(messages, list):
        return []
    message_id_set = set(message_ids)
    run_ids: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or str(message.get("id") or "") not in message_id_set:
            continue
        run_id = portal_turns.prompt_safe_text(str(message.get("run_id") or "")).strip()
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)
    return run_ids


def public_message(message: JsonObject, *, frame_id: str | None = None) -> JsonObject:
    public: JsonObject = {
        "id": message.get("id"),
        "role": message.get("role"),
        "created_at": message.get("created_at"),
    }
    for key in ("updated_at", "run_id", "stream_status"):
        if message.get(key) is not None:
            public[key] = message.get(key)
    if frame_id:
        public["frame_id"] = frame_id
    if isinstance(message.get("text"), str):
        public["text"] = portal_turns.prompt_safe_text(str(message["text"]))
    genome_context_mode = str(message.get("genome_context_mode") or "").strip().lower()
    if genome_context_mode in {"public", "auto"}:
        public["genome_context_mode"] = genome_context_mode
    event = message.get("event")
    if isinstance(event, dict):
        public["event"] = portal_turns.history_tool_event(event)
    selected = portal_turns.clean_selected_evidence(message.get("selected_evidence"))
    if selected:
        public["selected_evidence"] = selected
    return public


def _latest_public_version(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version = _latest_raw_artifact_version(artifact, state)
    return public_artifact_version_summary(version) if version is not None else None


def _latest_raw_artifact_version(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    version_id = artifact.get("latest_version_id")
    if not isinstance(version_id, str) or not version_id:
        return None
    version = state["artifact_versions"].get(version_id)
    if not isinstance(version, dict) or version.get("artifact_id") != artifact.get("id"):
        return None
    if version.get("project_id") != artifact.get("project_id"):
        return None
    return version


def _safe_public_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _safe_storage_name(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    path = Path(value)
    return not path.is_absolute() and path.name == value


def _safe_external_artifact_url(value: Any) -> str | None:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return raw
