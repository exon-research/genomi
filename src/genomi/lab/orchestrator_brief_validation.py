"""Runtime validation for Main-Orchestrator clinician briefs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ContextManager, Protocol

from .artifact_validation import BRIEF_CLINICAL_BOUNDARY
from .informational_narrative import validate_informational_narrative
from .models import (
    JsonObject,
    compact_json,
    required_text,
    validate_private_payload,
)


_BRIEF_FIELDS = {
    "title",
    "summary",
    "claims",
    "hypothesis_ids",
    "gap_ids",
    "confirmation_needs",
    "professional_questions",
    "clinical_boundary",
}
_CLAIM_FIELDS = {"statement", "evidence_record_ids", "profile_revision_ids"}


class _BriefValidationStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


def validate_orchestrator_brief(
    store: _BriefValidationStore,
    investigation: Mapping[str, object],
    cycle: Mapping[str, object],
    brief: JsonObject,
) -> None:
    _validate_current_cycle(store, investigation, cycle)
    validate_private_payload(brief)
    if set(brief) != _BRIEF_FIELDS:
        raise ValueError("brief must use the complete clinician brief shape")
    title = required_text(brief.get("title"), "brief.title", 500)
    summary = required_text(brief.get("summary"), "brief.summary", 10_000)
    validate_informational_narrative(title, "brief.title", kind="brief_title")
    validate_informational_narrative(summary, "brief.summary", kind="brief_summary")
    if brief.get("clinical_boundary") != BRIEF_CLINICAL_BOUNDARY:
        raise ValueError("brief must preserve the informational clinical boundary")

    claims = brief.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("brief.claims must be a non-empty array")
    hypothesis_ids = _identifier_array(brief, "hypothesis_ids")
    gap_ids = _identifier_array(brief, "gap_ids")
    if set(hypothesis_ids) & set(gap_ids):
        raise ValueError("brief references cannot be both hypotheses and gaps")
    for value in _text_array(brief, "confirmation_needs"):
        validate_informational_narrative(
            value, "brief confirmation need", kind="confirmation_need"
        )
    for value in _text_array(brief, "professional_questions"):
        validate_informational_narrative(
            value, "brief professional question", kind="professional_question"
        )

    evidence_ids: set[str] = set()
    fact_ids: set[str] = set()
    claim_fingerprints: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("every brief claim must be an object")
        if set(claim) != _CLAIM_FIELDS:
            raise ValueError("every brief claim must use the complete claim shape")
        statement = required_text(
            claim.get("statement"), "brief claim statement", 8_000
        )
        validate_informational_narrative(
            statement, "brief claim statement", kind="assertion"
        )
        for field, target in (
            ("evidence_record_ids", evidence_ids),
            ("profile_revision_ids", fact_ids),
        ):
            values = claim.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(
                    f"brief claim {field} must be an array of identifiers"
                )
            if len(values) != len(set(values)):
                raise ValueError(f"brief claim {field} cannot contain duplicates")
            target.update(values)
        if not (claim.get("evidence_record_ids") or claim.get("profile_revision_ids")):
            raise ValueError(
                "every brief claim must cite captured evidence or approved patient facts"
            )
        fingerprint = compact_json(dict(claim))
        if fingerprint in claim_fingerprints:
            raise ValueError("brief claims must be unique")
        claim_fingerprints.add(fingerprint)

    with store._connect() as connection:
        if not evidence_ids.issubset(
            _current_evidence_ids(connection, investigation)
        ):
            raise ValueError(
                "brief evidence claims must belong to the current evidence snapshot"
            )
        _validate_current_profile_fact_ids(connection, investigation, fact_ids)
        _validate_current_references(
            connection,
            investigation,
            hypothesis_ids=hypothesis_ids,
            gap_ids=gap_ids,
        )


def _validate_current_cycle(
    store: _BriefValidationStore,
    investigation: Mapping[str, object],
    cycle: Mapping[str, object],
) -> None:
    with store._connect() as connection:
        latest = connection.execute(
            "SELECT cycle_id FROM investigation_cycles "
            "WHERE investigation_id = ? ORDER BY ordinal DESC LIMIT 1",
            (investigation["investigation_id"],),
        ).fetchone()
    if latest is None or str(latest["cycle_id"]) != str(cycle["cycle_id"]):
        raise ValueError("brief must be published from the current investigation cycle")
    if cycle.get("patient_molecular_snapshot_id") != investigation.get(
        "patient_molecular_snapshot_id"
    ):
        raise ValueError("brief cycle must use the current profile snapshot")


def _identifier_array(brief: JsonObject, field: str) -> list[str]:
    values = brief.get(field)
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise ValueError(f"brief {field} must be an array of identifiers")
    if len(values) != len(set(values)):
        raise ValueError(f"brief {field} cannot contain duplicates")
    return values


def _text_array(brief: JsonObject, field: str) -> list[str]:
    values = brief.get(field)
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise ValueError(f"brief {field} must be an array of text")
    if len(values) != len(set(values)):
        raise ValueError(f"brief {field} cannot contain duplicates")
    return values


def _current_evidence_ids(
    connection: Any, investigation: Mapping[str, object]
) -> set[str]:
    evidence_snapshot_id = investigation.get("evidence_snapshot_id")
    if not evidence_snapshot_id:
        return set()
    snapshot = connection.execute(
        "SELECT * FROM evidence_snapshots WHERE evidence_snapshot_id = ? "
        "AND investigation_id = ?",
        (evidence_snapshot_id, investigation["investigation_id"]),
    ).fetchone()
    if snapshot is None:
        raise ValueError("the current evidence snapshot is unavailable")
    if snapshot["patient_molecular_snapshot_id"] != investigation.get(
        "patient_molecular_snapshot_id"
    ):
        raise ValueError("the current evidence snapshot uses a stale profile snapshot")
    values = json.loads(str(snapshot["evidence_record_ids_json"]))
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("the current evidence snapshot is invalid")
    return set(values)


def _validate_current_profile_fact_ids(
    connection: Any,
    investigation: Mapping[str, object],
    fact_ids: set[str],
) -> None:
    if not fact_ids:
        return
    snapshot_id = investigation.get("patient_molecular_snapshot_id")
    if not snapshot_id:
        raise ValueError("brief patient facts require an approved profile snapshot")
    snapshot = connection.execute(
        "SELECT observation_revision_ids_json FROM profile_snapshots "
        "WHERE patient_molecular_snapshot_id = ? AND investigation_id = ?",
        (snapshot_id, investigation["investigation_id"]),
    ).fetchone()
    allowed = (
        set(json.loads(str(snapshot["observation_revision_ids_json"])))
        if snapshot
        else set()
    )
    if not fact_ids.issubset(allowed):
        raise ValueError("brief cites facts outside the current approved profile snapshot")


def _validate_current_references(
    connection: Any,
    investigation: Mapping[str, object],
    *,
    hypothesis_ids: list[str],
    gap_ids: list[str],
) -> None:
    hypothesis_rows = connection.execute(
        "SELECT thread.logical_hypothesis_id, version.hypothesis_version_id, "
        "version.patient_molecular_snapshot_id, "
        "version.evidence_snapshot_id FROM orchestrator_hypothesis_threads AS thread "
        "JOIN orchestrator_hypothesis_versions AS version "
        "ON version.logical_hypothesis_id = thread.logical_hypothesis_id "
        "WHERE thread.investigation_id = ? AND version.version = ("
        "SELECT MAX(latest.version) FROM orchestrator_hypothesis_versions AS latest "
        "WHERE latest.logical_hypothesis_id = thread.logical_hypothesis_id)",
        (investigation["investigation_id"],),
    ).fetchall()
    hypotheses_by_identifier: dict[str, Any] = {}
    for row in hypothesis_rows:
        hypotheses_by_identifier[str(row["logical_hypothesis_id"])] = row
        hypotheses_by_identifier[str(row["hypothesis_version_id"])] = row
    if not set(hypothesis_ids).issubset(hypotheses_by_identifier):
        raise ValueError(
            "brief hypothesis references must identify current logical hypotheses "
            "or their latest versions"
        )
    resolved_hypotheses = {
        str(hypotheses_by_identifier[value]["logical_hypothesis_id"])
        for value in hypothesis_ids
    }
    if len(resolved_hypotheses) != len(hypothesis_ids):
        raise ValueError("brief references cannot repeat one logical hypothesis")
    for identifier in hypothesis_ids:
        row = hypotheses_by_identifier[identifier]
        if row["patient_molecular_snapshot_id"] != investigation.get(
            "patient_molecular_snapshot_id"
        ):
            raise ValueError("brief references must use the current profile snapshot")
        if row["evidence_snapshot_id"] != investigation.get("evidence_snapshot_id"):
            raise ValueError("brief references must use the current evidence snapshot")

    gap_rows = connection.execute(
        "SELECT thread.logical_information_gap_id, "
        "version.information_gap_version_id, version.status, "
        "version.patient_molecular_snapshot_id, version.evidence_snapshot_id "
        "FROM information_gap_threads AS thread "
        "JOIN information_gap_versions AS version "
        "ON version.logical_information_gap_id = thread.logical_information_gap_id "
        "WHERE thread.investigation_id = ? AND version.version = ("
        "SELECT MAX(latest.version) FROM information_gap_versions AS latest "
        "WHERE latest.logical_information_gap_id = "
        "thread.logical_information_gap_id)",
        (investigation["investigation_id"],),
    ).fetchall()
    gaps_by_identifier: dict[str, Any] = {}
    for row in gap_rows:
        gaps_by_identifier[str(row["logical_information_gap_id"])] = row
        gaps_by_identifier[str(row["information_gap_version_id"])] = row
    if not set(gap_ids).issubset(gaps_by_identifier):
        raise ValueError(
            "brief gap references must identify current information gaps or their "
            "latest versions"
        )
    resolved_gaps = {
        str(gaps_by_identifier[value]["logical_information_gap_id"])
        for value in gap_ids
    }
    if len(resolved_gaps) != len(gap_ids):
        raise ValueError("brief references cannot repeat one logical information gap")
    for identifier in gap_ids:
        row = gaps_by_identifier[identifier]
        if row["status"] != "open":
            raise ValueError("brief gap references must be current open information gaps")
        if row["patient_molecular_snapshot_id"] != investigation.get(
            "patient_molecular_snapshot_id"
        ):
            raise ValueError("brief gap references must use the current profile snapshot")
        if row["evidence_snapshot_id"] != investigation.get("evidence_snapshot_id"):
            raise ValueError("brief gap references must use the current evidence snapshot")


__all__ = ["validate_orchestrator_brief"]
