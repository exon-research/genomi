"""Canonical evidence repository composition and artifact validation."""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from ..evidence import envelope as canonical_evidence_envelope
from .artifact_validation import validate_brief_artifact, validate_plan_artifact
from .brief_provenance import derive_brief_modality_badges
from .disease_relation_contract import is_qualifying_supporting_relation
from .evidence_artifact_store import EvidenceArtifactStoreMixin
from .evidence_record_store import (
    EvidenceCommitGuardError as EvidenceCommitGuardError,
    EvidenceRecordStoreMixin,
)
from .evidence_snapshot_store import EvidenceSnapshotStoreMixin
from .hypothesis_contract import GAP_KINDS
from .hypothesis_store import HypothesisStoreMixin
from .models import JsonObject, row_dict


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...

    def get_profile_snapshot(self, snapshot_id: str) -> JsonObject: ...

    def validate_plan(self, investigation_id: str, plan: JsonObject) -> None: ...

    def validate_brief(self, investigation_id: str, brief: JsonObject) -> None: ...

    def _validate_claim_anchors(
        self,
        investigation_id: str,
        *,
        evidence_record_ids: list[str],
        profile_revision_ids: list[str],
    ) -> None: ...


class EvidenceStoreMixin(
    EvidenceRecordStoreMixin,
    HypothesisStoreMixin,
    EvidenceSnapshotStoreMixin,
    EvidenceArtifactStoreMixin,
):
    """Compose evidence ledgers with plan and brief anchor validation."""

    def validate_plan(
        self: _StoreContract, investigation_id: str, plan: JsonObject
    ) -> None:
        validate_plan_artifact(plan)
        with self._connect() as connection:
            target = connection.execute(
                "SELECT 1 FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
        if target is None:
            raise KeyError(investigation_id)

    def validate_brief(
        self: _StoreContract, investigation_id: str, brief: JsonObject
    ) -> None:
        validate_brief_artifact(brief)
        cited_evidence_ids: set[str] = set()
        cited_revision_ids: set[str] = set()
        for claim in brief["claims"]:
            evidence_ids = [
                str(value) for value in claim.get("evidence_record_ids") or []
            ]
            revision_ids = [
                str(value) for value in claim.get("profile_revision_ids") or []
            ]
            self._validate_claim_anchors(
                investigation_id,
                evidence_record_ids=evidence_ids,
                profile_revision_ids=revision_ids,
            )
            cited_evidence_ids.update(evidence_ids)
            cited_revision_ids.update(revision_ids)

        evidence_records, profile_records = self._brief_anchor_records(
            investigation_id,
            evidence_record_ids=cited_evidence_ids,
            profile_revision_ids=cited_revision_ids,
        )
        investigation = self.get_investigation(investigation_id)
        disease_scope = str(
            investigation.get("disease_scope") or investigation.get("question") or ""
        ).strip()
        self._validate_claim_evidence_readiness(
            brief,
            evidence_records,
            profile_records,
            disease_scope=disease_scope,
        )
        self._validate_brief_hypothesis_references(investigation_id, brief)
        supported_badges = set(
            derive_brief_modality_badges(
                brief["claims"],
                evidence_records=evidence_records.values(),
                profile_records=profile_records.values(),
            )
        )
        validate_brief_artifact(brief, allowed_modality_badges=supported_badges)
        if set(brief["modality_badges"]) != supported_badges:
            raise ValueError(
                "brief modality_badges must identify every modality cited by its claims"
            )

    def _brief_anchor_records(
        self: _StoreContract,
        investigation_id: str,
        *,
        evidence_record_ids: set[str],
        profile_revision_ids: set[str],
    ) -> tuple[dict[str, JsonObject], dict[str, JsonObject]]:
        evidence_records: dict[str, JsonObject] = {}
        profile_records: dict[str, JsonObject] = {}
        with self._connect() as connection:
            if evidence_record_ids:
                placeholders = ",".join("?" for _ in evidence_record_ids)
                rows = connection.execute(
                    f"SELECT * FROM evidence_records WHERE investigation_id = ? "
                    f"AND patient_molecular_snapshot_id = "
                    f"(SELECT patient_molecular_snapshot_id FROM investigations "
                    f"WHERE investigation_id = ?) "
                    f"AND evidence_record_id IN ({placeholders})",
                    (
                        investigation_id,
                        investigation_id,
                        *sorted(evidence_record_ids),
                    ),
                ).fetchall()
                evidence_records = {
                    str(row["evidence_record_id"]): row_dict(row) for row in rows
                }
            if profile_revision_ids:
                placeholders = ",".join("?" for _ in profile_revision_ids)
                rows = connection.execute(
                    f"SELECT * FROM molecular_observations "
                    f"WHERE observation_revision_id IN ({placeholders})",
                    tuple(sorted(profile_revision_ids)),
                ).fetchall()
                profile_records = {
                    str(row["observation_revision_id"]): row_dict(row) for row in rows
                }
        return evidence_records, profile_records

    @staticmethod
    def _validate_claim_evidence_readiness(
        brief: JsonObject,
        evidence_records: dict[str, JsonObject],
        profile_records: dict[str, JsonObject],
        *,
        disease_scope: str,
    ) -> None:
        evidence_checked_roles = {
            "observation",
            "candidate_hypothesis",
            "counterevidence",
        }
        for claim in brief["claims"]:
            evidence_ids = [
                str(value) for value in claim.get("evidence_record_ids") or []
            ]
            profile_ids = [
                str(value) for value in claim.get("profile_revision_ids") or []
            ]
            if claim["claim_role"] == "candidate_hypothesis" and (
                not evidence_ids or not profile_ids
            ):
                raise ValueError(
                    "a candidate hypothesis claim requires both usable evidence and pinned profile anchors"
                )
            if claim["claim_role"] == "counterevidence" and (
                not evidence_ids or not profile_ids
            ):
                raise ValueError(
                    "a counterevidence claim requires both usable evidence and pinned profile anchors"
                )
            cited_profile = [profile_records[value] for value in profile_ids]
            uncertain_only = bool(cited_profile) and all(
                EvidenceStoreMixin._is_uncertain_classification(record)
                for record in cited_profile
            )
            if uncertain_only and claim["claim_role"] not in {
                "observation",
                "limitation",
            }:
                raise ValueError(
                    "an uncertain-variant profile record can support only an observation or limitation"
                )
            if claim["claim_role"] == "candidate_hypothesis" and evidence_ids:
                cited_evidence = [evidence_records[value] for value in evidence_ids]
                if all(
                    EvidenceStoreMixin._is_model_only_evidence(record)
                    for record in cited_evidence
                ):
                    raise ValueError(
                        "model output alone cannot support a candidate hypothesis claim"
                    )
                if not any(
                    is_qualifying_supporting_relation(
                        record,
                        disease_scope=disease_scope,
                        exact_profile_revision_ids=set(profile_ids),
                    )
                    for record in cited_evidence
                ):
                    raise ValueError(
                        "candidate hypothesis claims require a non-personal, non-model "
                        "supporting disease-relation record linked to the exact cited "
                        "profile anchors"
                    )
            if claim["claim_role"] not in evidence_checked_roles:
                continue
            for evidence_id in evidence_ids:
                if not EvidenceStoreMixin._evidence_record_is_usable(
                    evidence_records[evidence_id]
                ):
                    raise ValueError(
                        "unavailable, incomplete, or empty evidence cannot support "
                        "an observation, candidate hypothesis, or counterevidence claim"
                    )

    @staticmethod
    def _evidence_record_is_usable(record: JsonObject) -> bool:
        envelope = record.get("evidence_envelope")
        return (
            isinstance(envelope, dict)
            and envelope.get("finding_state")
            in {
                canonical_evidence_envelope.EVIDENCE_PRESENT,
                canonical_evidence_envelope.TRUE_NEGATIVE_SUPPORTED,
            }
            and envelope.get("answer_readiness")
            in {
                canonical_evidence_envelope.ANSWER_SUPPORTED,
                canonical_evidence_envelope.SCOPED_ANSWER_ONLY,
                canonical_evidence_envelope.NEEDS_CLINICAL_CONFIRMATION,
            }
        )

    @staticmethod
    def _is_uncertain_classification(record: JsonObject) -> bool:
        classification = str(record.get("reported_classification") or "").lower()
        normalized = " ".join(
            classification.replace("_", " ").replace("-", " ").split()
        )
        return normalized in {"vus", "variant of uncertain significance"} or (
            "uncertain" in normalized and "significance" in normalized
        )

    @staticmethod
    def _is_model_only_evidence(record: JsonObject) -> bool:
        if str(record.get("source_family") or "") in {
            "model",
            "computational_model",
        }:
            return True
        evidence = record.get("evidence")
        if not isinstance(evidence, dict):
            return False
        if evidence.get("may_raise_answer_readiness") is False:
            return True
        envelope = evidence.get("evidence_envelope")
        observations = (
            envelope.get("observations") if isinstance(envelope, dict) else None
        )
        return isinstance(observations, dict) and (
            observations.get("independent_clinical_claim_ready") is False
            and evidence.get("model_verification") is not None
        )

    def _validate_brief_hypothesis_references(
        self: _StoreContract, investigation_id: str, brief: JsonObject
    ) -> None:
        hypothesis_ids = [str(value) for value in brief["hypothesis_ids"]]
        gap_ids = [str(value) for value in brief["gap_ids"]]
        if len(set(hypothesis_ids)) != len(hypothesis_ids) or len(set(gap_ids)) != len(
            gap_ids
        ):
            raise ValueError(
                "brief hypothesis_ids and gap_ids cannot contain duplicates"
            )
        if set(hypothesis_ids) & set(gap_ids):
            raise ValueError("a brief reference cannot be both a hypothesis and a gap")
        requested = set(hypothesis_ids) | set(gap_ids)
        rows: list[Any] = []
        if requested:
            placeholders = ",".join("?" for _ in requested)
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT * FROM hypotheses "
                    f"WHERE investigation_id = ? "
                    f"AND hypothesis_id IN ({placeholders}) "
                    f"AND NOT EXISTS ("
                    f"SELECT 1 FROM hypotheses newer "
                    f"WHERE newer.investigation_id = hypotheses.investigation_id "
                    f"AND newer.logical_hypothesis_id = hypotheses.logical_hypothesis_id "
                    f"AND newer.version > hypotheses.version)",
                    (investigation_id, *sorted(requested)),
                ).fetchall()
        records = {str(row["hypothesis_id"]): row_dict(row) for row in rows}
        by_id = {
            hypothesis_id: str(record["kind"])
            for hypothesis_id, record in records.items()
        }
        if set(by_id) != requested:
            raise ValueError(
                "brief hypothesis_ids and gap_ids must be the latest versions of "
                "logical hypotheses in this investigation"
            )
        if any(by_id[value] in GAP_KINDS for value in hypothesis_ids):
            raise ValueError("brief hypothesis_ids cannot refer to evidence gaps")
        if any(by_id[value] not in GAP_KINDS for value in gap_ids):
            raise ValueError("brief gap_ids must refer to evidence gaps")
        candidate_records = {
            hypothesis_id: record
            for hypothesis_id, record in records.items()
            if record.get("kind") == "candidate_mechanism"
        }
        counterevidence_records = {
            hypothesis_id: record
            for hypothesis_id, record in records.items()
            if record.get("kind") == "counterevidence"
        }
        if brief["clinical_stage"] == "candidate_hypothesis" and not candidate_records:
            raise ValueError(
                "candidate_hypothesis briefs must reference a saved candidate hypothesis"
            )
        claim_roles = {str(claim.get("claim_role") or "") for claim in brief["claims"]}
        if candidate_records and "candidate_hypothesis" not in claim_roles:
            raise ValueError(
                "a brief that references a candidate hypothesis must include its traceable candidate claim"
            )
        if counterevidence_records and "counterevidence" not in claim_roles:
            raise ValueError(
                "a brief that references counterevidence must include its traceable counterevidence claim"
            )
        if gap_ids and "limitation" not in claim_roles:
            raise ValueError(
                "a brief that references an evidence gap must include a limitation claim"
            )
        records_by_claim_role = {
            "candidate_hypothesis": candidate_records,
            "counterevidence": counterevidence_records,
        }
        for claim_role, referenced in records_by_claim_role.items():
            required_anchor_sets = {
                (
                    frozenset(record.get("evidence_record_ids") or []),
                    frozenset(record.get("profile_revision_ids") or []),
                )
                for record in referenced.values()
            }
            presented_anchor_sets = {
                (
                    frozenset(claim.get("evidence_record_ids") or []),
                    frozenset(claim.get("profile_revision_ids") or []),
                )
                for claim in brief["claims"]
                if claim.get("claim_role") == claim_role
            }
            if not required_anchor_sets.issubset(presented_anchor_sets):
                raise ValueError(
                    f"every referenced {claim_role.replace('_', ' ')} must have "
                    "a brief claim with its exact saved anchors"
                )
        for claim in brief["claims"]:
            referenced = records_by_claim_role.get(str(claim["claim_role"]))
            if referenced is None:
                continue
            claim_evidence = set(claim.get("evidence_record_ids") or [])
            claim_profile = set(claim.get("profile_revision_ids") or [])
            if not any(
                claim_evidence == set(record.get("evidence_record_ids") or [])
                and claim_profile == set(record.get("profile_revision_ids") or [])
                for record in referenced.values()
            ):
                label = (
                    "candidate brief claim"
                    if claim["claim_role"] == "candidate_hypothesis"
                    else "counterevidence brief claim"
                )
                raise ValueError(
                    f"{label} anchors must exactly match a referenced saved hypothesis"
                )

        gap_anchor_sets = {
            (
                frozenset(record.get("evidence_record_ids") or []),
                frozenset(record.get("profile_revision_ids") or []),
            )
            for hypothesis_id, record in records.items()
            if hypothesis_id in set(gap_ids)
        }
        limitation_anchor_sets = {
            (
                frozenset(claim.get("evidence_record_ids") or []),
                frozenset(claim.get("profile_revision_ids") or []),
            )
            for claim in brief["claims"]
            if claim.get("claim_role") == "limitation"
        }
        if not gap_anchor_sets.issubset(limitation_anchor_sets):
            raise ValueError(
                "every referenced evidence gap must have a limitation claim "
                "with its exact saved anchors"
            )

    def _validate_claim_anchors(
        self: _StoreContract,
        investigation_id: str,
        *,
        evidence_record_ids: list[str],
        profile_revision_ids: list[str],
    ) -> None:
        investigation = self.get_investigation(investigation_id)
        snapshot_id = investigation.get("patient_molecular_snapshot_id")
        if not snapshot_id:
            raise ValueError(
                "claim anchors require an approved molecular-profile snapshot"
            )
        snapshot = self.get_profile_snapshot(str(snapshot_id))
        allowed_revisions = set(snapshot.get("observation_revision_ids") or [])
        if not set(profile_revision_ids).issubset(allowed_revisions):
            raise ValueError("profile claim anchors must belong to the pinned snapshot")
        if evidence_record_ids:
            with self._connect() as connection:
                placeholders = ",".join("?" for _ in evidence_record_ids)
                rows = connection.execute(
                    f"SELECT evidence_record_id FROM evidence_records "
                    f"WHERE investigation_id = ? "
                    f"AND patient_molecular_snapshot_id = ? "
                    f"AND evidence_record_id IN ({placeholders})",
                    (investigation_id, snapshot_id, *evidence_record_ids),
                ).fetchall()
            if {str(row["evidence_record_id"]) for row in rows} != set(
                evidence_record_ids
            ):
                raise ValueError(
                    "evidence claim anchors must belong to the investigation's current profile context"
                )
