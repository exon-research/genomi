"""The single canonical contract for tool answer-readiness.

Every evidence-producing Genomi operation, and every operation result that
reports a blocked/error/non-success state, reports answer-readiness, scope,
and negative-inference rules through `evidence_envelope` and nowhere else.
Tools do not invent parallel policy surfaces — neither prose paragraphs
nor parallel typed structures. If a new policy facet is needed, extend
the envelope; do not start a second contract.

The envelope encodes:

  - what was asked (`query_scope`)
  - whether Active Genome Index was involved (`personal_context`)
  - which libraries and materialization artifacts were consulted (`coverage`)
  - the typed evidence state (`finding_state`)
  - the typed answer readiness (`answer_readiness`)
  - whether negative inference is permitted, and what it would require
  - what the agent should do next (`next_actions`)
  - self-explanatory guidance codes (`guidance`)

Case-specific facts — which library is missing, which gene was checked,
which input is absent — live in those adjacent factual fields, not in the
guidance codes.

The point of typing these states is to make it structurally impossible for
an operation that found zero ClinVar candidates to imply "no genetic disease
risk." `finding_state="not_observed_in_consulted_scope"` plus
`answer_readiness="scoped_answer_only"` is the strongest claim such a
result can make, and `negative_inference.allowed=False` makes that explicit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

ENVELOPE_SCHEMA_VERSION = "genomi-evidence-envelope-v1"


# --- typed states ----------------------------------------------------------

EVIDENCE_PRESENT = "evidence_present"
NOT_OBSERVED_IN_CONSULTED_SCOPE = "not_observed_in_consulted_scope"
NOT_ASSESSED = "not_assessed"
BLOCKED_MISSING_LIBRARY = "blocked_missing_library"
MATERIALIZATION_INCOMPLETE = "materialization_incomplete"
TRUE_NEGATIVE_SUPPORTED = "true_negative_supported"

FINDING_STATES = (
    EVIDENCE_PRESENT,
    NOT_OBSERVED_IN_CONSULTED_SCOPE,
    NOT_ASSESSED,
    BLOCKED_MISSING_LIBRARY,
    MATERIALIZATION_INCOMPLETE,
    TRUE_NEGATIVE_SUPPORTED,
)

ANSWER_SUPPORTED = "answer_supported"
SCOPED_ANSWER_ONLY = "scoped_answer_only"
CANNOT_ANSWER_YET = "cannot_answer_yet"
NEEDS_USER_INSTALL = "needs_user_install"
NEEDS_MATERIALIZATION = "needs_materialization"
NEEDS_CLINICAL_CONFIRMATION = "needs_clinical_confirmation"

ANSWER_READINESS_STATES = (
    ANSWER_SUPPORTED,
    SCOPED_ANSWER_ONLY,
    CANNOT_ANSWER_YET,
    NEEDS_USER_INSTALL,
    NEEDS_MATERIALIZATION,
    NEEDS_CLINICAL_CONFIRMATION,
)

# Negative-inference requirement tokens. A claim of `true_negative_supported`
# must list which of these were actually satisfied.
REQ_CALLABILITY = "callability"
REQ_LIBRARY_COVERAGE = "library_coverage"
REQ_GENOTYPE_SUPPORT = "genotype_support"
REQ_CLINICAL_CONFIRMATION = "clinical_confirmation"
REQ_SCOPE_ALIGNMENT = "scope_alignment"

NEGATIVE_INFERENCE_REQUIREMENTS = (
    REQ_CALLABILITY,
    REQ_LIBRARY_COVERAGE,
    REQ_GENOTYPE_SUPPORT,
    REQ_CLINICAL_CONFIRMATION,
    REQ_SCOPE_ALIGNMENT,
)


# --- nested dataclasses ----------------------------------------------------

@dataclass(frozen=True)
class LibraryUse:
    """Records how one library figured into this operation.

    `state` is one of: installed, missing, not_materialized, materializing,
    complete, stale, failed.
    """

    library: str
    state: str
    title: str | None = None
    install_command: str | None = None
    helps: str | None = None
    materialization_id: str | None = None
    materialization_progress: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"library": self.library, "state": self.state}
        if self.title:
            payload["title"] = self.title
        if self.install_command:
            payload["install_command"] = self.install_command
        if self.helps:
            payload["helps"] = self.helps
        if self.materialization_id:
            payload["materialization_id"] = self.materialization_id
        if self.materialization_progress:
            payload["materialization_progress"] = self.materialization_progress
        if self.error:
            payload["error"] = self.error
        return payload


LIBRARY_STATES = (
    "installed",
    "missing",
    "not_materialized",
    "materializing",
    "complete",
    "stale",
    "failed",
)


# --- envelope --------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceEnvelope:
    schema: str
    operation: str
    query_scope: dict[str, Any]
    personal_context: dict[str, Any]
    coverage: dict[str, Any]
    observations: dict[str, Any]
    finding_state: str
    answer_readiness: str
    negative_inference: dict[str, Any]
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # Reading order: identity → verdict → guidance → context → details.
        # Headline lets a one-glance preview convey the verdict.
        return {
            "schema": self.schema,
            "operation": self.operation,
            "headline": f"{self.operation}: {self.finding_state} · {self.answer_readiness}",
            "finding_state": self.finding_state,
            "answer_readiness": self.answer_readiness,
            "guidance": list(self.guidance),
            "negative_inference": self.negative_inference,
            "next_actions": list(self.next_actions),
            "personal_context": self.personal_context,
            "coverage": self.coverage,
            "observations": self.observations,
            "query_scope": self.query_scope,
            "notes": list(self.notes),
        }


# --- construction helpers --------------------------------------------------

def _personal_context(
    *,
    uses_personal_dna: bool = False,
    source: str | None = None,
    sample_slug: str | None = None,
    approval_recorded: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"uses_personal_dna": bool(uses_personal_dna)}
    if source is not None:
        payload["source"] = source
    if sample_slug is not None:
        payload["sample_slug"] = sample_slug
    if approval_recorded is not None:
        payload["approval_recorded"] = bool(approval_recorded)
    return payload


def _coverage(
    *,
    libraries: Iterable[LibraryUse | dict[str, Any]] | None = None,
    consulted_sources: Iterable[str] | None = None,
    unavailable_sources: Iterable[str] | None = None,
    materialization: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lib_payload = []
    for entry in libraries or ():
        if isinstance(entry, LibraryUse):
            lib_payload.append(entry.to_dict())
        elif isinstance(entry, dict):
            lib_payload.append(dict(entry))
    return {
        "libraries": lib_payload,
        "consulted_sources": list(consulted_sources or ()),
        "unavailable_sources": list(unavailable_sources or ()),
        "materialization": [dict(item) for item in (materialization or ())],
    }


def _negative_inference(
    *,
    allowed: bool,
    requires: Iterable[str] = (),
    satisfied: Iterable[str] = (),
    reason: str | None = None,
) -> dict[str, Any]:
    requires_list = [item for item in requires if item in NEGATIVE_INFERENCE_REQUIREMENTS]
    satisfied_list = [item for item in satisfied if item in NEGATIVE_INFERENCE_REQUIREMENTS]
    payload: dict[str, Any] = {
        "allowed": bool(allowed),
        "requires": requires_list,
        "satisfied": satisfied_list,
    }
    if reason:
        payload["reason"] = reason
    return payload


def envelope(
    *,
    operation: str,
    finding_state: str,
    answer_readiness: str,
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    negative_inference: dict[str, Any] | None = None,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Construct and validate a generic envelope. Most callers should use one
    of the typed constructors below instead.
    """

    env = EvidenceEnvelope(
        schema=ENVELOPE_SCHEMA_VERSION,
        operation=operation,
        query_scope=dict(query_scope or {}),
        personal_context=dict(personal_context or _personal_context()),
        coverage=dict(coverage or _coverage()),
        observations=dict(observations or {}),
        finding_state=finding_state,
        answer_readiness=answer_readiness,
        negative_inference=dict(negative_inference or _negative_inference(allowed=False, reason="default")),
        next_actions=list(next_actions or ()),
        notes=list(notes or ()),
        guidance=list(guidance or ()),
    )
    validate(env)
    payload = env.to_dict()
    if not payload["guidance"]:
        payload["guidance"] = render_guidance(payload)
    return payload


# --- typed constructors ----------------------------------------------------

def evidence_present(
    *,
    operation: str,
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    answer_readiness: str = ANSWER_SUPPORTED,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """At least one decision-grade observation is present in the consulted scope."""

    return envelope(
        operation=operation,
        finding_state=EVIDENCE_PRESENT,
        answer_readiness=answer_readiness,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations,
        negative_inference=_negative_inference(
            allowed=False,
            reason="evidence_present — positive findings present; negative inference not applicable",
        ),
        next_actions=next_actions,
        notes=notes,
        guidance=guidance,
    )


def empty_consulted_scope(
    *,
    operation: str,
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    requires_for_true_negative: Iterable[str] = (REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT, REQ_CLINICAL_CONFIRMATION),
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The consulted scope returned no observations, but the absence is NOT a
    clinical-style true negative. Negative inference is explicitly disallowed.
    """

    return envelope(
        operation=operation,
        finding_state=NOT_OBSERVED_IN_CONSULTED_SCOPE,
        answer_readiness=SCOPED_ANSWER_ONLY,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations or {"observation_count": 0},
        negative_inference=_negative_inference(
            allowed=False,
            requires=requires_for_true_negative,
            reason=(
                "Zero observations within the consulted source(s) is not equivalent to "
                "a clinical true negative. Reporting 'no risk' or 'no disease' from this "
                "result is unsupported."
            ),
        ),
        next_actions=next_actions,
        notes=notes,
        guidance=guidance,
    )


def missing_library(
    *,
    operation: str,
    library: str,
    library_status_payload: dict[str, Any],
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    intent: str | None = None,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """A library required to answer this question is not installed. Treat as
    a setup gap, not as negative evidence.
    """

    install_command = library_status_payload.get("install_command")
    helps = library_status_payload.get("helps")
    coverage = _coverage(
        libraries=[
            LibraryUse(
                library=library,
                state="missing",
                title=library_status_payload.get("title"),
                install_command=install_command,
                helps=helps,
            )
        ]
    )
    actions = list(next_actions or [])
    actions.append(
        {
            "action": "install_library",
            "library": library,
            "install_command": install_command,
            "why": helps,
            "intent": intent,
        }
    )
    return envelope(
        operation=operation,
        finding_state=BLOCKED_MISSING_LIBRARY,
        answer_readiness=NEEDS_USER_INSTALL,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations={"observation_count": 0, "blocked_by": library},
        negative_inference=_negative_inference(
            allowed=False,
            requires=[REQ_LIBRARY_COVERAGE],
            reason=(
                f"Library {library!r} is not installed; missing-library state cannot be "
                "interpreted as negative evidence."
            ),
        ),
        next_actions=actions,
        notes=notes,
        guidance=guidance,
    )


def materialization_pending(
    *,
    operation: str,
    library: str,
    materialization: dict[str, Any],
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Library is installed but the on-disk artifacts for the active genome
    index are not yet complete. A background job has been started or resumed.
    """

    progress = {
        "status": materialization.get("status"),
        "started_at": materialization.get("started_at"),
        "completed_at": materialization.get("completed_at"),
        "agi_id": materialization.get("agi_id"),
        "library_version": materialization.get("library_version"),
        "inputs_hash": materialization.get("inputs_hash"),
        "job_id": materialization.get("job_id"),
    }
    coverage = _coverage(
        libraries=[
            LibraryUse(
                library=library,
                state="materializing" if materialization.get("status") in {"queued", "running", "materializing"} else "not_materialized",
                materialization_id=materialization.get("materialization_id") or materialization.get("agi_id"),
                materialization_progress={k: v for k, v in progress.items() if v is not None},
            )
        ],
        materialization=[materialization],
    )
    actions = list(next_actions or [])
    actions.append(
        {
            "action": "wait_for_materialization",
            "library": library,
            "poll_with": "genomi.check_background_job",
            "job_id": materialization.get("job_id"),
        }
    )
    return envelope(
        operation=operation,
        finding_state=MATERIALIZATION_INCOMPLETE,
        answer_readiness=NEEDS_MATERIALIZATION,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations={"observation_count": 0, "pending_library": library},
        negative_inference=_negative_inference(
            allowed=False,
            requires=[REQ_LIBRARY_COVERAGE],
            reason=(
                f"Materialization for {library!r} is incomplete; partial state cannot be "
                "interpreted as negative evidence."
            ),
        ),
        next_actions=actions,
        notes=notes,
        guidance=guidance,
    )


def not_assessed(
    *,
    operation: str,
    reason: str,
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The operation could not assess the question (missing inputs, scope
    mismatch, ambiguous query) — distinct from "consulted and found nothing".
    """

    return envelope(
        operation=operation,
        finding_state=NOT_ASSESSED,
        answer_readiness=CANNOT_ANSWER_YET,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations or {"observation_count": 0},
        negative_inference=_negative_inference(
            allowed=False,
            requires=[REQ_SCOPE_ALIGNMENT],
            reason=f"Not assessed: {reason}",
        ),
        next_actions=next_actions,
        notes=[reason, *list(notes or [])],
        guidance=guidance,
    )


def true_negative_supported(
    *,
    operation: str,
    satisfied_requirements: Iterable[str],
    query_scope: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    observations: dict[str, Any] | None = None,
    answer_readiness: str = SCOPED_ANSWER_ONLY,
    next_actions: Iterable[dict[str, Any]] | None = None,
    notes: Iterable[str] | None = None,
    guidance: Iterable[str] | None = None,
) -> dict[str, Any]:
    """A clinical-style true negative is only allowed when callability,
    library coverage, genotype support, scope alignment, and (typically)
    clinical confirmation are all satisfied. Validator enforces this.
    """

    required = (REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT, REQ_SCOPE_ALIGNMENT)
    satisfied = list(satisfied_requirements)
    return envelope(
        operation=operation,
        finding_state=TRUE_NEGATIVE_SUPPORTED,
        answer_readiness=answer_readiness,
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations or {"observation_count": 0},
        negative_inference=_negative_inference(
            allowed=True,
            requires=required,
            satisfied=satisfied,
            reason="True-negative claim is supported by satisfied requirements.",
        ),
        next_actions=next_actions,
        notes=notes,
        guidance=guidance,
    )


# --- validation ------------------------------------------------------------

class EnvelopeValidationError(ValueError):
    pass


def validate(env: EvidenceEnvelope | dict[str, Any]) -> None:
    payload = env.to_dict() if isinstance(env, EvidenceEnvelope) else env
    finding = payload.get("finding_state")
    readiness = payload.get("answer_readiness")
    if finding not in FINDING_STATES:
        raise EnvelopeValidationError(f"unknown finding_state: {finding!r}")
    if readiness not in ANSWER_READINESS_STATES:
        raise EnvelopeValidationError(f"unknown answer_readiness: {readiness!r}")
    ni = payload.get("negative_inference") or {}
    if not isinstance(ni, dict) or "allowed" not in ni:
        raise EnvelopeValidationError("negative_inference must include 'allowed'")
    guidance = payload.get("guidance") or []
    for entry in guidance:
        if not isinstance(entry, str) or not entry:
            raise EnvelopeValidationError("guidance entries must be non-empty strings")
        if any(char.isspace() for char in entry):
            raise EnvelopeValidationError(f"guidance entries must be typed codes, got: {entry!r}")

    # cross-state invariants
    if finding == EVIDENCE_PRESENT and readiness in {NEEDS_USER_INSTALL, NEEDS_MATERIALIZATION, CANNOT_ANSWER_YET}:
        raise EnvelopeValidationError(
            f"evidence_present is incompatible with answer_readiness={readiness}"
        )
    if finding == BLOCKED_MISSING_LIBRARY and readiness != NEEDS_USER_INSTALL:
        raise EnvelopeValidationError(
            "blocked_missing_library requires answer_readiness=needs_user_install"
        )
    if finding == MATERIALIZATION_INCOMPLETE and readiness != NEEDS_MATERIALIZATION:
        raise EnvelopeValidationError(
            "materialization_incomplete requires answer_readiness=needs_materialization"
        )
    if finding == NOT_OBSERVED_IN_CONSULTED_SCOPE and ni.get("allowed"):
        raise EnvelopeValidationError(
            "not_observed_in_consulted_scope must not allow negative inference"
        )
    if finding == TRUE_NEGATIVE_SUPPORTED:
        if not ni.get("allowed"):
            raise EnvelopeValidationError("true_negative_supported must allow negative inference")
        required = set(ni.get("requires") or [])
        satisfied = set(ni.get("satisfied") or [])
        missing = required - satisfied
        if missing:
            raise EnvelopeValidationError(
                f"true_negative_supported missing satisfied requirements: {sorted(missing)}"
            )
        # callability + library_coverage + genotype_support are mandatory baseline
        baseline = {REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT}
        if not baseline.issubset(satisfied):
            raise EnvelopeValidationError(
                "true_negative_supported requires callability, library_coverage, and "
                "genotype_support to be satisfied"
            )


# --- guidance renderer -----------------------------------------------------

_GUIDANCE_TEMPLATES = {
    (EVIDENCE_PRESENT, ANSWER_SUPPORTED): "evidence_present:decision_grade_within_consulted_scope",
    (EVIDENCE_PRESENT, SCOPED_ANSWER_ONLY): "evidence_present:answer_only_within_consulted_scope",
    (EVIDENCE_PRESENT, NEEDS_CLINICAL_CONFIRMATION): "evidence_present:requires_clinical_confirmation",
    (NOT_OBSERVED_IN_CONSULTED_SCOPE, SCOPED_ANSWER_ONLY): "not_observed_in_consulted_scope:do_not_imply_clinical_negative",
    (NOT_ASSESSED, CANNOT_ANSWER_YET): "not_assessed:request_missing_inputs_or_use_different_tool",
    (BLOCKED_MISSING_LIBRARY, NEEDS_USER_INSTALL): "blocked_missing_library:ask_user_to_install",
    (MATERIALIZATION_INCOMPLETE, NEEDS_MATERIALIZATION): "materialization_incomplete:wait_or_poll_background_job",
    (TRUE_NEGATIVE_SUPPORTED, SCOPED_ANSWER_ONLY): "true_negative_supported:state_scope_explicitly",
    (TRUE_NEGATIVE_SUPPORTED, NEEDS_CLINICAL_CONFIRMATION): "true_negative_supported:requires_clinical_confirmation",
}


def render_guidance(envelope_payload: dict[str, Any]) -> list[str]:
    """Return a tiny list of self-explanatory guidance codes (zero prose).

    Each code is shaped as `<typed_state>:<imperative_directive>` using full
    English morphemes — readable without a legend. Agents act on the code
    directly; case-specific facts live in adjacent envelope fields
    (`coverage`, `observations`, `next_actions`).
    """

    finding = envelope_payload.get("finding_state")
    readiness = envelope_payload.get("answer_readiness")
    codes: list[str] = []
    code = _GUIDANCE_TEMPLATES.get((finding, readiness))
    if code:
        codes.append(code)
    else:
        codes.append(f"{finding}:{readiness}")
    ni = envelope_payload.get("negative_inference") or {}
    if not ni.get("allowed"):
        codes.append("negative_inference_disallowed:do_not_state_clinical_negative")
    return codes


# --- backward-compat helper ------------------------------------------------

def attach_envelope(payload: dict[str, Any], envelope_payload: dict[str, Any]) -> dict[str, Any]:
    """Attach `evidence_envelope` to a tool result."""
    payload["evidence_envelope"] = envelope_payload
    return payload


def _as_count(value: Any) -> int:
    """Coerce a result/observation value to a non-negative evidence count.

    Returns 0 for None, booleans, and anything not parseable as an int so the
    envelope's count heuristics never treat a flag or label as evidence.
    """
    if value is None or isinstance(value, bool):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


def derive_default_envelope(operation: str, result: dict[str, Any]) -> dict[str, Any]:
    """Best-effort envelope derived from common result fields.

    Used as a contract floor by the operations dispatcher: any evidence-producing
    operation whose handler did not emit an envelope gets one here. Per-tool
    handlers that need richer semantics should still emit their own envelope.

    Heuristics (low → high specificity):
      - status == "requires_library_install" → blocked_missing_library / needs_user_install
      - status == "in_progress" → materialization_incomplete / needs_materialization
      - status == "source_unavailable", "failed", or "error" → not_assessed / cannot_answer_yet
      - status == "no_*" or zero-count signals → not_observed_in_consulted_scope
      - any obvious evidence count > 0 → evidence_present, scoped_answer_only
      - otherwise → not_assessed
    """

    status = str(result.get("status") or "").lower()
    ok = result.get("ok")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    observations = {
        "status": status or None,
        "ok": ok,
    }
    # try to surface a record / candidate / match count
    count_keys = (
        "record_count",
        "result_count",
        "candidate_count",
        "match_count",
        "association_count",
        "total_records",
        "total_match_records",
    )
    for key in count_keys:
        if isinstance(summary, dict) and key in summary:
            observations[key] = summary[key]
        elif key in result:
            observations[key] = result[key]
    # Some operations (e.g. variant.gather_gene_context) carry their evidence
    # counts nested inside per-source summary objects — clinvar_gene.total_records,
    # sample_matches.total_records, research_evidence.record_count — rather than at
    # the top level, and emit no top-level `status`/`ok`. Without looking one level
    # down, a result that gathered genuinely useful gene context would fall through
    # to not_assessed/cannot_answer_yet. When no top-level count is present, surface
    # any positive nested count so partial-but-useful evidence is recognized.
    if not any(_as_count(observations.get(key)) > 0 for key in count_keys):
        for child_key, child in result.items():
            if not isinstance(child, dict):
                continue
            for key in count_keys:
                if key in child and _as_count(child[key]) > 0:
                    observations[f"{child_key}.{key}"] = child[key]

    query_scope = dict(result.get("query") or result.get("target") or {})
    coverage = _coverage(consulted_sources=[], unavailable_sources=[])

    if status in {"requires_library_install", "needs_library_install"}:
        library_status = _extract_library_status(result)
        if library_status is not None:
            return missing_library(
                operation=operation,
                library=str(library_status.get("library") or result.get("library") or "unknown"),
                library_status_payload=library_status,
                query_scope=query_scope,
                intent=str(result.get("intent") or result.get("how_it_helps") or ""),
                notes=_string_notes(result),
                guidance=["blocked_missing_library:ask_user_to_install"],
            )
        return not_assessed(
            operation=operation,
            reason="Operation reports a required library is missing.",
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )
    if status == "in_progress":
        return envelope(
            operation=operation,
            finding_state=MATERIALIZATION_INCOMPLETE,
            answer_readiness=NEEDS_MATERIALIZATION,
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            negative_inference=_negative_inference(
                allowed=False,
                requires=[REQ_LIBRARY_COVERAGE],
                reason="The operation is still running; partial state cannot be interpreted.",
            ),
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )
    if status in {"source_unavailable", "source_unavailable_no_evidence", "error", "unavailable", "failed"}:
        return not_assessed(
            operation=operation,
            reason=f"Operation reported status={status!r}; no evidence to interpret.",
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )
    if status.startswith(("invalid", "missing", "wrong", "blocked", "needs", "requires", "not_")):
        return not_assessed(
            operation=operation,
            reason=f"Operation reported status={status!r}.",
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )
    if ok is False:
        return not_assessed(
            operation=operation,
            reason="Operation returned ok=false.",
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )

    positive_count = 0
    for key, value in observations.items():
        if key in {"status", "ok"}:
            continue
        positive_count += _as_count(value)

    if positive_count > 0:
        return evidence_present(
            operation=operation,
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            answer_readiness=SCOPED_ANSWER_ONLY,
            guidance=_status_guidance(status, ok),
        )

    # zero-count fall-through
    if status.startswith("no_") or "_empty" in status or (status == "completed" and positive_count == 0):
        return empty_consulted_scope(
            operation=operation,
            query_scope=query_scope,
            coverage=coverage,
            observations=observations,
            next_actions=_status_next_actions(status, result),
            notes=_string_notes(result),
            guidance=_status_guidance(status, ok),
        )
    return not_assessed(
        operation=operation,
        reason="Operation did not emit an envelope and result indicators were inconclusive.",
        query_scope=query_scope,
        coverage=coverage,
        observations=observations,
        next_actions=_status_next_actions(status, result),
        notes=_string_notes(result),
        guidance=_status_guidance(status, ok),
    )


def _extract_library_status(result: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("missing_library", "library"):
        value = result.get(key)
        if isinstance(value, dict) and value.get("install_command"):
            return dict(value)
    request = result.get("library_install_request")
    if isinstance(request, dict):
        value = request.get("missing_library")
        if isinstance(value, dict) and value.get("install_command"):
            return dict(value)
    return None


def _string_notes(result: dict[str, Any]) -> list[str]:
    notes = []
    for key in ("message", "reason", "error", "how_it_helps"):
        value = result.get(key)
        if isinstance(value, str) and value:
            notes.append(value)
    error = result.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            notes.append(message)
    return notes


def _status_guidance(status: str, ok: Any = None) -> list[str]:
    if status == "in_progress":
        return ["in_progress:poll_runtime_check_background_job"]
    if status in {"requires_library_install", "needs_library_install"}:
        return ["blocked_missing_library:ask_user_to_install"]
    if status in {"source_unavailable", "source_unavailable_no_evidence", "unavailable"}:
        return ["source_unavailable:retry_or_use_alternate_source"]
    if status in {"failed", "error"} or status.endswith("_failed"):
        return ["operation_failed:inspect_error_before_retry"]
    if status.startswith("invalid"):
        return ["invalid_input:fix_params_before_retry"]
    if status.startswith("missing"):
        return ["missing_input:provide_required_context"]
    if status.startswith("wrong"):
        return ["wrong_evidence_regime:use_matching_tool"]
    if status.startswith("not_"):
        return ["not_assessed:request_missing_inputs_or_use_different_tool"]
    if status.startswith("no_") or "_empty" in status:
        return [
            "not_observed_in_consulted_scope:do_not_imply_global_negative",
            "negative_inference_disallowed:do_not_state_clinical_negative",
        ]
    if ok is False:
        return ["operation_not_ok:inspect_status_and_next_actions"]
    return []


def _status_next_actions(status: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if status == "in_progress":
        job_id = result.get("job_id")
        return [
            {
                "action": "poll_background_job",
                "operation": "genomi.check_background_job",
                "params": {"job_id": job_id} if job_id else {},
            }
        ]
    if status in {"requires_library_install", "needs_library_install"}:
        library_status = _extract_library_status(result)
        install_command = library_status.get("install_command") if library_status else None
        return [
            {
                "action": "install_library",
                "library": library_status.get("library") if library_status else result.get("library"),
                "install_command": install_command,
            }
        ]
    if status.startswith(("invalid", "missing")):
        missing_inputs = []
        for item in result.get("unanswered_answer_components") or []:
            if isinstance(item, dict):
                missing_inputs.extend(str(value) for value in item.get("missing_inputs") or [])
        return [{"action": "fix_inputs", "missing_inputs": sorted(set(missing_inputs))}]
    if status in {"source_unavailable", "source_unavailable_no_evidence", "unavailable"}:
        return [{"action": "retry_or_use_alternate_source"}]
    if status in {"failed", "error"} or status.endswith("_failed"):
        return [{"action": "inspect_error_before_retry"}]
    if status.startswith("wrong"):
        return [{"action": "use_matching_evidence_tool"}]
    return []
