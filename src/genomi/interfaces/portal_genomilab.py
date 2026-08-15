"""Project-scoped GenomiLab projections for the unified research portal.

GenomiLab remains the canonical owner of private profile and investigation data.
The portal persists only the identity binding needed to open the right board.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from ..lab.store import GenomiLabStore
from . import portal_project_events, portal_state, portal_store

JsonObject = dict[str, Any]
_BINDING_KEY = "genomilab_binding"
_SERVICE_LOCK = threading.Lock()
class _GenomiLabApplication(Protocol):
    def bootstrap_workspace(self) -> JsonObject: ...
    def molecular_profile(self) -> JsonObject: ...
    def integrations(self) -> JsonObject: ...
    def add_profile_observation(self, payload: JsonObject) -> JsonObject: ...
    def add_source_artifact(self, payload: JsonObject) -> JsonObject: ...
    def add_specimen(self, payload: JsonObject) -> JsonObject: ...
    def add_assay(self, payload: JsonObject) -> JsonObject: ...
    def connect_integration(self, provider: str, payload: JsonObject) -> JsonObject: ...
    def verify_integration(self, provider: str) -> JsonObject: ...
    def disconnect_integration(self, provider: str, *, confirmed: bool) -> JsonObject: ...
    def list_investigations(self) -> list[JsonObject]: ...
    def investigation(self, investigation_id: str) -> JsonObject: ...
    def create_investigation(self, payload: JsonObject) -> JsonObject: ...


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


def add_profile_observation(
    project_id: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    observation = (
        service or _application_service(project_id, root=root)
    ).add_profile_observation(payload)
    revision_id = str(observation.get("observation_revision_id") or "")
    _emit_status(
        project_id,
        "genomilab_profile_changed",
        status="updated",
        reason="observation_added",
        observation_revision_id=revision_id,
        root=root,
    )
    return {"status": "updated", "observation": observation}


def add_profile_source_artifact(
    project_id: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    artifact = (
        service or _application_service(project_id, root=root)
    ).add_source_artifact(payload)
    _emit_status(
        project_id,
        "genomilab_profile_changed",
        status="updated",
        reason="source_artifact_added",
        artifact_id=str(artifact.get("artifact_id") or ""),
        root=root,
    )
    return {"status": "updated", "source_artifact": artifact}


def add_profile_specimen(
    project_id: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    specimen = (
        service or _application_service(project_id, root=root)
    ).add_specimen(payload)
    _emit_status(
        project_id,
        "genomilab_profile_changed",
        status="updated",
        reason="specimen_added",
        specimen_id=str(specimen.get("specimen_id") or ""),
        root=root,
    )
    return {"status": "updated", "specimen": specimen}


def add_profile_assay(
    project_id: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    assay = (service or _application_service(project_id, root=root)).add_assay(
        payload
    )
    _emit_status(
        project_id,
        "genomilab_profile_changed",
        status="updated",
        reason="assay_added",
        assay_id=str(assay.get("assay_id") or ""),
        root=root,
    )
    return {"status": "updated", "assay": assay}


def change_integration(
    project_id: str,
    provider: str,
    action: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    """Apply one redacted, audited provider connection transition."""

    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    if action == "connect":
        integration = application.connect_integration(provider, payload)
    elif action == "verify":
        if payload:
            raise PortalGenomiLabError(
                "invalid_integration_request",
                "Connection checks do not accept request fields.",
            )
        integration = application.verify_integration(provider)
    elif action == "disconnect":
        if set(payload) != {"confirmed"} or payload.get("confirmed") is not True:
            raise PortalGenomiLabError(
                "invalid_integration_request",
                "Disconnect requires explicit confirmation.",
            )
        integration = application.disconnect_integration(provider, confirmed=True)
    else:
        raise PortalGenomiLabError(
            "invalid_integration_action", "Unsupported integration action."
        )
    _emit_status(
        project_id,
        "genomilab_integration_changed",
        status=str(integration.get("connection_state") or "updated"),
        reason=f"integration_{action}",
        provider=provider,
        root=root,
    )
    return {"status": "updated", "integration": integration}


def create_investigation(
    project_id: str,
    payload: JsonObject,
    *,
    service: _GenomiLabApplication | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    _require_project(project_id, root=root)
    application = service or _application_service(project_id, root=root)
    investigation = application.create_investigation(
        {key: payload[key] for key in ("question", "disease_scope") if key in payload}
    )
    binding = bind_investigation(
        project_id,
        investigation_id=str(investigation.get("investigation_id") or ""),
        frame_id=str(payload.get("frame_id") or ""),
        service=application,
        root=root,
    )
    return {
        "status": "created",
        "binding": binding,
        "investigation": _board_investigation(investigation),
    }


def bind_investigation(
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
    Provider connection operations are supplied by the host-neutral Lab backend;
    until that backend reports them, the landing page renders their honest
    unavailable state instead of falling back to a second credential boundary.
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

    def add_profile_observation(self, payload: JsonObject) -> JsonObject:
        with self._current_user() as user_id:
            return self.store.add_profile_observation(user_id, payload)

    def add_source_artifact(self, payload: JsonObject) -> JsonObject:
        with self._current_user() as user_id:
            return self.store.add_source_artifact(user_id, payload)

    def add_specimen(self, payload: JsonObject) -> JsonObject:
        with self._current_user() as user_id:
            return self.store.add_specimen(user_id, payload)

    def add_assay(self, payload: JsonObject) -> JsonObject:
        with self._current_user() as user_id:
            return self.store.add_assay(user_id, payload)

    def list_investigations(self) -> list[JsonObject]:
        with self._current_user() as user_id:
            records: list[JsonObject] = []
            for investigation in self.store.list_investigations(user_id):
                investigation_id = str(investigation.get("investigation_id") or "")
                if not investigation_id:
                    continue
                try:
                    view = self.store.read_orchestrator_investigation(
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
                if session == self.session_id or session.startswith(f"{self.session_id}:"):
                    records.append(view)
            return records

    def investigation(self, investigation_id: str) -> JsonObject:
        with self._current_user() as user_id:
            view = self.store.read_orchestrator_investigation(
                investigation_id, include_history=True
            )
            investigation = view.get("investigation")
            if not isinstance(investigation, dict) or str(
                investigation.get("user_id") or ""
            ) != user_id:
                raise PortalGenomiLabError(
                    "investigation_not_found",
                    "Investigation not found.",
                    http_status=404,
                )
            return view

    def create_investigation(self, payload: JsonObject) -> JsonObject:
        with self._current_user() as user_id:
            response = self.store.create_lab_investigation(
                user_id,
                workspace_session_id=self.session_id,
                question=str(payload.get("question") or "").strip(),
                disease_scope=str(payload.get("disease_scope") or "").strip()
                or None,
                public_only=False,
                approved_profile_context=None,
                command_id=f"portal-create-{uuid.uuid4().hex}",
            )
            return dict(response["investigation"])

    def integrations(self) -> JsonObject:
        return {
            "status": "ready",
            "integrations": [
                {
                    "provider": provider,
                    "connection_state": "backend_unavailable",
                    "credential_state": "not_configured",
                    "policy_state": "connection_backend_unavailable",
                    "investigation_operations": [],
                }
                for provider in ("paperclip", "biohub-esm", "proto")
            ],
        }

    def connect_integration(self, provider: str, payload: JsonObject) -> JsonObject:
        del provider, payload
        raise PortalGenomiLabError(
            "provider_connection_backend_unavailable",
            "Provider connections are not available in this build.",
            http_status=503,
        )

    def verify_integration(self, provider: str) -> JsonObject:
        return self.connect_integration(provider, {})

    def disconnect_integration(self, provider: str, *, confirmed: bool) -> JsonObject:
        del confirmed
        return self.connect_integration(provider, {})


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
                session_id=f"portal:{clean_project_id}",
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


def _board_investigation(investigation: JsonObject | None) -> JsonObject | None:
    if not isinstance(investigation, dict):
        return None
    result = _investigation_summary(investigation)
    record = investigation.get("investigation")
    record = record if isinstance(record, dict) else investigation
    hypotheses = investigation.get("current_hypotheses") or investigation.get(
        "hypothesis_versions"
    ) or []
    workstreams = investigation.get("panel_assignments") or investigation.get(
        "specialist_workstreams"
    ) or []
    patient_questions = investigation.get("patient_questions") or []
    next_steps = investigation.get("recommended_next_steps") or []
    brief_versions = investigation.get("brief_versions") or []
    current_brief = investigation.get("current_brief_version") or (
        brief_versions[-1] if brief_versions else None
    )
    evidence_snapshots = investigation.get("evidence_snapshots") or []
    cycles = investigation.get("cycles") or []
    research_artifacts = investigation.get("research_artifacts") or []
    result.update(
        {
            "private_context_status": investigation.get("private_context_status"),
            "cycles": cycles,
            "cycle_count": len(cycles),
            "evidence_snapshots": evidence_snapshots,
            "brief_versions": brief_versions,
            "research_artifacts": research_artifacts,
            "evidence_count": len(investigation.get("evidence_records") or []),
            "hypothesis_count": len(hypotheses),
            "gap_count": len(investigation.get("information_gaps") or []),
            "specialist_count": len(workstreams),
            "hypotheses": hypotheses,
            "specialist_workstreams": workstreams,
            "information_gaps": investigation.get("information_gaps") or [],
            "patient_questions": patient_questions,
            "recommended_next_steps": next_steps,
            "current_brief_version": (
                current_brief.get("version")
                if isinstance(current_brief, dict)
                else current_brief
            ),
            "current_brief": (
                (current_brief.get("brief") or {}).get("summary")
                or (current_brief.get("brief") or {}).get("title")
                or current_brief.get("summary")
                or current_brief.get("title")
                or "Evidence-linked doctor brief ready."
                if isinstance(current_brief, dict)
                else None
            ),
            "domain_revision": record.get("domain_revision"),
        }
    )
    return result


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
