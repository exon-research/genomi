from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]


class ArtifactOriginError(ValueError):
    """Raised when an artifact is attached to an invalid origin frame."""


def validate_frame_id(state: JsonObject, project_id: str, frame_id: str) -> str:
    clean_frame_id = str(frame_id or "").strip()
    if not clean_frame_id:
        raise ArtifactOriginError("artifact origin frame id is empty")
    frame = state["frames"].get(clean_frame_id)
    if not isinstance(frame, dict):
        raise ArtifactOriginError(f"artifact origin frame not found: {clean_frame_id}")
    if frame.get("project_id") != project_id:
        raise ArtifactOriginError(f"artifact origin frame belongs to a different project: {clean_frame_id}")
    return clean_frame_id


def origin_snapshot(state: JsonObject, project_id: str, frame_id: str | None) -> JsonObject | None:
    clean_frame_id = str(frame_id or "").strip()
    if not clean_frame_id:
        return None
    validated_frame_id = validate_frame_id(state, project_id, clean_frame_id)
    frame = state["frames"].get(validated_frame_id)
    messages = state["messages"].get(validated_frame_id, [])
    if not isinstance(messages, list):
        messages = []
    origin = {
        "frame_id": validated_frame_id,
        "message_ids": [
            str(message.get("id") or "").strip()
            for message in messages
            if isinstance(message, dict) and str(message.get("id") or "").strip()
        ],
    }
    producing_run_id = _producing_run_id(frame, messages)
    if producing_run_id:
        origin["producing_run_id"] = producing_run_id
        assistant_message_id = _producing_assistant_message_id(messages, producing_run_id)
        if assistant_message_id:
            origin["producing_assistant_message_id"] = assistant_message_id
    return origin


def origin_from_artifact(artifact: JsonObject, state: JsonObject) -> JsonObject | None:
    origin = artifact.get("origin") if isinstance(artifact.get("origin"), dict) else None
    if origin is None:
        return None
    frame_id = str(origin.get("frame_id") or "").strip()
    if not frame_id:
        return None
    frame = state["frames"].get(frame_id)
    if not isinstance(frame, dict) or frame.get("project_id") != artifact.get("project_id"):
        return None
    message_ids = origin.get("message_ids")
    if not isinstance(message_ids, list):
        return None
    clean_origin = {
        "frame_id": frame_id,
        "message_ids": [
            str(message_id).strip()
            for message_id in message_ids
            if str(message_id).strip()
        ],
    }
    producing_run_id = str(origin.get("producing_run_id") or "").strip()
    if producing_run_id:
        clean_origin["producing_run_id"] = producing_run_id
        producing_assistant_message_id = str(origin.get("producing_assistant_message_id") or "").strip()
        if producing_assistant_message_id:
            clean_origin["producing_assistant_message_id"] = producing_assistant_message_id
    return clean_origin


def _producing_run_id(frame: JsonObject | None, messages: list[Any]) -> str:
    if isinstance(frame, dict):
        frame_run_id = str(frame.get("run_id") or "").strip()
        if frame_run_id:
            return frame_run_id
    message_run_ids = [
        str(message.get("run_id") or "").strip()
        for message in messages
        if isinstance(message, dict) and str(message.get("run_id") or "").strip()
    ]
    unique_run_ids = list(dict.fromkeys(message_run_ids))
    return unique_run_ids[0] if len(unique_run_ids) == 1 else ""


def _producing_assistant_message_id(messages: list[Any], producing_run_id: str) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant" or str(message.get("run_id") or "").strip() != producing_run_id:
            continue
        message_id = str(message.get("id") or "").strip()
        if message_id:
            return message_id
    return ""
