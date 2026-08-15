"""Wire schemas and codecs for installed-harness artifacts.

This module is the single owner of artifact shape.  The Codex adapter handles
transport and delegates schema construction, decoding, and structural
validation here.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .brief_provenance import derive_brief_modality_badges
from .harness_transport import safe_json_value
from .harness_types import HarnessArtifactKind
from .hypothesis_contract import GAP_KINDS
from .narrative_contract import NarrativeStatementId, narrative_text, narrative_texts


def _object_schema(
    required: Sequence[str], properties: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": dict(properties),
    }


_PLAN_STEP_FIELDS = (
    "id",
    "title",
    "rationale",
    "capabilities",
    "proposed_agent_role",
    "requires_private_context",
    "requires_external_provider",
)
_PLAN_REQUEST_FIELDS = (
    "id",
    "step_id",
    "assigned_agent_role",
    "capability",
    "parameters",
)

PLAN_SCHEMA: dict[str, Any] = _object_schema(
    (
        "summary",
        "steps",
        "proposed_agent_roles",
        "capability_requests",
        "required_approvals",
    ),
    {
        "summary": {
            "type": "string",
            "enum": [narrative_text(NarrativeStatementId.PLAN_SUMMARY)],
            "description": (
                "Use the exact declared plan summary. Detailed reasoning belongs "
                "in typed steps and capability requests."
            ),
        },
        "steps": {
            "type": "array",
            "items": _object_schema(
                _PLAN_STEP_FIELDS,
                {
                    "id": {"type": "string"},
                    "title": {
                        "type": "string",
                        "enum": [
                            narrative_text(NarrativeStatementId.PLAN_STEP_TITLE)
                        ],
                    },
                    "rationale": {
                        "type": "string",
                        "enum": [
                            narrative_text(
                                NarrativeStatementId.PLAN_STEP_RATIONALE
                            )
                        ],
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "proposed_agent_role": {"type": "string"},
                    "requires_private_context": {"type": "boolean"},
                    "requires_external_provider": {"type": "boolean"},
                },
            ),
        },
        "proposed_agent_roles": {
            "type": "array",
            "items": _object_schema(
                ("role", "objective", "assigned_step_ids"),
                {
                    "role": {"type": "string"},
                    "objective": {
                        "type": "string",
                        "enum": [
                            narrative_text(
                                NarrativeStatementId.PLAN_ROLE_OBJECTIVE
                            )
                        ],
                    },
                    "assigned_step_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            ),
        },
        "capability_requests": {
            "type": "array",
            "items": _object_schema(
                _PLAN_REQUEST_FIELDS,
                {
                    "id": {"type": "string"},
                    "step_id": {"type": "string"},
                    "assigned_agent_role": {"type": "string"},
                    "capability": {"type": "string"},
                    "parameters": {
                        "type": "string",
                        "description": (
                            "JSON serialization of the exact capability parameter object."
                        ),
                    },
                },
            ),
        },
        "required_approvals": {"type": "array", "items": {"type": "string"}},
    },
)

EXECUTION_REPORT_SCHEMA: dict[str, Any] = _object_schema(
    ("summary", "request_results"),
    {
        "summary": {
            "type": "string",
            "enum": [narrative_text(NarrativeStatementId.EXECUTION_SUMMARY)],
        },
        "request_results": {
            "type": "array",
            "items": _object_schema(
                ("request_id", "capability", "status"),
                {
                    "request_id": {"type": "string"},
                    "capability": {"type": "string"},
                    "status": {"type": "string"},
                },
            ),
        },
    },
)

_CLAIM_ROLES = (
    "observation",
    "candidate_hypothesis",
    "counterevidence",
    "limitation",
)
_BRIEF_FIELDS = (
    "title",
    "summary",
    "clinical_stage",
    "claims",
    "hypothesis_ids",
    "gap_ids",
    "confirmation_needs",
    "professional_questions",
    "clinical_boundary",
    "change_summary",
)

BRIEF_SCHEMA: dict[str, Any] = _object_schema(
    _BRIEF_FIELDS,
    {
        "title": {
            "type": "string",
            "description": (
                "Use the declared identifier title when rsID and gene are present; "
                "otherwise use 'Proposed investigation brief'."
            ),
        },
        "summary": {"type": "string"},
        "clinical_stage": {
            "type": "string",
            "enum": ["research_observation", "candidate_hypothesis"],
        },
        "claims": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": _object_schema(
                (
                    "statement",
                    "claim_role",
                    "evidence_record_ids",
                    "profile_revision_ids",
                ),
                {
                    "statement": {
                        "type": "string",
                        "enum": [
                            text
                            for role in _CLAIM_ROLES
                            for text in narrative_texts(claim_role=role)
                        ],
                    },
                    "claim_role": {"type": "string", "enum": list(_CLAIM_ROLES)},
                    "evidence_record_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "profile_revision_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            ),
        },
        "hypothesis_ids": {"type": "array", "items": {"type": "string"}},
        "gap_ids": {"type": "array", "items": {"type": "string"}},
        "confirmation_needs": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": narrative_texts(kind="confirmation_need"),
            },
        },
        "professional_questions": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": narrative_texts(kind="professional_question"),
            },
        },
        "clinical_boundary": {
            "type": "string",
            "enum": [
                narrative_text(NarrativeStatementId.BRIEF_CLINICAL_BOUNDARY)
            ],
        },
        "change_summary": {
            "type": "string",
            "enum": [narrative_text(NarrativeStatementId.BRIEF_CHANGE_SUMMARY)],
        },
    },
)


def artifact_schema(
    artifact_kind: HarnessArtifactKind,
    approved_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fresh schema constrained to the approved context."""

    if artifact_kind == HarnessArtifactKind.PLAN:
        return copy.deepcopy(PLAN_SCHEMA)
    if artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
        return copy.deepcopy(EXECUTION_REPORT_SCHEMA)
    schema = copy.deepcopy(BRIEF_SCHEMA)
    context = approved_context if isinstance(approved_context, Mapping) else {}
    hypotheses = context.get("hypotheses")
    hypotheses = hypotheses if _is_sequence(hypotheses) else ()
    typed_ids: dict[str, list[str]] = {"hypothesis_ids": [], "gap_ids": []}
    allowed_claim_roles = {"observation", "limitation"}
    for record in hypotheses:
        if not isinstance(record, Mapping):
            continue
        hypothesis_id = record.get("hypothesis_id")
        kind = record.get("kind")
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            continue
        typed_ids["gap_ids" if kind in GAP_KINDS else "hypothesis_ids"].append(
            hypothesis_id
        )
        if kind == "candidate_mechanism":
            allowed_claim_roles.add("candidate_hypothesis")
        elif kind == "counterevidence":
            allowed_claim_roles.add("counterevidence")
    for field, identifiers in typed_ids.items():
        _constrain_reference_array(schema["properties"][field], identifiers)
        count = len(set(identifiers))
        schema["properties"][field]["minItems"] = count
        schema["properties"][field]["maxItems"] = count
    has_candidate = "candidate_hypothesis" in allowed_claim_roles
    schema["properties"]["clinical_stage"]["enum"] = [
        "candidate_hypothesis" if has_candidate else "research_observation"
    ]
    schema["properties"]["summary"]["enum"] = [
        narrative_text(
            NarrativeStatementId.BRIEF_SUMMARY_CANDIDATE
            if has_candidate
            else NarrativeStatementId.BRIEF_SUMMARY_OBSERVATION
        )
    ]
    if typed_ids["gap_ids"]:
        schema["properties"]["confirmation_needs"]["minItems"] = 1
        schema["properties"]["confirmation_needs"]["maxItems"] = 1
    evidence_records = context.get("evidence_records")
    evidence_ids = [
        str(record["evidence_record_id"])
        for record in evidence_records or ()
        if isinstance(record, Mapping)
        and isinstance(record.get("evidence_record_id"), str)
        and record["evidence_record_id"]
    ]
    profile = context.get("molecular_profile")
    observations = profile.get("observations") if isinstance(profile, Mapping) else ()
    profile_ids = [
        str(record["observation_revision_id"])
        for record in observations or ()
        if isinstance(record, Mapping)
        and isinstance(record.get("observation_revision_id"), str)
        and record["observation_revision_id"]
    ]
    claim_properties = schema["properties"]["claims"]["items"]["properties"]
    _constrain_reference_array(claim_properties["evidence_record_ids"], evidence_ids)
    _constrain_reference_array(claim_properties["profile_revision_ids"], profile_ids)
    claim_properties["claim_role"]["enum"] = [
        role for role in _CLAIM_ROLES if role in allowed_claim_roles
    ]
    claim_properties["statement"]["enum"] = [
        text
        for role in claim_properties["claim_role"]["enum"]
        for text in narrative_texts(claim_role=role)
    ]
    return schema


def decode_wire_artifact(
    artifact_kind: HarnessArtifactKind,
    artifact: dict[str, Any],
    *,
    approved_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize a strict wire artifact into its canonical domain shape."""

    if artifact_kind == HarnessArtifactKind.BRIEF_DRAFT:
        claims = artifact.get("claims")
        if not isinstance(claims, list) or not all(
            isinstance(claim, Mapping) for claim in claims
        ):
            raise ValueError("brief claims must be an array of objects")
        context = approved_context if isinstance(approved_context, Mapping) else {}
        evidence_records = context.get("evidence_records")
        profile = context.get("molecular_profile")
        observations = profile.get("observations") if isinstance(profile, Mapping) else ()
        return {
            **artifact,
            "modality_badges": derive_brief_modality_badges(
                claims,
                evidence_records=evidence_records if _is_sequence(evidence_records) else (),
                profile_records=observations if _is_sequence(observations) else (),
            ),
        }
    if artifact_kind != HarnessArtifactKind.PLAN:
        return artifact
    requests = artifact.get("capability_requests")
    if not isinstance(requests, list):
        return artifact
    decoded = dict(artifact)
    decoded_requests: list[Any] = []
    for request in requests:
        if not isinstance(request, dict):
            decoded_requests.append(request)
            continue
        decoded_request = dict(request)
        parameters = decoded_request.get("parameters")
        if isinstance(parameters, str):
            parsed = safe_json_value(json.loads(parameters))
            if not isinstance(parsed, dict):
                raise ValueError(
                    "plan capability parameters JSON must decode to an object"
                )
            decoded_request["parameters"] = parsed
        decoded_requests.append(decoded_request)
    decoded["capability_requests"] = decoded_requests
    return decoded


def validate_artifact(
    artifact_kind: HarnessArtifactKind,
    artifact: Mapping[str, Any],
    approved_context: Mapping[str, Any] | None = None,
) -> None:
    """Validate decoded artifact structure against one generated contract."""

    schema = artifact_schema(artifact_kind, approved_context)
    required = set(schema["required"])
    if artifact_kind == HarnessArtifactKind.BRIEF_DRAFT:
        required.add("modality_badges")
    if set(artifact) != required:
        raise ValueError("structured artifact fields do not match the requested schema")
    if artifact_kind == HarnessArtifactKind.PLAN:
        _validate_plan(artifact)
    elif artifact_kind == HarnessArtifactKind.EXECUTION_REPORT:
        _validate_execution_report(artifact)
    else:
        _validate_brief(artifact, schema)


def _validate_plan(artifact: Mapping[str, Any]) -> None:
    if not isinstance(artifact["summary"], str):
        raise ValueError("plan summary must be a string")
    if not _is_string_array(artifact["required_approvals"]):
        raise ValueError("plan required_approvals must be an array of strings")
    roles = artifact["proposed_agent_roles"]
    if not isinstance(roles, list):
        raise ValueError("plan proposed_agent_roles must be an array")
    known_roles: set[str] = set()
    for role in roles:
        if not isinstance(role, dict) or set(role) != {
            "role", "objective", "assigned_step_ids"
        }:
            raise ValueError("proposed agent role fields do not match the requested schema")
        if not isinstance(role["role"], str) or not isinstance(role["objective"], str):
            raise ValueError("proposed agent role and objective must be strings")
        if not _is_string_array(role["assigned_step_ids"]):
            raise ValueError("assigned_step_ids must be an array of strings")
        known_roles.add(role["role"])
    steps = artifact["steps"]
    if not isinstance(steps, list):
        raise ValueError("plan steps must be an array")
    step_by_id: dict[str, Mapping[str, Any]] = {}
    for step in steps:
        if not isinstance(step, dict) or set(step) != set(_PLAN_STEP_FIELDS):
            raise ValueError("plan step fields do not match the requested schema")
        if not all(
            isinstance(step[field], str)
            for field in ("id", "title", "rationale", "proposed_agent_role")
        ):
            raise ValueError("plan step identity, title, and rationale must be strings")
        if step["proposed_agent_role"] not in known_roles:
            raise ValueError("plan step references an undeclared proposed agent role")
        if not _is_string_array(step["capabilities"]):
            raise ValueError("plan step capabilities must be an array of strings")
        if not all(
            isinstance(step[field], bool)
            for field in ("requires_private_context", "requires_external_provider")
        ):
            raise ValueError("plan step policy flags must be booleans")
        step_by_id[step["id"]] = step
    requests = artifact["capability_requests"]
    if not isinstance(requests, list):
        raise ValueError("plan capability_requests must be an array")
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, dict) or set(request) != set(_PLAN_REQUEST_FIELDS):
            raise ValueError("capability request fields do not match the requested schema")
        if not all(
            isinstance(request[field], str)
            for field in ("id", "step_id", "assigned_agent_role", "capability")
        ) or not isinstance(request["parameters"], dict):
            raise ValueError("capability request fields have invalid types")
        if request["id"] in seen:
            raise ValueError("capability request identifiers must be unique")
        seen.add(request["id"])
        step = step_by_id.get(request["step_id"])
        if (
            step is None
            or request["capability"] not in step["capabilities"]
            or request["assigned_agent_role"] != step["proposed_agent_role"]
        ):
            raise ValueError("capability request must match its declared step and agent role")


def _validate_execution_report(artifact: Mapping[str, Any]) -> None:
    if not isinstance(artifact["summary"], str):
        raise ValueError("execution report summary must be a string")
    results = artifact["request_results"]
    if not isinstance(results, list):
        raise ValueError("execution report request_results must be an array")
    seen: set[str] = set()
    expected = {"request_id", "capability", "status"}
    for result in results:
        if not isinstance(result, dict) or set(result) != expected:
            raise ValueError("execution report entries must use the exact schema")
        if not all(
            isinstance(result[field], str) and bool(result[field].strip())
            for field in expected
        ):
            raise ValueError("execution report fields must be non-empty strings")
        if result["request_id"] in seen:
            raise ValueError("execution report request identifiers must be unique")
        seen.add(result["request_id"])


def _validate_brief(artifact: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    if not all(
        isinstance(artifact[field], str)
        for field in ("title", "summary", "clinical_boundary", "change_summary")
    ):
        raise ValueError("brief narrative fields must be strings")
    if artifact["clinical_stage"] not in schema["properties"]["clinical_stage"]["enum"]:
        raise ValueError("brief clinical_stage is not in the declared vocabulary")
    for field in (
        "modality_badges", "hypothesis_ids", "gap_ids",
        "confirmation_needs", "professional_questions",
    ):
        if not _is_string_array(artifact[field]):
            raise ValueError("brief reference sections must be arrays of strings")
    for field in ("hypothesis_ids", "gap_ids"):
        _validate_reference_array(artifact[field], schema["properties"][field], field)
    if len(artifact["modality_badges"]) != len(set(artifact["modality_badges"])):
        raise ValueError("brief modality_badges must be unique")
    claims = artifact["claims"]
    if not isinstance(claims, list) or not claims:
        raise ValueError("brief claims must be a non-empty array")
    claim_schema = schema["properties"]["claims"]["items"]["properties"]
    fingerprints: set[str] = set()
    for claim in claims:
        expected = {"statement", "claim_role", "evidence_record_ids", "profile_revision_ids"}
        if not isinstance(claim, dict) or set(claim) != expected:
            raise ValueError("brief claim fields do not match the requested schema")
        if not isinstance(claim["statement"], str):
            raise ValueError("brief claim statement must be a string")
        if claim["claim_role"] not in claim_schema["claim_role"]["enum"]:
            raise ValueError("brief claim_role is not in the declared vocabulary")
        for field in ("evidence_record_ids", "profile_revision_ids"):
            if not _is_string_array(claim[field]):
                raise ValueError("brief claim anchors must be arrays of strings")
            _validate_reference_array(claim[field], claim_schema[field], f"claim {field}")
        if not claim["evidence_record_ids"] and not claim["profile_revision_ids"]:
            raise ValueError("brief claim must cite evidence or profile observations")
        fingerprint = json.dumps(claim, sort_keys=True, separators=(",", ":"))
        if fingerprint in fingerprints:
            raise ValueError("brief claims must be unique")
        fingerprints.add(fingerprint)


def _validate_reference_array(
    values: list[str], schema: Mapping[str, Any], field: str
) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"brief {field} identifiers must be unique")
    maximum = schema.get("maxItems")
    if isinstance(maximum, int) and len(values) > maximum:
        raise ValueError(f"brief {field} must be empty in the approved context")
    items = schema.get("items")
    allowed = items.get("enum") if isinstance(items, Mapping) else None
    if isinstance(allowed, list) and any(value not in allowed for value in values):
        boundary = (
            "approved context" if field.startswith("claim ") else "approved typed set"
        )
        raise ValueError(
            f"brief {field} contains an identifier outside the {boundary}"
        )


def _constrain_reference_array(schema: dict[str, Any], identifiers: list[str]) -> None:
    if identifiers:
        schema["items"]["enum"] = sorted(set(identifiers))
    else:
        schema["maxItems"] = 0


def _is_string_array(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple))


__all__ = [
    "BRIEF_SCHEMA",
    "EXECUTION_REPORT_SCHEMA",
    "PLAN_SCHEMA",
    "artifact_schema",
    "decode_wire_artifact",
    "validate_artifact",
]
