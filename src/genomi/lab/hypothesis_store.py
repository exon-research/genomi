"""Versioned, evidence-anchored investigation hypothesis persistence."""

from __future__ import annotations

import uuid
from typing import Any, ContextManager, Protocol

from .artifact_validation import validate_research_narrative
from .disease_relation_contract import (
    REGISTER_DISEASE_RELATION,
    disease_relation_direction,
    is_qualifying_supporting_relation,
)
from .evidence_record_store import EvidenceCommitGuardError
from .hypothesis_contract import GAP_KINDS
from .models import JsonObject, compact_json, required_text, row_dict, utc_now


class _HypothesisStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...

    def _validate_claim_anchors(
        self,
        investigation_id: str,
        *,
        evidence_record_ids: list[str],
        profile_revision_ids: list[str],
    ) -> None: ...

    def _brief_anchor_records(
        self,
        investigation_id: str,
        *,
        evidence_record_ids: set[str],
        profile_revision_ids: set[str],
    ) -> tuple[dict[str, JsonObject], dict[str, JsonObject]]: ...

    def _evidence_record_is_usable(self, record: JsonObject) -> bool: ...

    def _is_model_only_evidence(self, record: JsonObject) -> bool: ...


class HypothesisStoreMixin:
    """Persist versioned hypotheses only after validating their exact anchors."""

    def commit_hypothesis(
        self: _HypothesisStore,
        investigation_id: str,
        *,
        kind: object,
        statement: object,
        evidence_record_ids: object,
        profile_revision_ids: object,
        status: object = "candidate",
        supersedes_hypothesis_id: object = None,
        expected_consent_receipt_id: object = None,
    ) -> JsonObject:
        if not isinstance(evidence_record_ids, list) or not isinstance(
            profile_revision_ids, list
        ):
            raise ValueError("hypothesis anchors must be arrays")
        evidence_ids = [
            required_text(value, "evidence_record_id", 200)
            for value in evidence_record_ids
        ]
        revision_ids = [
            required_text(value, "profile_revision_id", 200)
            for value in profile_revision_ids
        ]
        if not evidence_ids and not revision_ids:
            raise ValueError("a hypothesis must cite evidence or a profile observation")
        kind_value = required_text(kind, "kind", 80)
        status_value = required_text(status, "status", 80)
        allowed_kinds = {
            "candidate_mechanism",
            "counterevidence",
            "uncertainty",
            *GAP_KINDS,
        }
        allowed_statuses = {
            "candidate",
            "open",
            "supported",
            "weakened",
            "rejected",
            "resolved",
        }
        if kind_value not in allowed_kinds:
            raise ValueError(
                "hypothesis kind must use the declared investigation vocabulary"
            )
        if status_value not in allowed_statuses:
            raise ValueError(
                "hypothesis status must use the declared investigation vocabulary"
            )
        statement_value = validate_research_narrative(
            statement,
            "hypothesis statement",
            kind=(
                "hypothesis_candidate_mechanism"
                if kind_value == "candidate_mechanism"
                else "hypothesis_counterevidence"
                if kind_value == "counterevidence"
                else "hypothesis_uncertainty"
                if kind_value == "uncertainty"
                else "hypothesis_gap"
            ),
        )
        expected_consent = (
            required_text(
                expected_consent_receipt_id,
                "expected_consent_receipt_id",
                200,
            )
            if expected_consent_receipt_id not in (None, "")
            else None
        )
        if kind_value in {"candidate_mechanism", "counterevidence"} and (
            not evidence_ids or not revision_ids
        ):
            raise ValueError(
                "candidate mechanisms and counterevidence require both evidence and pinned profile anchors"
            )
        self._validate_claim_anchors(
            investigation_id,
            evidence_record_ids=evidence_ids,
            profile_revision_ids=revision_ids,
        )
        if kind_value in {"candidate_mechanism", "counterevidence"}:
            evidence_records, _ = self._brief_anchor_records(
                investigation_id,
                evidence_record_ids=set(evidence_ids),
                profile_revision_ids=set(revision_ids),
            )
            if not all(
                self._evidence_record_is_usable(record)
                for record in evidence_records.values()
            ):
                raise ValueError(
                    "candidate mechanisms and counterevidence require usable, "
                    "answer-scoped evidence"
                )
            if all(
                self._is_model_only_evidence(record)
                for record in evidence_records.values()
            ):
                raise ValueError(
                    "model output alone cannot support a candidate mechanism or counterevidence"
                )
        if kind_value == "candidate_mechanism":
            investigation = self.get_investigation(investigation_id)
            disease_scope = str(
                investigation.get("disease_scope")
                or investigation.get("question")
                or ""
            ).strip()
            if not any(
                is_qualifying_supporting_relation(
                    record,
                    disease_scope=disease_scope,
                    exact_profile_revision_ids=set(revision_ids),
                )
                for record in evidence_records.values()
            ):
                raise ValueError(
                    "candidate mechanisms require a non-personal, non-model "
                    "supporting disease-relation record linked to the exact cited "
                    "profile anchors"
                )
        if kind_value == "counterevidence":
            relation_records = [
                record
                for record in evidence_records.values()
                if record.get("operation") == REGISTER_DISEASE_RELATION
            ]
            if any(
                disease_relation_direction(record) not in {"refutes", "mixed"}
                for record in relation_records
            ):
                raise ValueError(
                    "counterevidence cannot cite a disease relation unless its "
                    "direction is refutes or mixed"
                )
        hypothesis_id = f"hypothesis-{uuid.uuid4().hex}"
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT user_id, patient_molecular_snapshot_id, "
                "active_consent_receipt_id FROM investigations "
                "WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if investigation is None:
                raise KeyError(investigation_id)
            profile_snapshot_id = investigation["patient_molecular_snapshot_id"]
            if not profile_snapshot_id:
                raise ValueError(
                    "a hypothesis requires an approved molecular-profile snapshot"
                )
            if expected_consent is not None:
                consent = connection.execute(
                    "SELECT 1 FROM consent_receipts "
                    "WHERE consent_receipt_id = ? AND investigation_id = ? "
                    "AND user_id = ? AND patient_molecular_snapshot_id IS ? "
                    "AND revoked_at IS NULL",
                    (
                        expected_consent,
                        investigation_id,
                        investigation["user_id"],
                        profile_snapshot_id,
                    ),
                ).fetchone()
                if (
                    consent is None
                    or investigation["active_consent_receipt_id"] != expected_consent
                ):
                    raise EvidenceCommitGuardError(
                        "consent_revoked",
                        "private molecular-context consent changed before hypothesis commit",
                    )
            existing = connection.execute(
                "SELECT * FROM hypotheses WHERE investigation_id = ? AND kind = ? "
                "AND statement = ? AND status = ? AND evidence_record_ids_json = ? "
                "AND profile_revision_ids_json = ? "
                "AND patient_molecular_snapshot_id = ?",
                (
                    investigation_id,
                    kind_value,
                    statement_value,
                    status_value,
                    compact_json(evidence_ids),
                    compact_json(revision_ids),
                    profile_snapshot_id,
                ),
            ).fetchone()
            if existing is not None:
                return row_dict(existing)
            supersedes = None
            logical_hypothesis_id = f"hypothesis-thread-{uuid.uuid4().hex}"
            version = 1
            if supersedes_hypothesis_id not in (None, ""):
                supersedes = required_text(
                    supersedes_hypothesis_id, "supersedes_hypothesis_id", 200
                )
                prior = connection.execute(
                    "SELECT * FROM hypotheses WHERE hypothesis_id = ? "
                    "AND investigation_id = ? "
                    "AND patient_molecular_snapshot_id = ?",
                    (supersedes, investigation_id, profile_snapshot_id),
                ).fetchone()
                if prior is None:
                    raise ValueError(
                        "supersedes_hypothesis_id must belong to this investigation's current profile context"
                    )
                logical_hypothesis_id = str(prior["logical_hypothesis_id"])
                version = int(prior["version"]) + 1
                newer = connection.execute(
                    "SELECT 1 FROM hypotheses WHERE supersedes_hypothesis_id = ?",
                    (supersedes,),
                ).fetchone()
                if newer is not None:
                    raise ValueError(
                        "a newer revision already supersedes this hypothesis"
                    )
            connection.execute(
                """
                INSERT INTO hypotheses(
                    hypothesis_id, logical_hypothesis_id, investigation_id,
                    patient_molecular_snapshot_id,
                    supersedes_hypothesis_id, version, kind, statement, status,
                    evidence_record_ids_json, profile_revision_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hypothesis_id,
                    logical_hypothesis_id,
                    investigation_id,
                    profile_snapshot_id,
                    supersedes,
                    version,
                    kind_value,
                    statement_value,
                    status_value,
                    compact_json(evidence_ids),
                    compact_json(revision_ids),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)
            ).fetchone()
        return row_dict(row)
