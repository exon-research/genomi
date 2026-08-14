from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..operations import OperationError, call_operation
from . import (
    portal_artifact_reproduction,
    portal_decode_artifacts,
    portal_evidence_packet_artifacts,
    portal_run_events,
    portal_store,
)
from .presentation import present_result

JsonObject = dict[str, Any]
OutputFilenameBuilder = Callable[[JsonObject], str]
ParamsBuilder = Callable[["ArtifactRenderRequest", Path], JsonObject]
ResultPreparer = Callable[[JsonObject, Path], "ArtifactRenderOutput"]
ArtifactMapper = Callable[[str, "ArtifactRenderOutput", "ArtifactRenderRequest"], JsonObject | None]

DECODE_DASHBOARD_RENDERER = "decode_dashboard"
EVIDENCE_PACKET_RENDERER = "evidence_packet"


@dataclass(frozen=True)
class ArtifactRenderer:
    id: str
    operation: str
    output_filename: str
    artifact_mapper: ArtifactMapper
    params_builder: ParamsBuilder
    result_preparer: ResultPreparer
    output_filename_builder: OutputFilenameBuilder | None = None

    def output_path(self, project_id: str, payload: JsonObject | None = None) -> Path:
        filename = self.output_filename_builder(payload or {}) if self.output_filename_builder else self.output_filename
        return portal_store.artifacts_dir(project_id) / filename


@dataclass(frozen=True)
class ArtifactRenderOutput:
    presented_result: JsonObject
    file_path: str | None = None
    open_url: str | None = None


@dataclass(frozen=True)
class ArtifactRenderRequest:
    payload: JsonObject
    origin_frame_id: str | None = None

    @classmethod
    def from_payload(cls, payload: JsonObject) -> "ArtifactRenderRequest":
        return cls(payload=dict(payload), origin_frame_id=_payload_origin_frame_id(payload))


_RENDERERS: dict[str, ArtifactRenderer] = {
    DECODE_DASHBOARD_RENDERER: ArtifactRenderer(
        id=DECODE_DASHBOARD_RENDERER,
        operation="decode.render_dashboard",
        output_filename="dashboard.html",
        artifact_mapper=lambda project_id, output, request: portal_decode_artifacts.add_decode_dashboard_artifact(
            project_id,
            output.presented_result,
            frame_id=request.origin_frame_id,
        ),
        params_builder=lambda _request, output: {"output": str(output)},
        result_preparer=lambda presented, _output: ArtifactRenderOutput(presented_result=presented),
    ),
    EVIDENCE_PACKET_RENDERER: ArtifactRenderer(
        id=EVIDENCE_PACKET_RENDERER,
        operation="research.build_target_packet",
        output_filename="evidence-packet.html",
        output_filename_builder=lambda _payload: _unique_evidence_packet_filename(),
        artifact_mapper=lambda project_id, output, request: portal_evidence_packet_artifacts.add_evidence_packet_artifact(
            project_id,
            output.presented_result,
            frame_id=request.origin_frame_id,
            file_path=output.file_path,
            external_url=output.open_url,
            reproduction=portal_artifact_reproduction.operation_rebuild_recipe(
                operation="research.build_target_packet",
                renderer=EVIDENCE_PACKET_RENDERER,
                params=_evidence_packet_params(request.payload),
                artifact_family="evidence_report",
            ),
        ),
        params_builder=lambda request, _output: _evidence_packet_params(request.payload),
        result_preparer=lambda presented, output: _prepare_evidence_packet_result(presented, output),
    ),
}


def start_artifact_render(project_id: str, payload: JsonObject) -> JsonObject:
    project = portal_store.get_project(project_id)
    if project is None:
        return {"error": {"code": "not_found", "message": "project not found"}}
    renderer_id = str(payload.get("renderer") or "").strip()
    if not renderer_id:
        return {"error": {"code": "missing_renderer", "message": "artifact renderer required"}}
    renderer = _RENDERERS.get(renderer_id)
    if renderer is None:
        return {"error": {"code": "unknown_renderer", "message": f"unknown artifact renderer: {renderer_id}"}}
    request = ArtifactRenderRequest.from_payload(payload)
    origin_error = _origin_validation_error(project_id, request)
    if origin_error is not None:
        return {"error": origin_error}
    run = portal_run_events.create_run(
        kind="artifact_render",
        message=f"Render Genomi artifact with {renderer.id}",
        project_id=project_id,
    )
    threading.Thread(
        target=_run_artifact_render,
        args=(run, project_id, renderer, request),
        name=f"genomi-portal-artifact-{renderer.id}-{run.id}",
        daemon=True,
    ).start()
    return {"runId": run.id, "status": run.status, "project": project, "renderer": renderer.id}


def render_project_artifact(project_id: str, renderer: ArtifactRenderer, payload: JsonObject) -> JsonObject:
    return _render_project_artifact_request(project_id, renderer, ArtifactRenderRequest.from_payload(payload))


def _render_project_artifact_request(project_id: str, renderer: ArtifactRenderer, request: ArtifactRenderRequest) -> JsonObject:
    project = portal_store.get_project(project_id)
    if project is None:
        return {"error": {"code": "not_found", "message": "project not found"}}
    origin_error = _origin_validation_error(project_id, request)
    if origin_error is not None:
        return {"error": origin_error}
    output = renderer.output_path(project_id, request.payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = call_operation(renderer.operation, renderer.params_builder(request, output))
        rendered = renderer.result_preparer(present_result(renderer.operation, result), output)
    except OperationError as exc:
        return exc.to_json(operation=renderer.operation)
    try:
        artifact = renderer.artifact_mapper(project_id, rendered, request)
    except portal_store.ArtifactOriginError as exc:
        return {"error": {"code": "invalid_origin", "message": str(exc)}}
    return {"status": "completed", "project": project, "artifact": artifact, "result": rendered.presented_result}


def _run_artifact_render(
    run: portal_run_events.PortalRun,
    project_id: str,
    renderer: ArtifactRenderer,
    request: ArtifactRenderRequest,
) -> None:
    run.status = "running"
    run.emit("start", {"status": "running", "renderer": renderer.id, "operation": renderer.operation})
    result = _render_project_artifact_request(project_id, renderer, request)
    if result.get("error"):
        error = result["error"]
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "artifact render failed")
            error_payload = error
        else:
            message = str(result.get("message") or error or "artifact render failed")
            error_payload = {"code": str(error or "artifact_render_failed"), "message": message}
        run.emit("artifact_error", {"message": message, "error": error_payload, "renderer": renderer.id})
        run.finish("failed", error=message)
        return
    artifact = result.get("artifact")
    if isinstance(artifact, dict):
        run.output = str((result.get("result") or {}).get("headline") or artifact.get("title") or "Artifact rendered.")
        event = run.emit("artifact", {"artifact": portal_store.public_artifact_summary(artifact)})
        portal_store.attach_artifact_producing_event(
            str(artifact.get("id") or ""),
            run_id=run.id,
            event_id=event.id,
        )
    run.finish("succeeded")


def _evidence_packet_params(payload: JsonObject) -> JsonObject:
    source = _evidence_packet_param_source(payload)
    params: JsonObject = {}
    for key in ("gene", "drug", "condition", "topic", "chrom", "ref", "alt", "genome_build", "source_id"):
        value = source.get(key)
        if value not in (None, ""):
            params[key] = value
    for key in ("pos", "limit"):
        value = source.get(key)
        if value not in (None, ""):
            params[key] = value
    target_type = source.get("target_type")
    if target_type not in (None, ""):
        params["target_type"] = target_type
    return params


def _evidence_packet_param_source(payload: JsonObject) -> JsonObject:
    params = payload.get("params")
    if isinstance(params, dict):
        return dict(params)
    target = payload.get("target")
    if isinstance(target, dict):
        combined = dict(target)
        for key in ("genome_build", "source_id", "limit"):
            if payload.get(key) not in (None, ""):
                combined[key] = payload[key]
        return combined
    return payload


def _origin_validation_error(project_id: str, request: ArtifactRenderRequest) -> JsonObject | None:
    if not request.origin_frame_id:
        return None
    try:
        portal_store.validate_artifact_origin_frame(project_id, request.origin_frame_id)
    except portal_store.ArtifactOriginError as exc:
        return {"code": "invalid_origin", "message": str(exc)}
    return None


def _payload_origin_frame_id(payload: JsonObject) -> str | None:
    for key in ("frameId", "frame_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _prepare_evidence_packet_result(presented: JsonObject, output: Path) -> ArtifactRenderOutput:
    payload = dict(presented)
    portal_evidence_packet_artifacts.write_evidence_packet_html(output, payload)
    return ArtifactRenderOutput(presented_result=payload, file_path=str(output))


def _unique_evidence_packet_filename() -> str:
    return f"evidence-packet-{uuid.uuid4().hex[:12]}.html"
