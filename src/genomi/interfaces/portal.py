from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..operations import OperationError, operation_discovery_payload
from ..runtime import portal_routes
from ..lab.local_sqlite import LocalSQLiteError
from . import portal_active_context, portal_agents, portal_artifact_bundles, portal_artifact_exports, portal_artifact_renderers, portal_assets, portal_bundle_files, portal_context, portal_file_imports, portal_frame_bundles, portal_genomes, portal_genomilab, portal_project_events, portal_prompt_suggestions, portal_router, portal_run_event_pages, portal_run_events, portal_run_packages, portal_run_service, portal_source_lookups, portal_state, portal_store, portal_turns, portal_workspace_files

JsonObject = dict[str, Any]
MAX_PORTAL_REQUEST_BYTES = 8 * 1024 * 1024
CSRF_HEADER = "X-Genomi-CSRF"
_ARTIFACT_FLAG_ACTIONS: dict[str, tuple[Callable[[str, str, bool], JsonObject | None], bool]] = {
    "star": (portal_store.set_project_artifact_starred, True),
    "unstar": (portal_store.set_project_artifact_starred, False),
    "hide": (portal_store.set_project_artifact_hidden, True),
    "unhide": (portal_store.set_project_artifact_hidden, False),
}


def handle_get(handler: BaseHTTPRequestHandler, path: str, query: str) -> bool:
    match = portal_router.match_route(path, _get_routes())
    if match is None:
        return False
    try:
        match.spec.handler(handler, match.params, query)
    except portal_state.PortalStateError:
        _send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, _portal_state_error_payload())
    return True


def is_portal_get_path(path: str) -> bool:
    return portal_router.match_route(path, _get_routes()) is not None


def handle_post(handler: BaseHTTPRequestHandler, path: str, body: bytes) -> bool:
    match = portal_router.match_route(path, _post_routes())
    if match is None:
        return False
    _dispatch_post_match(handler, match, body)
    return True


def is_portal_post_path(path: str) -> bool:
    return portal_router.match_route(path, _post_routes()) is not None


def handle_post_request(handler: BaseHTTPRequestHandler, path: str) -> bool:
    match = portal_router.match_route(path, _post_routes())
    if match is None:
        return False
    content_length = handler.headers.get("Content-Length")
    if content_length is None:
        _send_json(handler, HTTPStatus.LENGTH_REQUIRED, {"error": {"code": "missing_content_length", "message": "Missing Content-Length"}})
        return True
    try:
        length = int(content_length)
    except ValueError:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "invalid_content_length", "message": "Invalid Content-Length"}})
        return True
    if length < 0 or length > MAX_PORTAL_REQUEST_BYTES:
        _send_json(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": {"code": "request_body_too_large", "message": "Request body too large"}})
        return True
    _dispatch_post_match(handler, match, handler.rfile.read(length))
    return True


def _dispatch_post_match(handler: BaseHTTPRequestHandler, match: portal_router.RouteMatch, body: bytes) -> None:
    if not _validate_mutating_request(handler):
        return
    try:
        match.spec.handler(handler, match.params, body)
    except portal_state.PortalStateError:
        _send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, _portal_state_error_payload())


def _get_routes() -> tuple[portal_router.RouteSpec, ...]:
    return (
        portal_router.RouteSpec(portal_routes.PORTAL_ENDPOINT, _get_portal_html),
        portal_router.RouteSpec("/projects/{project_id}", _get_portal_html),
        portal_router.RouteSpec("/projects/{project_id}/artifacts/{artifact_id}/versions/{version_id}", _get_portal_html),
        portal_router.RouteSpec("/projects/{project_id}/artifacts/{artifact_id}", _get_portal_html),
        portal_router.RouteSpec("/projects/{project_id}/frames/{frame_id}", _get_portal_html),
        portal_router.RouteSpec("/assets/genomi-logo-transparent.png", _get_logo),
        portal_router.RouteSpec("/assets/{asset_name}", _get_template_asset),
        portal_router.RouteSpec("/api/context", _get_context),
        portal_router.RouteSpec("/api/genomes", _get_genomes),
        portal_router.RouteSpec("/api/agents", _get_agents),
        portal_router.RouteSpec("/api/projects", _get_projects),
        portal_router.RouteSpec("/api/projects/current", _get_current_project),
        portal_router.RouteSpec("/api/projects/{project_id}/active-context", _get_project_active_context),
        portal_router.RouteSpec("/api/projects/{project_id}/genomilab/board", _get_project_genomilab_board),
        portal_router.RouteSpec("/api/projects/{project_id}/genomilab/profile", _get_project_genomilab_profile),
        portal_router.RouteSpec("/api/projects/{project_id}/genomilab/integrations", _get_project_genomilab_integrations),
        portal_router.RouteSpec("/api/projects/{project_id}/events", _get_project_events),
        portal_router.RouteSpec("/api/projects/{project_id}/workspace/files", _get_project_workspace_files),
        portal_router.RouteSpec("/api/projects/{project_id}/workspace/file", _get_project_workspace_file),
        portal_router.RouteSpec("/api/projects/{project_id}/workspace/file-preview", _get_project_workspace_file_preview),
        portal_router.RouteSpec(portal_routes.project_frame_bundle_endpoint("{project_id}", "{frame_id}"), _get_frame_bundle),
        portal_router.RouteSpec("/api/projects/{project_id}/frames", _get_project_frames),
        portal_router.RouteSpec(portal_routes.project_artifact_version_script_bundle_endpoint("{project_id}", "{artifact_id}", "{version_id}"), _get_artifact_version_script_bundle),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/versions/{version_id}/file", _get_artifact_version_file),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/versions/{version_id}", _get_artifact_version),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/versions", _get_artifact_versions),
        portal_router.RouteSpec(portal_routes.project_artifact_script_bundle_endpoint("{project_id}", "{artifact_id}"), _get_artifact_script_bundle),
        portal_router.RouteSpec(portal_routes.project_artifact_bundle_endpoint("{project_id}", "{artifact_id}"), _get_artifact_bundle),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/metadata", _get_artifact_metadata),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/file", _get_artifact_file),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}", _get_artifact),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts", _get_project_artifacts),
        portal_router.RouteSpec("/api/source-lookups", _get_source_lookups),
        portal_router.RouteSpec("/api/tools", _get_tools),
        portal_router.RouteSpec("/api/projects/{project_id}", _get_project),
        portal_router.RouteSpec("/api/frames/{frame_id}/messages", _get_frame_messages),
        portal_router.RouteSpec("/api/frames/{frame_id}", _get_frame),
        portal_router.RouteSpec("/api/runs/{run_id}/events", _get_run_events),
        portal_router.RouteSpec("/api/runs/{run_id}/event-page", _get_run_event_page),
        portal_router.RouteSpec("/api/runs/{run_id}/result-package", _get_run_result_package),
        portal_router.RouteSpec("/api/runs/{run_id}", _get_run),
    )


def _post_routes() -> tuple[portal_router.RouteSpec, ...]:
    return (
        portal_router.RouteSpec("/api/projects", _post_project),
        portal_router.RouteSpec("/api/runs", _post_run),
        portal_router.RouteSpec("/api/evidence-sources/attach", _post_evidence_source_attach),
        portal_router.RouteSpec("/api/genomes/select", _post_genome_select),
        portal_router.RouteSpec("/api/projects/{project_id}/select", _post_project_select),
        portal_router.RouteSpec("/api/projects/{project_id}/rename", _post_project_rename),
        portal_router.RouteSpec("/api/projects/{project_id}/request", _post_project_request),
        portal_router.RouteSpec("/api/prompt/suggestion", _post_prompt_suggestion),
        portal_router.RouteSpec("/api/projects/{project_id}/active-context", _post_project_active_context),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/render", _post_project_artifact_render),
        portal_router.RouteSpec(portal_routes.project_artifact_import_endpoint("{project_id}"), _post_project_artifact_import),
        portal_router.RouteSpec(portal_routes.project_artifact_version_review_runs_endpoint("{project_id}", "{artifact_id}", "{version_id}"), _post_project_artifact_version_review_run),
        portal_router.RouteSpec(portal_routes.project_artifact_review_runs_endpoint("{project_id}", "{artifact_id}"), _post_project_artifact_review_run),
        portal_router.RouteSpec("/api/projects/{project_id}/artifacts/{artifact_id}/action", _post_project_artifact_action),
        portal_router.RouteSpec(portal_routes.project_frame_reviews_endpoint("{project_id}", "{frame_id}"), _post_frame_review),
        portal_router.RouteSpec("/api/projects/{project_id}/frames/{frame_id}/rename", _post_frame_rename),
        portal_router.RouteSpec("/api/frames/{frame_id}/message", _post_frame_message),
        portal_router.RouteSpec("/api/runs/{run_id}/approve-permission", _post_run_approve_permission),
        portal_router.RouteSpec("/api/runs/{run_id}/cancel", _post_run_cancel),
    )


def _get_portal_html(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    portal_assets.send_portal_html(handler)


def _get_logo(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    portal_assets.send_logo(handler)


def _get_template_asset(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    portal_assets.send_template_asset(handler, params["asset_name"])


def _get_project_genomilab_board(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    if query:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "invalid_query", "message": "Unexpected query parameters."}})
        return
    _send_genomilab_result(
        handler,
        lambda: portal_genomilab.project_board(params["project_id"]),
    )


def _get_project_genomilab_profile(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    if query:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "invalid_query", "message": "Unexpected query parameters."}})
        return
    _send_genomilab_result(
        handler,
        lambda: portal_genomilab.project_profile(params["project_id"]),
    )


def _get_project_genomilab_integrations(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    if query:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "invalid_query", "message": "Unexpected query parameters."}})
        return
    _send_genomilab_result(
        handler,
        lambda: portal_genomilab.project_integrations(params["project_id"]),
    )


def _get_artifact_file(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    portal_assets.send_artifact_file(handler, params["project_id"], params["artifact_id"])


def _get_artifact_version_file(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    portal_assets.send_artifact_version_file(handler, params["project_id"], params["artifact_id"], params["version_id"])


def _get_artifact(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    artifact = portal_store.get_project_artifact(params["project_id"], params["artifact_id"])
    if artifact is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, portal_store.public_artifact_detail(artifact))


def _get_artifact_metadata(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    bundle = portal_artifact_exports.project_artifact_metadata_bundle(params["project_id"], params["artifact_id"])
    if bundle is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
        return
    _send_json_download(handler, HTTPStatus.OK, bundle, filename=_artifact_metadata_filename(bundle))


def _get_artifact_bundle(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    bundle = portal_artifact_bundles.project_artifact_bundle(params["project_id"], params["artifact_id"])
    if bundle is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
        return
    _send_bytes_download(handler, HTTPStatus.OK, bundle.body, content_type=bundle.content_type, filename=bundle.filename)


def _get_artifact_script_bundle(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    bundle = portal_artifact_bundles.project_artifact_script_bundle(params["project_id"], params["artifact_id"])
    if bundle is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "rebuild script not available"}})
        return
    _send_bytes_download(handler, HTTPStatus.OK, bundle.body, content_type=bundle.content_type, filename=bundle.filename)


def _get_artifact_version_script_bundle(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    bundle = portal_artifact_bundles.project_artifact_script_bundle(params["project_id"], params["artifact_id"], params["version_id"])
    if bundle is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "rebuild script not available"}})
        return
    _send_bytes_download(handler, HTTPStatus.OK, bundle.body, content_type=bundle.content_type, filename=bundle.filename)


def _get_artifact_versions(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    versions = portal_store.list_project_artifact_versions(params["project_id"], params["artifact_id"])
    if versions is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, versions)


def _get_artifact_version(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    version = portal_store.get_project_artifact_version(params["project_id"], params["artifact_id"], params["version_id"])
    if version is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact version not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, portal_store.public_artifact_version_detail(version))


def _post_project_artifact_review_run(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    if _read_json_body(body) is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    result = portal_store.run_project_artifact_version_review(params["project_id"], params["artifact_id"])
    if result is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact version not found"}})
        return
    _send_json(handler, HTTPStatus.CREATED, result)


def _post_project_artifact_version_review_run(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    if _read_json_body(body) is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    result = portal_store.run_project_artifact_version_review(params["project_id"], params["artifact_id"], params["version_id"])
    if result is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact version not found"}})
        return
    _send_json(handler, HTTPStatus.CREATED, result)


def _post_frame_review(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    result = portal_run_service.start_frame_review(
        frame_id=params["frame_id"],
        project_id=params["project_id"],
        agent_id=str(payload.get("agentId") or "").strip() or None,
    )
    if result is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "conversation not found"}})
        return
    status = str(result.get("status") or "")
    if status == "busy":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "busy", "message": "Wait for the current conversation or review to finish."}})
        return
    if status == "no_answer":
        _send_json(handler, HTTPStatus.UNPROCESSABLE_ENTITY, {"error": {"code": "no_answer", "message": "There is no assistant answer to review yet."}})
        return
    if status == "unavailable":
        _send_json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": {"code": "reviewer_unavailable", "message": "No local assistant is available to review this conversation."}})
        return
    _send_json(handler, HTTPStatus.ACCEPTED, result)


def _get_context(handler: BaseHTTPRequestHandler, _params: dict[str, str], query: str) -> None:
    project_id = _single_query_value(query, "projectId")
    if project_id and portal_store.get_project(project_id) is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    _send_json(handler, HTTPStatus.OK, portal_context.context_payload(project_id))


def _get_genomes(handler: BaseHTTPRequestHandler, _params: dict[str, str], query: str) -> None:
    project_id = _single_query_value(query, "projectId")
    if project_id and portal_store.get_project(project_id) is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    try:
        _send_json(handler, HTTPStatus.OK, portal_genomes.genome_inventory_payload(project_id))
    except OperationError as exc:
        _send_json(handler, HTTPStatus.BAD_REQUEST, exc.to_json(operation="active_genome_index.list"))


def _get_agents(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    _send_json(handler, HTTPStatus.OK, {"agents": portal_agents.detect_agents()})


def _get_projects(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    _send_json(handler, HTTPStatus.OK, {"projects": portal_store.list_projects()})


def _get_current_project(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    _send_json(handler, HTTPStatus.OK, {"project": portal_store.ensure_default_project()})


def _get_project_active_context(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    if portal_store.get_project(params["project_id"]) is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    active_context = portal_active_context.active_context_for_project(params["project_id"])
    _send_json(handler, HTTPStatus.OK, {"active_context": active_context or {"status": "empty", "project_id": params["project_id"]}})


def _get_project_frames(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    portal_run_service.reconcile_stale_persisted_runs()
    frames = portal_store.list_project_frames(params["project_id"])
    if frames is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, frames)


def _get_frame_bundle(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    bundle = portal_frame_bundles.project_frame_bundle(params["project_id"], params["frame_id"])
    if bundle is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "frame not found"}})
        return
    _send_bytes_download(handler, HTTPStatus.OK, bundle.body, content_type=bundle.content_type, filename=bundle.filename)


def _get_project_artifacts(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    artifacts = portal_store.list_project_artifacts(params["project_id"])
    if artifacts is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, artifacts)


def _get_project_workspace_files(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    files = portal_workspace_files.list_project_workspace_files(params["project_id"])
    if files is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, files)


def _get_project_workspace_file_preview(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    relative_path = _single_query_value(query, "path")
    preview = portal_workspace_files.preview_project_workspace_file(params["project_id"], relative_path)
    status = _workspace_file_preview_http_status(preview)
    _send_json(handler, status, _workspace_file_preview_payload(preview, status))


def _get_project_workspace_file(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    relative_path = _single_query_value(query, "path")
    document = portal_workspace_files.read_project_workspace_document_file(params["project_id"], relative_path)
    status = _workspace_file_document_http_status(document.status)
    if document.status != "available":
        _send_json(
            handler,
            status,
            {
                "status": document.status,
                "error": {
                    "code": document.status,
                    "message": document.reason or "Project document preview failed.",
                },
            },
        )
        return
    _send_bytes_inline(handler, status, document.body, content_type=document.content_type, filename=document.name)


def _get_project_events(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    if portal_store.get_project(params["project_id"]) is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    portal_project_events.stream_project_events(handler, params["project_id"], query)


def _workspace_file_preview_http_status(preview: dict[str, object]) -> HTTPStatus:
    return {
        "available": HTTPStatus.OK,
        "unavailable": HTTPStatus.OK,
        "missing_path": HTTPStatus.BAD_REQUEST,
        "path_escape": HTTPStatus.BAD_REQUEST,
        "missing_project": HTTPStatus.NOT_FOUND,
        "not_found": HTTPStatus.NOT_FOUND,
        "unreadable": HTTPStatus.FORBIDDEN,
    }.get(str(preview.get("status") or ""), HTTPStatus.INTERNAL_SERVER_ERROR)


def _workspace_file_preview_payload(preview: dict[str, object], http_status: HTTPStatus) -> dict[str, object]:
    if http_status < HTTPStatus.BAD_REQUEST:
        return preview
    code = str(preview.get("status") or "preview_error")
    message = str(preview.get("reason") or "Project file preview failed.")
    return {
        **preview,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _workspace_file_document_http_status(status: str) -> HTTPStatus:
    return {
        "available": HTTPStatus.OK,
        "unavailable": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "unsupported_type": HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "missing_path": HTTPStatus.BAD_REQUEST,
        "path_escape": HTTPStatus.BAD_REQUEST,
        "missing_project": HTTPStatus.NOT_FOUND,
        "not_found": HTTPStatus.NOT_FOUND,
        "unreadable": HTTPStatus.FORBIDDEN,
    }.get(str(status or ""), HTTPStatus.INTERNAL_SERVER_ERROR)


def _get_tools(handler: BaseHTTPRequestHandler, _params: dict[str, str], query: str) -> None:
    capability = _single_query_value(query, "capability")
    namespace = _single_query_value(query, "namespace")
    try:
        _send_json(handler, HTTPStatus.OK, operation_discovery_payload(capability=capability, namespace=namespace))
    except OperationError as exc:
        _send_json(handler, HTTPStatus.BAD_REQUEST, exc.to_json(operation="tools/list"))


def _get_source_lookups(handler: BaseHTTPRequestHandler, _params: dict[str, str], _query: str) -> None:
    _send_json(handler, HTTPStatus.OK, portal_source_lookups.source_lookup_payload())


def _post_evidence_source_attach(handler: BaseHTTPRequestHandler, _params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    prepared = portal_source_lookups.attach_evidence_source_payload(payload)
    if prepared is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "evidence source not found"}})
        return
    _send_json(handler, HTTPStatus.OK, prepared)


def _post_genome_select(handler: BaseHTTPRequestHandler, _params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    project_id = _payload_text(payload, "projectId", "project_id")
    if not project_id:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "projectId required"}})
        return
    try:
        _send_json(handler, HTTPStatus.OK, portal_genomes.select_active_genome(payload, project_id=project_id))
    except OperationError as exc:
        _send_json(handler, HTTPStatus.BAD_REQUEST, exc.to_json(operation="active_genome_index.approve_access"))


def _get_project(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    project = portal_store.get_project(params["project_id"])
    if project is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, project)


def _get_frame_messages(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    frame = _frame_for_request(params["frame_id"], query)
    if frame is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "frame not found"}})
        return
    _send_json(handler, HTTPStatus.OK, portal_store.list_frame_messages(params["frame_id"]))


def _get_frame(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    frame = _frame_for_request(params["frame_id"], query)
    if frame is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "frame not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, portal_store.public_frame(frame))


def _frame_for_request(frame_id: str, query: str) -> JsonObject | None:
    project_id = _single_query_value(query, "projectId")
    frame = portal_store.get_frame_for_project(frame_id, project_id) if project_id else portal_store.get_frame(frame_id)
    if frame is None:
        return None
    run_id = str(frame.get("run_id") or "")
    if frame.get("status") == "processing" and run_id:
        portal_run_service.reconcile_stale_persisted_runs(run_id=run_id)
        return portal_store.get_frame_for_project(frame_id, project_id) if project_id else portal_store.get_frame(frame_id)
    return frame


def _get_run_events(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    if portal_run_events.get_run(params["run_id"]) is not None:
        portal_run_events.stream_run_events(handler, params["run_id"], query)
        return
    status = portal_run_service.get_run_status(params["run_id"])
    if status is None:
        portal_run_events.stream_run_events(handler, params["run_id"], query)
        return
    portal_run_events.stream_terminal_run_status(handler, status, query)


def _get_run(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    status = portal_run_service.get_run_status(params["run_id"])
    if status is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "run not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, status)


def _get_run_event_page(handler: BaseHTTPRequestHandler, params: dict[str, str], query: str) -> None:
    page = portal_run_event_pages.run_event_page(
        params["run_id"],
        after_event_id=_optional_int_query(query, "after_event_id"),
        limit=_optional_int_query(query, "limit"),
    )
    if page is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "run not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, page)


def _get_run_result_package(handler: BaseHTTPRequestHandler, params: dict[str, str], _query: str) -> None:
    package = portal_run_packages.run_result_package(params["run_id"])
    if package is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "run not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, package)


def _post_project(handler: BaseHTTPRequestHandler, _params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body) or {}
    name = str(payload.get("name") or portal_store.DEFAULT_PROJECT_NAME).strip() or portal_store.DEFAULT_PROJECT_NAME
    project = portal_store.create_project(name=name)
    _send_json(handler, HTTPStatus.CREATED, {"project": project})


def _post_project_select(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    if _read_json_body(body) is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    project = portal_store.select_project(params["project_id"])
    if project is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    _send_json(handler, HTTPStatus.OK, {"project": project})


def _post_project_rename(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    name = _payload_text(payload, "name")
    if not name:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "workspace name required"}})
        return
    project = portal_store.rename_project(params["project_id"], name)
    if project is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    _send_json(handler, HTTPStatus.OK, {"project": project})


def _post_project_request(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    _start_run_from_payload(handler, payload, project_id=params["project_id"])


def _post_run(handler: BaseHTTPRequestHandler, _params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    project_id = _payload_text(payload, "projectId", "project_id")
    if not project_id:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "projectId required"}})
        return
    _start_run_from_payload(handler, payload, project_id=project_id, frame_id=_payload_text(payload, "frameId", "frame_id"))


def _start_run_from_payload(
    handler: BaseHTTPRequestHandler,
    payload: JsonObject,
    *,
    project_id: str,
    frame_id: str | None = None,
) -> None:
    message = portal_turns.message_from_payload(payload)
    if not message:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "message required"}})
        return
    selected_evidence = portal_turns.selected_evidence_from_payload(payload)
    agent_id = _runnable_agent_id_from_payload(payload)
    if not agent_id:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "no_agent_available", "message": "No supported assistant CLI was found on PATH."}})
        return
    if frame_id:
        response = portal_run_service.start_frame_message(
            frame_id=frame_id,
            project_id=project_id,
            message=message,
            agent_id=agent_id,
            selected_evidence=selected_evidence,
            genome_context_mode=_payload_text(payload, "genomeContextMode", "genome_context_mode"),
        )
        _send_frame_run_response(handler, response)
        return
    response = portal_run_service.start_project_request(
        project_id=project_id,
        message=message,
        agent_id=agent_id,
        selected_evidence=selected_evidence,
        genome_context_mode=_payload_text(payload, "genomeContextMode", "genome_context_mode"),
        started_from_selected_material=_payload_bool(
            payload,
            "startedFromSelectedMaterial",
            "started_from_selected_material",
        ),
        source_frame_id=_payload_text(payload, "sourceFrameId", "source_frame_id"),
    )
    _send_project_run_response(handler, response)


def _post_prompt_suggestion(handler: BaseHTTPRequestHandler, _params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    _send_json(handler, HTTPStatus.OK, portal_prompt_suggestions.prompt_suggestion_payload(payload))


def _post_project_active_context(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    if portal_store.get_project(params["project_id"]) is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
        return
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    active_context = portal_active_context.update_project_active_context(params["project_id"], payload)
    _send_json(handler, HTTPStatus.OK, {"active_context": active_context})


def _post_project_artifact_render(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body) or {}
    result = portal_artifact_renderers.start_artifact_render(params["project_id"], payload)
    if result.get("error"):
        status = HTTPStatus.NOT_FOUND if result["error"].get("code") == "not_found" else HTTPStatus.BAD_REQUEST
        _send_json(handler, status, result)
    else:
        _send_json(handler, HTTPStatus.ACCEPTED, result)


def _post_project_artifact_import(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    status, result = portal_file_imports.import_project_file(params["project_id"], payload)
    _send_json(handler, status, result)


def _post_project_artifact_action(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    action = str(payload.get("action") or "").strip().lower()
    project_id = params["project_id"]
    artifact_id = params["artifact_id"]
    if action == "rename":
        title = portal_turns.prompt_safe_text(str(payload.get("title") or "")).strip()
        if not title:
            _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "artifact title required"}})
            return
        artifact = portal_store.rename_project_artifact(project_id, artifact_id, title=title)
        _send_artifact_action_result(handler, artifact)
        return
    flag_action = _ARTIFACT_FLAG_ACTIONS.get(action)
    if flag_action is not None:
        operation, value = flag_action
        artifact = operation(project_id, artifact_id, value)
        _send_artifact_action_result(handler, artifact)
        return
    if action == "delete":
        artifact = portal_store.delete_project_artifact(project_id, artifact_id)
        if artifact is None:
            _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
        else:
            _send_json(handler, HTTPStatus.OK, {"ok": True, "deleted": True, "artifact_id": artifact_id})
        return
    _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "unsupported artifact action"}})


def _send_artifact_action_result(handler: BaseHTTPRequestHandler, artifact: JsonObject | None) -> None:
    if artifact is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "artifact not found"}})
    else:
        _send_json(handler, HTTPStatus.OK, {"ok": True, "artifact": portal_store.public_artifact_detail(artifact)})


def _post_frame_message(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    project_id = _payload_text(payload, "projectId", "project_id")
    if not project_id:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "projectId required"}})
        return
    _start_run_from_payload(handler, payload, project_id=project_id, frame_id=params["frame_id"])


def _post_frame_rename(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    title = _payload_text(payload, "title")
    if not title:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "conversation title required"}})
        return
    frame = portal_store.rename_frame(params["project_id"], params["frame_id"], title)
    if frame is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "conversation not found"}})
        return
    _send_json(handler, HTTPStatus.OK, {"frame": frame})


def _send_project_run_response(handler: BaseHTTPRequestHandler, response: JsonObject | None) -> None:
    if response is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "project not found"}})
    else:
        _send_json(handler, HTTPStatus.ACCEPTED, response)


def _send_frame_run_response(handler: BaseHTTPRequestHandler, response: JsonObject | None) -> None:
    if response is None:
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "frame not found"}})
    elif response.get("status") == "busy":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "frame_busy", "message": "frame is already processing"}})
    elif response.get("status") == "wrong_project":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "frame_wrong_project", "message": "frame does not belong to project"}})
    else:
        _send_json(handler, HTTPStatus.ACCEPTED, response)


def _post_run_cancel(handler: BaseHTTPRequestHandler, params: dict[str, str], _body: bytes) -> None:
    result = portal_run_service.cancel_run_by_id(params["run_id"])
    if result.state == "missing":
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "run not found"}})
    elif result.state == "not_active":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "run_not_active", "message": "run is not active"}, "run": result.run_status})
    elif result.state == "terminal":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "run_terminal", "message": "run is already terminal"}, "run": result.run_status})
    else:
        _send_json(handler, HTTPStatus.OK, {"ok": True, "run": result.run_status})


def _post_run_approve_permission(handler: BaseHTTPRequestHandler, params: dict[str, str], body: bytes) -> None:
    payload = _read_json_body(body)
    if payload is None:
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": "JSON object required"}})
        return
    result = portal_run_service.approve_run_permission_and_retry(
        run_id=params["run_id"],
        permission=payload.get("permission") if "permission" in payload else payload,
    )
    status = str(result.get("status") or "")
    if status == "missing":
        _send_json(handler, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": result.get("message") or "run not found"}})
    elif status == "busy":
        _send_json(handler, HTTPStatus.CONFLICT, {"error": {"code": "run_busy", "message": result.get("message") or "run is still active"}})
    elif status == "bad_request":
        _send_json(handler, HTTPStatus.BAD_REQUEST, {"error": {"code": "bad_request", "message": result.get("message") or "invalid permission approval"}})
    else:
        _send_json(handler, HTTPStatus.ACCEPTED, result)


def _runnable_agent_id_from_payload(payload: JsonObject) -> str | None:
    requested = _payload_text(payload, "agentId", "agent_id")
    if requested:
        agents = {str(agent["id"]): agent for agent in portal_agents.detect_agents()}
        return requested if agents.get(requested, {}).get("runnable") else None
    return portal_agents.default_agent_id()


def _payload_text(payload: JsonObject, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _payload_bool(payload: JsonObject, *keys: str) -> bool:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in {"true", "1", "yes", "on"}:
                return True
            if clean in {"false", "0", "no", "off", ""}:
                return False
    return False


def _single_query_value(query: str, key: str) -> str | None:
    values = parse_qs(query).get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _optional_int_query(query: str, key: str) -> int | None:
    value = _single_query_value(query, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _read_json_body(body: bytes) -> JsonObject | None:
    if len(body) > MAX_PORTAL_REQUEST_BYTES:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_mutating_request(handler: BaseHTTPRequestHandler) -> bool:
    content_type = str(handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        _send_json(
            handler,
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            {"error": {"code": "unsupported_media_type", "message": "Portal POST requests require application/json."}},
        )
        return False
    origin = str(handler.headers.get("Origin") or "").strip()
    if origin and not _is_same_origin(handler, origin):
        _send_json(
            handler,
            HTTPStatus.FORBIDDEN,
            {"error": {"code": "forbidden_origin", "message": "Portal POST origin does not match this local server."}},
        )
        return False
    expected = str(getattr(handler.server, "portal_csrf_token", ""))
    supplied = str(handler.headers.get(CSRF_HEADER) or "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        _send_json(
            handler,
            HTTPStatus.FORBIDDEN,
            {"error": {"code": "csrf_required", "message": "Portal POST request is missing a valid CSRF token."}},
        )
        return False
    return True


def _is_same_origin(handler: BaseHTTPRequestHandler, origin: str) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = str(handler.headers.get("Host") or "")
    return parsed.netloc.lower() == host.lower()


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    if headers:
        for name, value in headers.items():
            handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def _send_genomilab_result(
    handler: BaseHTTPRequestHandler,
    operation: Callable[[], JsonObject],
    *,
    success_status: int = HTTPStatus.OK,
) -> None:
    try:
        result = operation()
    except portal_genomilab.PortalGenomiLabError as exc:
        _send_json(handler, exc.http_status, exc.to_json())
        return
    except LocalSQLiteError:
        _send_json(
            handler,
            HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "error": {
                    "code": "genomilab_storage_unavailable",
                    "message": (
                        "Genomi Lab could not open its local records. "
                        "Check the private Genomi data directory and retry."
                    ),
                }
            },
        )
        return
    _send_json(handler, success_status, result)


def _send_json_download(handler: BaseHTTPRequestHandler, status: int, payload: Any, *, filename: str) -> None:
    _send_json(
        handler,
        status,
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _send_bytes_download(handler: BaseHTTPRequestHandler, status: int, body: bytes, *, content_type: str, filename: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _send_bytes_inline(handler: BaseHTTPRequestHandler, status: int, body: bytes, *, content_type: str, filename: str) -> None:
    safe_filename = portal_bundle_files.download_safe_token(filename or "project-file", fallback="project-file")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", f'inline; filename="{safe_filename}"')
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _artifact_metadata_filename(bundle: JsonObject) -> str:
    artifact = bundle.get("artifact") if isinstance(bundle.get("artifact"), dict) else {}
    token = portal_bundle_files.download_safe_token(str(artifact.get("id") or bundle.get("artifact_id") or "artifact"), fallback="artifact")
    return f"{token}-metadata.json"


def _portal_state_error_payload() -> JsonObject:
    return {"error": {"code": "portal_state_error", "message": "Portal state is unavailable."}}
