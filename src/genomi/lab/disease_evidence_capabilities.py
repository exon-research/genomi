"""Patient-anchored, local Genomi disease-evidence capability contracts.

These contracts expose only Genomi operations that can run without network
egress for the request itself.  Public provider work remains behind the
GenomiLab evidence gateway; the current underlying agent still decides which
source prior is relevant and how results should be combined.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .disease_evidence_catalog import (
    GENCC_CLASSIFICATIONS,
    GENE_DISEASE_ASSOCIATIONS,
    LOCAL_DISEASE_EVIDENCE_CAPABILITIES,
    PATHWAY_MEMBERS,
    PHENOTYPE_GENE_COMPARE,
    PHENOTYPE_NORMALIZE,
    PUBLIC_EVIDENCE_SOURCE_PRIORS,
    build_local_disease_evidence_catalog,
)
from .models import JsonObject, compact_json, required_text


_HALLMARK_ID = re.compile(r"^HALLMARK_[A-Z0-9_]+$")


@dataclass(frozen=True)
class LocalGenomiEvidenceCall:
    operation: str
    params: JsonObject
    profile_revision_ids: tuple[str, ...]
    source_family: str | None = None


def validate_local_disease_evidence_request(
    capability: str,
    parameters: object,
    catalog_entry: object,
) -> LocalGenomiEvidenceCall:
    """Validate a request and project it to the fixed local Genomi operation."""

    if capability not in LOCAL_DISEASE_EVIDENCE_CAPABILITIES:
        raise ValueError("unsupported local disease-evidence capability")
    if not isinstance(parameters, dict):
        raise ValueError("capability parameters must be an object")
    request_contract = (
        catalog_entry.get("request_contract")
        if isinstance(catalog_entry, dict) and catalog_entry.get("available") is True
        else None
    )
    if not isinstance(request_contract, dict):
        raise ValueError("local disease-evidence capability contract is unavailable")
    _exact_fields(parameters, request_contract)

    if capability == PHENOTYPE_NORMALIZE:
        revision_ids = _selected_ids(parameters, request_contract)
        phenotypes = _selected_anchor_values(
            parameters.get("phenotypes"),
            "phenotypes",
            revision_ids,
            request_contract,
            anchor_field="phenotype",
        )
        hpo_ids = _selected_anchor_values(
            parameters.get("hpo_ids"),
            "hpo_ids",
            revision_ids,
            request_contract,
            anchor_field="hpo_id",
            uppercase=True,
        )
        if not phenotypes and not hpo_ids:
            raise ValueError(
                "phenotype normalization requires approved phenotype terms"
            )
        return LocalGenomiEvidenceCall(
            operation="phenotype.normalize_terms",
            params={"phenotypes": phenotypes, "hpo_ids": hpo_ids},
            profile_revision_ids=tuple(revision_ids),
        )

    if capability == GENE_DISEASE_ASSOCIATIONS:
        revision_ids = _selected_ids(parameters, request_contract)
        genes = _selected_anchor_values(
            parameters.get("genes"),
            "genes",
            revision_ids,
            request_contract,
            anchor_field="gene",
            uppercase=True,
        )
        if not genes:
            raise ValueError("gene-disease retrieval requires approved gene anchors")
        classifications = _text_array(
            parameters.get("classifications"), "classifications", uppercase=False
        )
        allowed_classifications = set(
            _field_allowed_values(request_contract, "classifications")
        )
        if (
            not classifications
            or not set(classifications).issubset(allowed_classifications)
            or not allowed_classifications.issubset(set(GENCC_CLASSIFICATIONS))
        ):
            raise ValueError("GenCC classifications exceed the declared source prior")
        limit = _limit(parameters.get("limit"), request_contract, "limit")
        return LocalGenomiEvidenceCall(
            operation="phenotype.retrieve_gene_disease_associations",
            params={
                "genes": genes,
                "classifications": classifications,
                "limit": limit,
            },
            profile_revision_ids=tuple(revision_ids),
            source_family="gencc",
        )

    if capability == PHENOTYPE_GENE_COMPARE:
        revision_ids = _selected_ids(parameters, request_contract)
        phenotypes = _selected_anchor_values(
            parameters.get("phenotypes"),
            "phenotypes",
            revision_ids,
            request_contract,
            anchor_field="phenotype",
        )
        hpo_ids = _selected_anchor_values(
            parameters.get("hpo_ids"),
            "hpo_ids",
            revision_ids,
            request_contract,
            anchor_field="hpo_id",
            uppercase=True,
        )
        genes = _selected_anchor_values(
            parameters.get("genes"),
            "genes",
            revision_ids,
            request_contract,
            anchor_field="gene",
            uppercase=True,
        )
        if not phenotypes and not hpo_ids:
            raise ValueError("HPO comparison requires approved phenotype anchors")
        if not genes:
            raise ValueError("HPO comparison requires approved gene anchors")
        limit = _limit(parameters.get("limit"), request_contract, "limit")
        return LocalGenomiEvidenceCall(
            operation="phenotype.compare_gene_hpo_evidence",
            params={
                "phenotypes": phenotypes,
                "hpo_ids": hpo_ids,
                "genes": genes,
                "search_stored_research": False,
                "use_hpo_annotations": True,
                "limit": limit,
            },
            profile_revision_ids=tuple(revision_ids),
            source_family="hpo",
        )

    revision_ids = _selected_ids(parameters, request_contract)
    pathway = required_text(
        parameters.get("pathway_id_or_name"), "pathway_id_or_name", 300
    ).upper()
    if not _HALLMARK_ID.fullmatch(pathway):
        raise ValueError("pathway lookup requires a controlled HALLMARK identifier")
    source_contract = _field_contract(request_contract, "source")
    if parameters.get("source") != source_contract.get("fixed_value"):
        raise ValueError("pathway source must preserve the MSigDB Hallmark prior")
    limit = _limit(parameters.get("limit"), request_contract, "limit")
    return LocalGenomiEvidenceCall(
        operation="pathway.retrieve_members",
        params={
            "pathway_id_or_name": pathway,
            "source": "msigdb_hallmark",
            "limit": limit,
        },
        profile_revision_ids=tuple(revision_ids),
        source_family="msigdb_hallmark",
    )


def execute_local_disease_evidence_request(
    application: Any,
    investigation_id: str,
    capability: str,
    parameters: JsonObject,
    catalog_entry: JsonObject,
    *,
    expected_plan_version_id: str | None = None,
    expected_consent_receipt_id: str | None = None,
) -> JsonObject:
    """Execute one validated local call and commit evidence by source prior."""

    call = validate_local_disease_evidence_request(
        capability, parameters, catalog_entry
    )
    profile = application.investigation_profile(investigation_id)
    result = application._safe_call(call.operation, call.params)
    if expected_plan_version_id is not None or expected_consent_receipt_id is not None:
        application.require_capability_commit_authority(
            investigation_id,
            expected_plan_version_id=expected_plan_version_id,
            expected_consent_receipt_id=expected_consent_receipt_id,
        )
    if call.source_family is None:
        return {
            "status": "completed",
            "profile_revision_ids": list(call.profile_revision_ids),
            "normalization": result,
        }
    if not isinstance(result.get("evidence_envelope"), dict):
        raise ValueError("Genomi evidence result has no canonical evidence envelope")
    evidence = dict(result)
    evidence["genomilab_context"] = {
        "disease_scope": application.investigation(investigation_id).get(
            "disease_scope"
        )
        or application.investigation(investigation_id).get("question"),
        "patient_molecular_snapshot_id": profile.get("patient_molecular_snapshot_id"),
        "profile_revision_ids": list(call.profile_revision_ids),
        "source_prior": call.source_family,
    }
    identity = hashlib.sha256(
        compact_json(
            {
                "operation": call.operation,
                "params": call.params,
                "patient_molecular_snapshot_id": profile.get(
                    "patient_molecular_snapshot_id"
                ),
                "profile_revision_ids": list(call.profile_revision_ids),
                "result": result,
            }
        ).encode("utf-8")
    ).hexdigest()
    record = application.store.commit_evidence(
        investigation_id,
        source_family=call.source_family,
        operation=call.operation,
        evidence=evidence,
        deduplication_key=f"local-genomi:{identity}",
        expected_plan_version_id=expected_plan_version_id,
        expected_consent_receipt_id=expected_consent_receipt_id,
        emit_investigation_event=True,
    )
    operational_status = _local_evidence_operational_status(result)
    return {
        "status": "committed" if operational_status is None else operational_status,
        "evidence_record": record,
        **(
            {
                "missing_library": result.get("missing_library"),
                "how_it_helps": result.get("how_it_helps"),
                "ask_user": result.get("ask_user"),
            }
            if operational_status == "requires_library_install"
            else {}
        ),
    }


def _selected_ids(parameters: JsonObject, contract: JsonObject) -> list[str]:
    selected = _text_array(
        parameters.get("profile_revision_ids"), "profile_revision_ids"
    )
    allowed = set(_field_allowed_values(contract, "profile_revision_ids"))
    if not selected or not set(selected).issubset(allowed):
        raise ValueError("profile anchors must belong to the approved pinned snapshot")
    return selected


def _selected_anchor_values(
    value: object,
    field: str,
    selected_revision_ids: list[str],
    contract: JsonObject,
    *,
    anchor_field: str,
    uppercase: bool = False,
) -> list[str]:
    values = _text_array(value, field, uppercase=uppercase)
    selected = set(selected_revision_ids)
    # The catalog deliberately exposes only values from eligible anchors.  A
    # request may choose a subset, but cannot add a term or gene absent from the
    # selected snapshot anchors.
    allowed_values = {
        str(item).upper() if uppercase else str(item)
        for item in _field_allowed_values(contract, field)
    }
    if not set(values).issubset(allowed_values):
        raise ValueError(f"{field} exceed the approved pinned profile values")

    bindings = contract.get("selection_bindings")
    if not isinstance(bindings, list):
        raise ValueError("profile anchor bindings are unavailable")
    for requested in values:
        if not any(
            isinstance(binding, dict)
            and binding.get("profile_revision_id") in selected
            and (
                str(binding.get(anchor_field) or "").upper()
                if uppercase
                else str(binding.get(anchor_field) or "")
            )
            == requested
            for binding in bindings
        ):
            raise ValueError(f"{field} are not bound to the selected profile anchors")
    return values


def _exact_fields(parameters: JsonObject, contract: JsonObject) -> None:
    required = contract.get("required_fields")
    optional = contract.get("optional_fields")
    if not isinstance(required, list) or not isinstance(optional, list):
        raise ValueError("local disease-evidence request contract is malformed")
    expected = {*required, *optional}
    if not set(required).issubset(parameters) or not set(parameters).issubset(expected):
        raise ValueError(
            "local disease-evidence request fields do not match the typed contract"
        )


def _text_array(
    value: object,
    field: str,
    *,
    uppercase: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result = [required_text(item, field, 1_000) for item in value]
    if uppercase:
        result = [item.upper() for item in result]
    if len(set(result)) != len(result):
        raise ValueError(f"{field} cannot contain duplicates")
    return result


def _limit(value: object, contract: JsonObject, field: str) -> int:
    field_contract = _field_contract(contract, field)
    minimum = field_contract.get("minimum")
    maximum = field_contract.get("maximum")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
    ):
        raise ValueError("limit contract must declare integer bounds")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"limit must be from {minimum} to {maximum}")
    return value


def _field_contract(contract: JsonObject, field: str) -> JsonObject:
    fields = contract.get("fields")
    value = fields.get(field) if isinstance(fields, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"{field} contract is unavailable")
    return value


def _field_allowed_values(contract: JsonObject, field: str) -> list[str]:
    value = _field_contract(contract, field).get("allowed_values")
    if not isinstance(value, list):
        raise ValueError(f"{field} allowed values are unavailable")
    return _text_array(value, field)


def _local_evidence_operational_status(result: JsonObject) -> str | None:
    status = str(result.get("status") or "")
    if status == "requires_library_install" or result.get("ask_user"):
        return "requires_library_install"
    if status in {
        "source_unavailable",
        "source_not_available",
        "authentication_failed",
        "rate_limited",
    }:
        return status
    return None


__all__ = [
    "GENE_DISEASE_ASSOCIATIONS",
    "LOCAL_DISEASE_EVIDENCE_CAPABILITIES",
    "LocalGenomiEvidenceCall",
    "PATHWAY_MEMBERS",
    "PHENOTYPE_GENE_COMPARE",
    "PHENOTYPE_NORMALIZE",
    "PUBLIC_EVIDENCE_SOURCE_PRIORS",
    "build_local_disease_evidence_catalog",
    "execute_local_disease_evidence_request",
    "validate_local_disease_evidence_request",
]
