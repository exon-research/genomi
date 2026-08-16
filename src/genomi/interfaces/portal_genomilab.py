"""Project-scoped GenomiLab projections for the unified research portal.

GenomiLab remains the canonical owner of private profile and investigation data.
The portal persists only the identity binding needed to open the right board.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from ..lab.store import GenomiLabStore
from ..operations.registry import all_operations
from ..runtime.external_credentials import credential_state as external_credential_state
from . import portal_project_events, portal_project_genomes, portal_state, portal_store

JsonObject = dict[str, Any]
_BINDING_KEY = "genomilab_binding"
_SERVICE_LOCK = threading.Lock()
_RESEARCH_PROVIDER_OPERATIONS = {
    "paperclip": ("paperclip.search_biomedical", "paperclip.retrieve_document_evidence"),
    "biohub-esm": ("biohub.compare_protein_embeddings",),
    "proto": ("proto.search_tools", "proto.describe_tool_schema", "proto.run_tool"),
}
_RESEARCH_PROVIDER_CREDENTIAL_IDS = {
    "paperclip": "paperclip",
    "biohub-esm": "biohub",
    "proto": "proto",
}


class _GenomiLabApplication(Protocol):
    def bootstrap_workspace(self) -> JsonObject: ...
    def molecular_profile(self) -> JsonObject: ...
    def integrations(self) -> JsonObject: ...
    def list_investigations(self) -> list[JsonObject]: ...
    def investigation(self, investigation_id: str) -> JsonObject: ...


_SERVICES: dict[tuple[str, str], _GenomiLabApplication] = {}


@dataclass(frozen=True, slots=True)
class PortalGenomiLabError(RuntimeError):
    code: str
    message: str
    http_status: int = 400

    def to_json(self) -> JsonObject:
        return {"error": {"code": self.code, "message": self.message}}


def project_board(
    project_id: str,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    workspace = application.bootstrap_workspace()
    if workspace.get("status") != "ready":
        return {
            "status": workspace.get("status", "setup_required"),
            "setup": workspace.get("setup"),
            "binding": None,
            "investigation": None,
            "investigations": [],
        }

    binding = project_binding(project_id, root=root)
    investigations = application.list_investigations()
    active = None
    if binding:
        try:
            active = application.investigation(str(binding["investigation_id"]))
        except PortalGenomiLabError as exc:
            if exc.code != "investigation_not_found":
                raise
            binding = None
    if active is None and investigations:
        active = investigations[0]
    return {
        "status": "ready",
        "binding": binding,
        "investigation": _board_investigation(active),
        "investigations": [
            _investigation_summary(investigation)
            for investigation in investigations
            if isinstance(investigation, dict)
        ],
    }


def project_resume_context(
    project_id: str,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    """Return the minimal canonical state needed to continue a Lab turn.

    This projection deliberately excludes patient-authored content, hypothesis
    statements, specialist analyses, and filesystem details. It carries only
    opaque identifiers, revisions, and lifecycle states that the Main agent
    needs to address the next canonical Lab operation.
    """

    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    workspace = application.bootstrap_workspace()
    if workspace.get("status") != "ready":
        return {"status": workspace.get("status", "setup_required")}

    binding = project_binding(project_id, root=root)
    investigations = application.list_investigations()
    active: JsonObject | None = None
    if binding:
        try:
            active = application.investigation(str(binding["investigation_id"]))
        except PortalGenomiLabError as exc:
            if exc.code != "investigation_not_found":
                raise
    if active is None and investigations:
        candidate = investigations[0]
        active = candidate if isinstance(candidate, dict) else None
    return {
        "status": "ready",
        "active_investigation": _resume_investigation(active),
    }


def project_profile(
    project_id: str,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    workspace = application.bootstrap_workspace()
    if workspace.get("status") != "ready":
        return {
            "status": workspace.get("status", "setup_required"),
            "setup": workspace.get("setup"),
            "profile": None,
        }
    return {"status": "ready", "profile": application.molecular_profile()}


def project_integrations(
    project_id: str,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    """Return redacted provider state for the project's current Genomi user."""

    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    workspace = application.bootstrap_workspace()
    if workspace.get("status") != "ready":
        return {
            "status": workspace.get("status", "setup_required"),
            "setup": workspace.get("setup"),
            "integrations": [],
        }
    return application.integrations()


def _bind_observed_investigation(
    project_id: str,
    *,
    investigation_id: str,
    frame_id: str,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    clean_investigation_id = str(investigation_id or "").strip()
    clean_frame_id = str(frame_id or "").strip()
    if not clean_investigation_id:
        raise PortalGenomiLabError(
            "investigation_required", "Choose an investigation to link."
        )
    if not clean_frame_id or portal_store.get_frame_for_project(
        clean_frame_id, project_id, root
    ) is None:
        raise PortalGenomiLabError(
            "conversation_required",
            "Open the inquiry conversation before linking its investigation.",
            http_status=409,
        )
    investigation = (
        service or _application_service(project_id, root=root)
    ).investigation(clean_investigation_id)
    user_id = str(investigation.get("user_id") or "")

    def mutate(state: JsonObject) -> JsonObject:
        project = state["projects"].get(project_id)
        if not isinstance(project, dict):
            raise PortalGenomiLabError(
                "project_not_found", "Workspace not found.", http_status=404
            )
        binding = {
            "investigation_id": clean_investigation_id,
            "frame_id": clean_frame_id,
            "user_id": user_id,
        }
        project[_BINDING_KEY] = binding
        return binding

    binding = portal_state.mutate_state(mutate, root)
    _emit_status(
        project_id,
        "genomilab_investigation_changed",
        status=str(investigation.get("status") or "linked"),
        reason="investigation_linked",
        investigation_id=clean_investigation_id,
        frame_id=clean_frame_id,
        root=root,
    )
    return binding


def project_binding(
    project_id: str, *, root: str | Path | None = None
) -> JsonObject | None:
    state = portal_state.read_state(root)
    project = state["projects"].get(str(project_id or "").strip())
    binding = project.get(_BINDING_KEY) if isinstance(project, dict) else None
    if not isinstance(binding, dict):
        return None
    investigation_id = str(binding.get("investigation_id") or "").strip()
    frame_id = str(binding.get("frame_id") or "").strip()
    if not investigation_id or not frame_id:
        return None
    return {
        "investigation_id": investigation_id,
        "frame_id": frame_id,
        "user_id": str(binding.get("user_id") or "") or None,
    }


class _PortalGenomiLabApplication:
    """Project-bound projection over the local Genomi Lab record domain.

    This adapter deliberately owns no assistant runner or provider secret layer.
    It reports only whether focused provider operations are registered and
    whether the shared credential resolver found a complete configuration.
    """

    def __init__(
        self,
        *,
        session_id: str,
        context_provider: Callable[[], JsonObject],
    ) -> None:
        self.session_id = session_id
        self._context_provider = context_provider
        self.store = GenomiLabStore()

    @contextmanager
    def _current_user(self) -> Iterator[str]:
        expected = str(self._context_provider().get("active_user_id") or "").strip()
        if not expected:
            raise PortalGenomiLabError(
                "genomi_user_required",
                "Select a Genomi user and Active Genome Index for this workspace.",
                http_status=409,
            )

        def require_same_user() -> None:
            current = str(
                self._context_provider().get("active_user_id") or ""
            ).strip()
            if current != expected:
                raise PortalGenomiLabError(
                    "genomi_user_changed",
                    "The workspace user changed during this operation.",
                    http_status=409,
                )

        with self.store.current_user_authority_guard(require_same_user):
            yield expected

    def bootstrap_workspace(self) -> JsonObject:
        user_id = str(self._context_provider().get("active_user_id") or "").strip()
        if not user_id:
            return {
                "status": "setup_required",
                "setup": {
                    "action": "Select a Genomi user and Active Genome Index for this workspace."
                },
            }
        with self._current_user():
            self.store.open_workspace(user_id)
        return {"status": "ready"}

    def molecular_profile(self) -> JsonObject:
        with self._current_user() as user_id:
            profile = dict(self.store.open_workspace(user_id)["profile"])
        context = self._context_provider()
        profile["genome"] = {
            "agi_id": context.get("active_agi_id"),
            "access_approved": bool(context.get("active_agi_id")),
        }
        return profile

    def list_investigations(self) -> list[JsonObject]:
        with self._current_user() as user_id:
            records: list[JsonObject] = []
            for investigation in self.store.list_investigations(user_id):
                investigation_id = str(investigation.get("investigation_id") or "")
                if not investigation_id:
                    continue
                try:
                    view = self.store.read_portal_investigation(
                        investigation_id, include_history=True
                    )
                except (KeyError, ValueError):
                    continue
                context = view.get("context")
                session = (
                    str(context.get("workspace_session_id") or "")
                    if isinstance(context, dict)
                    else ""
                )
                if session == self.session_id:
                    records.append(view)
            return records

    def investigation(self, investigation_id: str) -> JsonObject:
        view: JsonObject | None = None
        authorized = False
        with self._current_user() as user_id:
            try:
                candidate = self.store.read_portal_investigation(
                    investigation_id, include_history=True
                )
            except (KeyError, ValueError):
                candidate = None
            if isinstance(candidate, dict):
                investigation = candidate.get("investigation")
                context = candidate.get("context")
                workspace_session_id = (
                    str(context.get("workspace_session_id") or "")
                    if isinstance(context, dict)
                    else ""
                )
                authorized = (
                    isinstance(investigation, dict)
                    and str(investigation.get("user_id") or "") == user_id
                    and workspace_session_id == self.session_id
                )
                view = candidate
        if not authorized or view is None:
            raise PortalGenomiLabError(
                "investigation_not_found",
                "Investigation not found.",
                http_status=404,
            )
        return view

    def integrations(self) -> JsonObject:
        registered_operations = {
            str(operation.get("name") or "") for operation in all_operations()
        }
        return {
            "status": "ready",
            "integrations": [
                _research_provider_readiness(provider, registered_operations)
                for provider in _RESEARCH_PROVIDER_OPERATIONS
            ],
        }

def _research_provider_readiness(
    provider: str, registered_operations: set[str]
) -> JsonObject:
    operations = _RESEARCH_PROVIDER_OPERATIONS[provider]
    available_operations = [
        operation for operation in operations if operation in registered_operations
    ]
    capability_available = len(available_operations) == len(operations)
    credential = external_credential_state(
        _RESEARCH_PROVIDER_CREDENTIAL_IDS[provider]
    )
    credential_configured = bool(credential.get("configured"))
    if not capability_available:
        connection_state = "capability_unavailable"
    elif credential_configured:
        connection_state = "ready"
    else:
        connection_state = "credentials_required"
    return {
        "provider": provider,
        "connection_state": connection_state,
        "capability_state": "available" if capability_available else "unavailable",
        "credential_state": "configured" if credential_configured else "not_configured",
        "investigation_operations": available_operations,
    }


def _application_service(
    project_id: str, *, root: str | Path | None
) -> _GenomiLabApplication:
    clean_project_id = str(project_id or "").strip()
    root_key = str(portal_state.state_path(root).parent.resolve())
    key = (root_key, clean_project_id)
    with _SERVICE_LOCK:
        application = _SERVICES.get(key)
        if application is None:
            # Construction discovers capabilities but does not start or resume an
            # assistant task. The existing portal run remains the only runner.
            application = _PortalGenomiLabApplication(
                # Lab operations derive their durable session authority from
                # context_scope(), whose id is the resolved GENOMI_CONTEXT path.
                # Use that same project-stable boundary in the portal projection
                # so a recreated service sees the investigation created by MCP.
                session_id=str(
                    portal_project_genomes.project_context_path(
                        clean_project_id, root=root
                    ).expanduser().resolve(strict=False)
                ),
                context_provider=lambda: _project_context(
                    clean_project_id, root=root
                ),
            )
            _SERVICES[key] = application
        return application


def _project_context(
    project_id: str, *, root: str | Path | None
) -> JsonObject:
    binding = portal_store.project_genome_binding(project_id, root=root)
    if not isinstance(binding, dict):
        return {
            "active_user_id": f"portal-{str(project_id or '').strip()}",
            "active_agi_id": None,
            "agis": {},
        }
    return {
        "active_user_id": str(binding.get("user_id") or "").strip() or None,
        "active_agi_id": str(binding.get("agi_id") or "").strip() or None,
        "agis": {},
    }


def _require_project(project_id: str, *, root: str | Path | None) -> None:
    if portal_store.get_project(str(project_id or "").strip(), root) is None:
        raise PortalGenomiLabError(
            "project_not_found", "Workspace not found.", http_status=404
        )


def _investigation_summary(investigation: JsonObject) -> JsonObject:
    record = investigation.get("investigation")
    if isinstance(record, dict):
        investigation = record
    return {
        "investigation_id": investigation.get("investigation_id"),
        "question": investigation.get("question"),
        "disease_scope": investigation.get("disease_scope"),
        "status": investigation.get("status"),
        "updated_at": investigation.get("updated_at"),
    }


def _latest_hypothesis_versions(items: object) -> dict[str, JsonObject]:
    latest: dict[str, JsonObject] = {}
    if not isinstance(items, list):
        return latest
    for item in items:
        if not isinstance(item, dict):
            continue
        logical_id = str(item.get("logical_hypothesis_id") or "").strip()
        if not logical_id:
            continue
        current = latest.get(logical_id)
        if current is None or int(item.get("version") or 0) > int(
            current.get("version") or 0
        ):
            latest[logical_id] = item
    return latest


def _latest_information_gap_versions(items: object) -> dict[str, JsonObject]:
    latest: dict[str, JsonObject] = {}
    if not isinstance(items, list):
        return latest
    for item in items:
        if not isinstance(item, dict):
            continue
        logical_id = str(item.get("logical_information_gap_id") or "").strip()
        if not logical_id:
            continue
        current = latest.get(logical_id)
        if current is None or int(item.get("version") or 0) > int(
            current.get("version") or 0
        ):
            latest[logical_id] = item
    return latest


def _specialist_workstreams(investigation: JsonObject) -> list[JsonObject]:
    analyses = {
        str(item.get("specialist_assignment_id") or ""): item
        for item in investigation.get("specialist_analyses") or []
        if isinstance(item, dict) and item.get("specialist_assignment_id")
    }
    workstreams: list[JsonObject] = []
    for assignment in investigation.get("specialist_assignments") or []:
        if not isinstance(assignment, dict):
            continue
        projected = dict(assignment)
        analysis = analyses.get(str(assignment.get("specialist_assignment_id") or ""))
        if analysis:
            finding = _specialist_finding(analysis.get("general_analysis"))
            if finding:
                projected["finding"] = finding
            gaps = _specialist_gaps(analysis)
            if gaps:
                projected["gaps"] = gaps
        workstreams.append(projected)
    return workstreams


def _specialist_finding(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    nested = value.get("general_analysis")
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    if isinstance(nested, dict):
        value = nested
    for key in ("conclusion", "summary", "finding", "caution"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _specialist_gaps(analysis: JsonObject) -> list[str]:
    direct = _text_list(analysis.get("gaps"))
    if direct:
        return direct
    general = analysis.get("general_analysis")
    if not isinstance(general, dict):
        return []
    nested = general.get("general_analysis")
    if isinstance(nested, dict):
        general = nested
    return _text_list(general.get("key_gaps") or general.get("gaps"))


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _board_investigation(investigation: JsonObject | None) -> JsonObject | None:
    if not isinstance(investigation, dict):
        return None
    result = _investigation_summary(investigation)
    record = investigation.get("investigation")
    record = record if isinstance(record, dict) else investigation
    if "current_hypotheses" in investigation:
        current_hypotheses = investigation.get("current_hypotheses")
        hypotheses = current_hypotheses if isinstance(current_hypotheses, list) else []
    else:
        hypotheses = list(
            _latest_hypothesis_versions(
                investigation.get("hypothesis_versions") or []
            ).values()
        )
    workstreams = _specialist_workstreams(investigation)
    brief_versions = investigation.get("brief_versions") or []
    if "current_brief_version" in investigation:
        current_brief = investigation.get("current_brief_version")
    else:
        current_brief = max(
            (item for item in brief_versions if isinstance(item, dict)),
            key=lambda item: int(item.get("version") or 0),
            default=None,
        )
    evidence_snapshots = investigation.get("evidence_snapshots") or []
    cycles = investigation.get("cycles") or []
    research_artifacts = investigation.get("research_artifacts") or []
    evidence_records = investigation.get("evidence_records") or []
    brief = current_brief.get("brief") if isinstance(current_brief, dict) else None
    brief = brief if isinstance(brief, dict) else {}
    information_gaps = list(
        _latest_information_gap_versions(
            investigation.get("information_gap_versions") or []
        ).values()
    )
    open_information_gaps = [
        item for item in information_gaps if str(item.get("status") or "open") == "open"
    ]
    result.update(
        {
            "private_context_status": investigation.get("private_context_status"),
            "cycles": cycles,
            "cycle_count": len(cycles),
            "evidence_snapshots": evidence_snapshots,
            "brief_versions": brief_versions,
            "research_artifacts": research_artifacts,
            "research_artifact_count": len(research_artifacts),
            "evidence_records": evidence_records,
            "evidence_count": len(evidence_records),
            "hypothesis_count": len(hypotheses),
            "gap_count": len(open_information_gaps),
            "specialist_count": len(workstreams),
            "hypotheses": hypotheses,
            "specialist_workstreams": workstreams,
            "information_gaps": information_gaps,
            "patient_questions": brief.get("professional_questions") or [],
            "recommended_next_steps": brief.get("confirmation_needs") or [],
            "current_brief_version": (
                current_brief.get("version")
                if isinstance(current_brief, dict)
                else current_brief
            ),
            "current_brief": current_brief,
            "domain_revision": record.get("domain_revision"),
        }
    )
    return result


def _resume_investigation(investigation: JsonObject | None) -> JsonObject | None:
    if not isinstance(investigation, dict):
        return None
    record = investigation.get("investigation")
    record = record if isinstance(record, dict) else investigation
    cycles = [
        item for item in investigation.get("cycles") or [] if isinstance(item, dict)
    ]
    assignments = [
        item
        for item in investigation.get("specialist_assignments") or []
        if isinstance(item, dict)
    ]
    evidence_snapshots = [
        item
        for item in investigation.get("evidence_snapshots") or []
        if isinstance(item, dict)
    ]
    brief_versions = [
        item
        for item in investigation.get("brief_versions") or []
        if isinstance(item, dict)
    ]
    latest_hypotheses = _latest_hypothesis_versions(
        investigation.get("hypothesis_versions") or []
    )

    latest_cycle = max(
        cycles, key=lambda item: int(item.get("ordinal") or 0), default=None
    )
    latest_evidence = max(
        evidence_snapshots,
        key=lambda item: int(item.get("version") or 0),
        default=None,
    )
    latest_brief = max(
        brief_versions,
        key=lambda item: int(item.get("version") or 0),
        default=None,
    )
    return {
        "investigation_id": record.get("investigation_id"),
        "status": record.get("status"),
        "domain_revision": record.get("domain_revision"),
        "latest_cycle": _select_fields(latest_cycle, ("cycle_id", "ordinal")),
        "specialist_assignments": [
            _select_fields(
                item,
                (
                    "specialist_assignment_id",
                    "cycle_id",
                    "specialist_brief_id",
                    "state",
                    "revision",
                    "specialist_analysis_id",
                ),
            )
            for item in assignments
        ],
        "latest_hypothesis_versions": [
            _select_fields(
                item,
                (
                    "logical_hypothesis_id",
                    "hypothesis_version_id",
                    "cycle_id",
                    "version",
                    "status",
                    "evidence_snapshot_id",
                ),
            )
            for item in latest_hypotheses.values()
        ],
        "latest_evidence_snapshot": _select_fields(
            latest_evidence, ("evidence_snapshot_id", "version")
        ),
        "latest_brief_version": _select_fields(
            latest_brief,
            ("brief_version_id", "version", "evidence_snapshot_id"),
        ),
    }


def _select_fields(
    record: JsonObject | None, fields: tuple[str, ...]
) -> JsonObject | None:
    if not isinstance(record, dict):
        return None
    return {
        field: record.get(field)
        for field in fields
        if record.get(field) is not None
    }


def _emit_status(
    project_id: str,
    event: str,
    *,
    status: str,
    reason: str,
    root: str | Path | None,
    **identifiers: str,
) -> None:
    data = {"status": status, "reason": reason}
    data.update({key: value for key, value in identifiers.items() if value})
    portal_project_events.emit_project_event(project_id, event, data, root=root)
