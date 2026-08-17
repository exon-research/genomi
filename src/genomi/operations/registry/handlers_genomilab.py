"""Direct, in-process MCP handlers for host-owned GenomiLab work."""

from __future__ import annotations

from typing import Callable

from ...lab.models import JsonObject
from ...lab.scientific_executor_config import (
    ScientificExecutorConfigurationError,
)
from ...lab.service_errors import LabError
from .errors import OperationError


def current_agent_runtime():
    # Import lazily: the GenomiLab runtime imports the HTTP portal, whose
    # service calls the operation registry.  Tool-catalog initialization must
    # finish before that cycle is entered.
    from ...lab.agent_runtime import current_agent_runtime as get_runtime

    return get_runtime()


def _runtime_call(operation: Callable[[], JsonObject]) -> JsonObject:
    try:
        return operation()
    except LabError as exc:
        raise OperationError(exc.code, str(exc)) from exc
    except ScientificExecutorConfigurationError as exc:
        raise OperationError(exc.code, str(exc)) from exc
    except OperationError:
        raise
    except Exception as exc:
        raise OperationError("genomilab_unavailable", str(exc)) from exc


def _exact_fields(params: JsonObject, allowed: set[str]) -> None:
    unexpected = set(params) - allowed
    if unexpected:
        raise OperationError(
            "invalid_params",
            "unsupported GenomiLab parameters: " + ", ".join(sorted(unexpected)),
        )


def _required_text(params: JsonObject, field: str) -> str:
    value = params.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OperationError("invalid_params", f"{field} is required")
    return value.strip()


def _authorization_handoff(
    investigation_id: str, candidate: object
) -> JsonObject:
    if not isinstance(candidate, dict):
        raise OperationError(
            "genomilab_unavailable",
            "GenomiLab did not prepare an authorization candidate.",
        )
    return {
        "kind": "investigation_authorization",
        "investigation_id": investigation_id,
        "authorization_candidate": candidate,
    }


def _genomilab_open_workspace(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"open_portal"})
    open_portal = params.get("open_portal", True)
    if not isinstance(open_portal, bool):
        raise OperationError("invalid_params", "open_portal must be a boolean")
    return _runtime_call(
        lambda: current_agent_runtime().open_workspace(open_portal=open_portal)
    )


def _genomilab_create_investigation(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"question", "disease_scope"})
    question = _required_text(params, "question")
    payload: JsonObject = {"question": question}
    if params.get("disease_scope") not in (None, ""):
        payload["disease_scope"] = _required_text(params, "disease_scope")
    return _runtime_call(
        lambda: current_agent_runtime().service.create_agent_investigation(payload)
    )


def _genomilab_inspect_investigation(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id"})
    investigation_id = _required_text(params, "investigation_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.inspect_agent_investigation(
            investigation_id
        )
    )


def _genomilab_form_specialist_board(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id", "specialists"})
    investigation_id = _required_text(params, "investigation_id")
    specialists = params.get("specialists")
    if not isinstance(specialists, list) or not specialists or any(
        not isinstance(item, dict) for item in specialists
    ):
        raise OperationError(
            "invalid_params", "specialists must be a non-empty object array"
        )
    return _runtime_call(
        lambda: current_agent_runtime().service.form_agent_specialist_board(
            investigation_id,
            specialists=[dict(item) for item in specialists],
        )
    )


def _genomilab_report_specialist_progress(params: JsonObject) -> JsonObject:
    _exact_fields(
        params,
        {
            "investigation_id",
            "round_id",
            "specialist_id",
            "status",
            "current_work",
        },
    )
    investigation_id = _required_text(params, "investigation_id")
    round_id = _required_text(params, "round_id")
    specialist_id = _required_text(params, "specialist_id")
    status = _required_text(params, "status")
    current_work = _required_text(params, "current_work")
    return _runtime_call(
        lambda: current_agent_runtime().service.report_agent_specialist_progress(
            investigation_id,
            round_id=round_id,
            specialist_id=specialist_id,
            status=status,
            current_work=current_work,
        )
    )


def _genomilab_record_specialist_report(params: JsonObject) -> JsonObject:
    _exact_fields(
        params, {"investigation_id", "round_id", "specialist_id", "report"}
    )
    investigation_id = _required_text(params, "investigation_id")
    round_id = _required_text(params, "round_id")
    specialist_id = _required_text(params, "specialist_id")
    report = params.get("report")
    if not isinstance(report, dict):
        raise OperationError("invalid_params", "report must be an object")
    return _runtime_call(
        lambda: current_agent_runtime().service.record_agent_specialist_report(
            investigation_id,
            round_id=round_id,
            specialist_id=specialist_id,
            report=dict(report),
        )
    )


def _genomilab_prepare_authorization(params: JsonObject) -> JsonObject:
    _exact_fields(
        params, {"investigation_id", "observation_revision_ids", "purpose"}
    )
    investigation_id = _required_text(params, "investigation_id")
    revision_ids = params.get("observation_revision_ids")
    if revision_ids is not None and (
        not isinstance(revision_ids, list)
        or any(not isinstance(item, str) or not item.strip() for item in revision_ids)
    ):
        raise OperationError(
            "invalid_params", "observation_revision_ids must be a string array"
        )
    purpose = params.get("purpose")
    if purpose is not None and not isinstance(purpose, str):
        raise OperationError("invalid_params", "purpose must be a string")

    def prepare() -> JsonObject:
        runtime = current_agent_runtime()
        result = runtime.service.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=(
                [item.strip() for item in revision_ids]
                if isinstance(revision_ids, list)
                else None
            ),
            purpose=purpose.strip() if isinstance(purpose, str) else None,
        )
        return {
            **result,
            "portal": runtime.open_portal(
                authorization_handoff=_authorization_handoff(
                    investigation_id, result.get("candidate")
                )
            ),
        }

    return _runtime_call(prepare)


def _genomilab_record_patient_observations(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id", "observations"})
    investigation_id = _required_text(params, "investigation_id")
    observations = params.get("observations")
    if not isinstance(observations, list) or not observations or any(
        not isinstance(item, dict) for item in observations
    ):
        raise OperationError(
            "invalid_params", "observations must be a non-empty object array"
        )

    def record() -> JsonObject:
        runtime = current_agent_runtime()
        result = runtime.service.record_agent_patient_observations(
            investigation_id, [dict(item) for item in observations]
        )
        authorization = result.get("authorization")
        candidate = (
            authorization.get("candidate")
            if isinstance(authorization, dict)
            else None
        )
        return {
            **result,
            "portal": runtime.open_portal(
                authorization_handoff=_authorization_handoff(
                    investigation_id, candidate
                )
            ),
        }

    return _runtime_call(record)


def _genomilab_submit_plan(params: JsonObject) -> JsonObject:
    _exact_fields(
        params,
        {
            "investigation_id",
            "focus_question",
            "specialist_assignments",
            "requests",
        },
    )
    investigation_id = _required_text(params, "investigation_id")
    focus_question = _required_text(params, "focus_question")
    assignments = params.get("specialist_assignments")
    if not isinstance(assignments, list) or not assignments or any(
        not isinstance(item, dict) for item in assignments
    ):
        raise OperationError(
            "invalid_params",
            "specialist_assignments must be a non-empty object array",
        )
    requests = params.get("requests")
    if not isinstance(requests, list) or not requests or any(
        not isinstance(item, dict) for item in requests
    ):
        raise OperationError(
            "invalid_params", "requests must be a non-empty object array"
        )
    return _runtime_call(
        lambda: current_agent_runtime().service.submit_agent_plan(
            investigation_id,
            focus_question=focus_question,
            specialist_assignments=[dict(item) for item in assignments],
            requests=[dict(item) for item in requests],
        )
    )


def _genomilab_execute_request(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id", "request_id"})
    investigation_id = _required_text(params, "investigation_id")
    request_id = _required_text(params, "request_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.execute_agent_request(
            investigation_id, request_id
        )
    )


def _genomilab_check_request(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id", "request_id"})
    investigation_id = _required_text(params, "investigation_id")
    request_id = _required_text(params, "request_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.check_agent_request(
            investigation_id, request_id
        )
    )


def _genomilab_submit_brief(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id", "brief"})
    investigation_id = _required_text(params, "investigation_id")
    brief = params.get("brief")
    if not isinstance(brief, dict):
        raise OperationError("invalid_params", "brief must be an object")
    return _runtime_call(
        lambda: current_agent_runtime().service.submit_agent_brief(
            investigation_id, dict(brief)
        )
    )


def _genomilab_submit_research_artifact(params: JsonObject) -> JsonObject:
    _exact_fields(
        params,
        {
            "investigation_id",
            "round_id",
            "deduplication_key",
            "origin",
            "artifact",
        },
    )
    investigation_id = _required_text(params, "investigation_id")
    round_id = _required_text(params, "round_id")
    deduplication_key = _required_text(params, "deduplication_key")
    origin = _required_text(params, "origin")
    artifact = params.get("artifact")
    if not isinstance(artifact, dict):
        raise OperationError("invalid_params", "artifact must be an object")
    return _runtime_call(
        lambda: current_agent_runtime().service.submit_agent_research_artifact(
            investigation_id,
            round_id=round_id,
            deduplication_key=deduplication_key,
            origin=origin,
            artifact=dict(artifact),
        )
    )


def _genomilab_verify_sequence_substitution(params: JsonObject) -> JsonObject:
    fields = {
        "investigation_id",
        "round_id",
        "deduplication_key",
        "gene",
        "transcript_accession",
        "protein_accession",
        "coding_change",
        "protein_substitution",
        "public_reference_protein_sequence",
        "reference_source_label",
        "reference_source_version",
        "reference_source_record_id",
    }
    _exact_fields(params, fields)
    values = {field: _required_text(params, field) for field in fields}
    investigation_id = values.pop("investigation_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.verify_agent_sequence_substitution(
            investigation_id, **values
        )
    )


def _genomilab_run_esm_substitution_analysis(params: JsonObject) -> JsonObject:
    fields = {
        "investigation_id",
        "round_id",
        "deduplication_key",
        "sequence_verification_artifact_id",
        "public_reference_protein_sequence",
    }
    _exact_fields(params, fields)
    values = {field: _required_text(params, field) for field in fields}
    investigation_id = values.pop("investigation_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.run_agent_esm_substitution_analysis(
            investigation_id, **values
        )
    )


def _genomilab_run_proto_blinded_experiment_design(
    params: JsonObject,
) -> JsonObject:
    fields = {
        "investigation_id",
        "round_id",
        "deduplication_key",
        "sequence_verification_artifact_id",
        "objective",
        "required_arm_classes",
        "readouts",
    }
    _exact_fields(params, fields)
    investigation_id = _required_text(params, "investigation_id")
    required_arm_classes = params.get("required_arm_classes")
    readouts = params.get("readouts")
    if not isinstance(required_arm_classes, list) or not isinstance(readouts, list):
        raise OperationError(
            "invalid_params", "required_arm_classes and readouts must be arrays"
        )
    return _runtime_call(
        lambda: current_agent_runtime().service.run_agent_proto_blinded_experiment_design(
            investigation_id,
            round_id=_required_text(params, "round_id"),
            deduplication_key=_required_text(params, "deduplication_key"),
            sequence_verification_artifact_id=_required_text(
                params, "sequence_verification_artifact_id"
            ),
            objective=_required_text(params, "objective"),
            required_arm_classes=list(required_arm_classes),
            readouts=list(readouts),
        )
    )


def _genomilab_list_research_artifacts(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id"})
    investigation_id = _required_text(params, "investigation_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.list_agent_research_artifacts(
            investigation_id
        )
    )


def _genomilab_list_research_tools(params: JsonObject) -> JsonObject:
    _exact_fields(params, set())
    return _runtime_call(
        lambda: current_agent_runtime().service.list_agent_research_tools()
    )


def _genomilab_revoke_context(params: JsonObject) -> JsonObject:
    _exact_fields(params, {"investigation_id"})
    investigation_id = _required_text(params, "investigation_id")
    return _runtime_call(
        lambda: current_agent_runtime().service.revoke_agent_context(
            investigation_id
        )
    )


__all__ = [
    "_genomilab_check_request",
    "_genomilab_create_investigation",
    "_genomilab_execute_request",
    "_genomilab_form_specialist_board",
    "_genomilab_inspect_investigation",
    "_genomilab_list_research_artifacts",
    "_genomilab_list_research_tools",
    "_genomilab_open_workspace",
    "_genomilab_prepare_authorization",
    "_genomilab_record_patient_observations",
    "_genomilab_record_specialist_report",
    "_genomilab_report_specialist_progress",
    "_genomilab_revoke_context",
    "_genomilab_submit_brief",
    "_genomilab_submit_plan",
    "_genomilab_submit_research_artifact",
    "_genomilab_verify_sequence_substitution",
    "_genomilab_run_esm_substitution_analysis",
    "_genomilab_run_proto_blinded_experiment_design",
]
