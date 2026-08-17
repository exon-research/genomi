"""Local persistence for typed public-evidence-to-patient disease relations."""

from __future__ import annotations

import hashlib
from typing import Any, ContextManager, Protocol

from ..evidence import envelope as canonical_evidence_envelope
from .disease_relation_contract import (
    DISEASE_RELATION_RECORD_TYPE,
    REGISTER_DISEASE_RELATION,
    RELATION_KIND_SOURCE_FAMILIES,
    eligible_public_context_source,
    eligible_public_relation_source,
    validate_disease_relation_parameters,
)
from .models import JsonObject, compact_json, row_dict


_DISEASE_RELATION_COMMIT_TOKEN = object()


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...

    def _validate_claim_anchors(
        self,
        investigation_id: str,
        *,
        evidence_record_ids: list[str],
        profile_revision_ids: list[str],
    ) -> None: ...

    def commit_evidence(
        self,
        investigation_id: str,
        *,
        source_family: object,
        operation: object,
        evidence: JsonObject,
        deduplication_key: object,
        expected_plan_version_id: object = None,
        expected_consent_receipt_id: object = None,
        _reserved_operation_token: object = None,
        emit_investigation_event: bool = False,
    ) -> JsonObject: ...


def validate_reserved_relation_commit(operation: str, token: object) -> None:
    """Prevent generic ledger writes from impersonating a validated relation."""

    if (
        operation == REGISTER_DISEASE_RELATION
        and token is not _DISEASE_RELATION_COMMIT_TOKEN
    ):
        raise ValueError("disease-relation evidence must use commit_disease_relation")


class DiseaseRelationStoreMixin:
    """Commit source-grounded disease relations inside the local domain only."""

    def commit_disease_relation(
        self: _StoreContract,
        investigation_id: str,
        parameters: object,
        *,
        expected_plan_version_id: object = None,
        expected_consent_receipt_id: object = None,
    ) -> JsonObject:
        relation = validate_disease_relation_parameters(parameters)
        investigation = self.get_investigation(investigation_id)
        expected_scope = str(
            investigation.get("disease_scope") or investigation.get("question") or ""
        ).strip()
        if relation["disease_scope"] != expected_scope:
            raise ValueError(
                "disease-relation scope must exactly match the investigation disease scope"
            )
        source_ids = list(relation["source_evidence_record_ids"])
        conflict_ids = [
            str(item["source_evidence_record_id"]) for item in relation["conflicts"]
        ]
        all_evidence_ids = list(dict.fromkeys([*source_ids, *conflict_ids]))
        self._validate_claim_anchors(
            investigation_id,
            evidence_record_ids=all_evidence_ids,
            profile_revision_ids=list(relation["profile_revision_ids"]),
        )
        records = self._disease_relation_source_records(
            investigation_id, all_evidence_ids
        )
        source_records = [records[value] for value in source_ids]
        context_only = relation["direction"] == "context_only"
        source_eligible = (
            eligible_public_context_source
            if context_only
            else eligible_public_relation_source
        )
        if not all(source_eligible(record) for record in source_records):
            raise ValueError(
                "disease relations require usable, non-personal, non-model public source evidence"
            )
        source_families = {
            str(record.get("source_family") or "") for record in source_records
        }
        if len(source_families) != 1:
            raise ValueError(
                "one disease relation must preserve one public source-family prior"
            )
        if not all(
            eligible_public_relation_source(records[value]) for value in conflict_ids
        ):
            raise ValueError(
                "disease-relation conflicts must cite usable public source evidence"
            )
        source_family = next(iter(source_families))
        if source_family == "trial_registry" and not (
            relation["relation_kind"] == "trial_relevance" and context_only
        ):
            raise ValueError(
                "trial registrations may create only context-only trial-relevance relations"
            )
        if source_family not in RELATION_KIND_SOURCE_FAMILIES[
            relation["relation_kind"]
        ]:
            raise ValueError(
                "disease-relation kind does not match the cited source-family prior"
            )
        evidence: JsonObject = {
            "status": "committed_relation",
            "record_type": DISEASE_RELATION_RECORD_TYPE,
            "disease_relation": relation,
            "evidence_envelope": canonical_evidence_envelope.evidence_present(
                operation=REGISTER_DISEASE_RELATION,
                query_scope={
                    "disease_scope": relation["disease_scope"],
                    "relation_kind": relation["relation_kind"],
                    "direction": relation["direction"],
                    "source_family": source_family,
                },
                personal_context={
                    "patient_influenced_query": True,
                    "uses_personal_dna": False,
                    "profile_revision_ids": list(relation["profile_revision_ids"]),
                },
                coverage={
                    "source_evidence_record_ids": source_ids,
                    "conflict_evidence_record_ids": conflict_ids,
                },
                observations={
                    "relation_count": 1,
                    "conflict_count": len(conflict_ids),
                    "uncertainty_count": len(relation["uncertainty"]),
                },
                answer_readiness=(
                    canonical_evidence_envelope.NEEDS_CLINICAL_CONFIRMATION
                ),
            ),
        }
        identity = hashlib.sha256(compact_json(relation).encode("utf-8")).hexdigest()
        return self.commit_evidence(
            investigation_id,
            source_family=source_family,
            operation=REGISTER_DISEASE_RELATION,
            evidence=evidence,
            deduplication_key=f"disease-relation:{identity}",
            expected_plan_version_id=expected_plan_version_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
            _reserved_operation_token=_DISEASE_RELATION_COMMIT_TOKEN,
            emit_investigation_event=True,
        )

    def _disease_relation_source_records(
        self: _StoreContract,
        investigation_id: str,
        evidence_record_ids: list[str],
    ) -> dict[str, JsonObject]:
        if not evidence_record_ids:
            return {}
        placeholders = ",".join("?" for _ in evidence_record_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM evidence_records WHERE investigation_id = ? "
                f"AND evidence_record_id IN ({placeholders})",
                (investigation_id, *evidence_record_ids),
            ).fetchall()
        records = {str(row["evidence_record_id"]): row_dict(row) for row in rows}
        if set(records) != set(evidence_record_ids):
            raise ValueError(
                "disease-relation evidence anchors must belong to the investigation"
            )
        return records
