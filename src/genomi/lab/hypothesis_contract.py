"""Typed contracts for evidence-anchored investigation synthesis."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .models import JsonObject


GAP_KINDS = frozenset({"evidence_gap", "confirmation_requirement"})

CASE_NARRATIVE_CONTRACT_TYPE = "approved_case_anchored_research_narrative"
CASE_NARRATIVE_MINIMUM_LENGTH = 20
CASE_NARRATIVE_MAXIMUM_LENGTH = 2_000

_EVIDENCE_VARIANT_TERM_FIELDS = frozenset(
    {
        "reported_variant",
        "rsid",
        "variant_id",
    }
)
_EVIDENCE_GENE_TERM_FIELDS = frozenset(
    {
        "gene",
        "candidate_genes",
        "matched_candidate_genes",
    }
)
_EVIDENCE_PROTEIN_SUBSTITUTION_TERM_FIELDS = frozenset(
    {"protein_substitution"}
)
_PROFILE_CASE_TERM_MODALITIES = frozenset(
    {
        "condition",
        "phenotype",
        "family_history",
        "medication",
        "exposure",
        "measurement",
        "procedure",
        "pathology",
        "biomarker",
    }
)
_PROFILE_CASE_TERM_VERIFICATION_STATES = frozenset(
    {"user_confirmed", "record_confirmed", "clinician_confirmed"}
)
_SIMPLE_CASE_TERM = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9 _:/+()'*-]{0,159}",
)
_UNSAFE_CASE_TERM = re.compile(
    r"\b(?:patient|you|we|they|he|she|has|have|had|is|are|was|were|"
    r"should|must|recommend|recommends|recommended|diagnose|diagnosed|"
    r"diagnosis|treat|treats|treated|dose|"
    r"causes|caused|causal|cures|cured|proves|proved|confirms|confirmed|"
    r"establishes|established|requires|required|eligible|actionable)\b",
    re.IGNORECASE,
)
_INSTRUCTION_OR_ASSERTION_TERM = re.compile(
    r"\b(?:ignore|previous|instruction|instructions|prompt|system|assistant|"
    r"developer|tool|tools|schema|json|execute|reveal|bypass|override|"
    r"predict|predicts|predicted|guarantee|guarantees|guaranteed|explain|"
    r"explains|explained|mean|means|meant|indicate|indicates|indicated|"
    r"demonstrate|demonstrates|demonstrated|show|shows|shown|drive|drives|"
    r"driven|lead|leads|leading|result|results|resulted|responsible|"
    r"pathogenic|benign|oncogenic|malignant|metastatic|positive|"
    r"benefit|benefits|effective|contraindicated|qualifies|present)\b",
    re.IGNORECASE,
)
_NAMED_VARIANT_IDENTIFIER = re.compile(
    r"(?:rs\d+|(?:VCV|RCV)\d+(?:\.\d+)?|COS[MV]\d+|CA\d+)",
    re.IGNORECASE,
)
_COORDINATE_VARIANT_IDENTIFIER = re.compile(
    r"(?:chr)?(?:[1-9]|1\d|2[0-2]|X|Y|MT):\d+(?::[ACGTN]+:[ACGTN]+)?",
    re.IGNORECASE,
)
_GENE_SYMBOL = re.compile(r"[A-Z][A-Z0-9-]{1,19}")
_PROTEIN_SUBSTITUTION_IDENTIFIER = re.compile(r"[A-Z][1-9][0-9]*[A-Z]")
_UNSAFE_PROFILE_CASE_TERM = re.compile(
    r"\b(?:patient|you|we|they|he|she|should|must|recommend|recommends|"
    r"recommended|diagnose|diagnosed|diagnosis|treat|treats|treated|dose|"
    r"causes|caused|causal|cures|cured|proves|proved|confirms|confirmed|"
    r"establishes|established|requires|required|eligible|actionable)\b",
    re.IGNORECASE,
)


def build_case_narrative_contract(
    *,
    disease_scope: object,
    molecular_profile: object,
    evidence_records: object = None,
) -> JsonObject:
    """Publish exact case terms that may enter otherwise closed research prose.

    The contract deliberately exposes approved display terms together with their
    typed profile anchors.  It does not turn source prose into an allowlist and
    it does not infer a scientific conclusion.
    """

    anchors: list[JsonObject] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()

    def add_anchor(
        text: object,
        *,
        source_kind: str,
        profile_revision_id: str | None = None,
        profile_modality: str | None = None,
        evidence_record_id: str | None = None,
        source_family: str | None = None,
    ) -> None:
        term = _eligible_case_term(text)
        if term is None:
            return
        key = (
            term.casefold(),
            source_kind,
            profile_revision_id,
            evidence_record_id,
        )
        if key in seen:
            return
        seen.add(key)
        anchor: JsonObject = {
            "text": term,
            "source_kind": source_kind,
        }
        if profile_revision_id is not None:
            anchor["profile_revision_id"] = profile_revision_id
        if profile_modality is not None:
            anchor["profile_modality"] = profile_modality
        if evidence_record_id is not None:
            anchor["evidence_record_id"] = evidence_record_id
        if source_family is not None:
            anchor["source_family"] = source_family
        anchors.append(anchor)

    del disease_scope
    profile = molecular_profile if isinstance(molecular_profile, Mapping) else {}
    observations = profile.get("observations")
    if isinstance(observations, Sequence) and not isinstance(
        observations, (str, bytes, bytearray)
    ):
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            revision_id = observation.get("observation_revision_id")
            if not isinstance(revision_id, str) or not revision_id.strip():
                continue
            modality = observation.get("modality")
            modality_value = (
                str(modality).strip()
                if isinstance(modality, str) and modality.strip()
                else None
            )
            if (
                modality_value in _PROFILE_CASE_TERM_MODALITIES
                and observation.get("verification_state")
                in _PROFILE_CASE_TERM_VERIFICATION_STATES
            ):
                add_anchor(
                    _profile_case_term(observation.get("label")),
                    source_kind="profile_observation",
                    profile_revision_id=revision_id,
                    profile_modality=modality_value,
                )
            if observation.get("normalization_state") not in {
                "rsid_ready",
                "exact_genomic_allele_ready",
            }:
                continue
            for field, projector in (("reported_variant", _variant_case_term),):
                add_anchor(
                    projector(observation.get(field)),
                    source_kind="profile_observation",
                    profile_revision_id=revision_id,
                    profile_modality=modality_value,
                )
            add_anchor(
                _gene_case_term(observation.get("gene")),
                source_kind="profile_observation",
                profile_revision_id=revision_id,
                profile_modality=modality_value,
            )

    records = evidence_records if isinstance(evidence_records, Sequence) else ()
    if isinstance(records, (str, bytes, bytearray)):
        records = ()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        evidence_record_id = record.get("evidence_record_id")
        if not isinstance(evidence_record_id, str) or not evidence_record_id.strip():
            continue
        source_family = record.get("source_family")
        source_family_value = (
            str(source_family).strip()
            if isinstance(source_family, str) and source_family.strip()
            else None
        )
        for value in _typed_evidence_case_terms(record):
            add_anchor(
                value,
                source_kind="evidence_typed_identifier",
                evidence_record_id=evidence_record_id,
                source_family=source_family_value,
            )

    return {
        "type": CASE_NARRATIVE_CONTRACT_TYPE,
        "minimum_length": CASE_NARRATIVE_MINIMUM_LENGTH,
        "maximum_length": CASE_NARRATIVE_MAXIMUM_LENGTH,
        "minimum_case_anchor_mentions": 1,
        "anchors": anchors,
    }


def case_anchor_terms(
    contract: object,
    *,
    profile_revision_ids: Iterable[str] | None = None,
    evidence_record_ids: Iterable[str] | None = None,
) -> list[str]:
    """Resolve terms allowed by the exact cited profile and evidence records."""

    if not isinstance(contract, Mapping):
        return []
    selected = (
        {str(value) for value in profile_revision_ids}
        if profile_revision_ids is not None
        else None
    )
    selected_evidence = (
        {str(value) for value in evidence_record_ids}
        if evidence_record_ids is not None
        else None
    )
    scope_terms: list[str] = []
    cited_terms: list[str] = []
    for anchor in contract.get("anchors") or []:
        if not isinstance(anchor, Mapping):
            continue
        text = anchor.get("text")
        if not isinstance(text, str) or not text:
            continue
        revision_id = anchor.get("profile_revision_id")
        if (
            revision_id is not None
            and selected is not None
            and str(revision_id) not in selected
        ):
            continue
        evidence_id = anchor.get("evidence_record_id")
        if (
            evidence_id is not None
            and selected_evidence is not None
            and str(evidence_id) not in selected_evidence
        ):
            continue
        if revision_id is not None or evidence_id is not None:
            cited_terms.append(text)
        else:
            scope_terms.append(text)
    # With typed references, prose must name a term carried by one of those
    # exact records. No free-form patient or source prose is used as fallback.
    if selected is not None or selected_evidence is not None:
        terms = cited_terms or scope_terms
    else:
        terms = [*cited_terms, *scope_terms]
    return list(dict.fromkeys(terms))


def case_narrative_schema_metadata(contract: object) -> JsonObject:
    """Return a defensive copy suitable for a public tool/result contract."""

    if not isinstance(contract, Mapping):
        return {
            "type": CASE_NARRATIVE_CONTRACT_TYPE,
            "minimum_length": CASE_NARRATIVE_MINIMUM_LENGTH,
            "maximum_length": CASE_NARRATIVE_MAXIMUM_LENGTH,
            "minimum_case_anchor_mentions": 1,
            "anchors": [],
        }
    return {
        "type": str(contract.get("type") or CASE_NARRATIVE_CONTRACT_TYPE),
        "minimum_length": int(
            contract.get("minimum_length") or CASE_NARRATIVE_MINIMUM_LENGTH
        ),
        "maximum_length": int(
            contract.get("maximum_length") or CASE_NARRATIVE_MAXIMUM_LENGTH
        ),
        "minimum_case_anchor_mentions": int(
            contract.get("minimum_case_anchor_mentions") or 1
        ),
        "anchors": [
            dict(anchor)
            for anchor in contract.get("anchors") or []
            if isinstance(anchor, Mapping)
        ],
    }


def _eligible_case_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    term = " ".join(value.strip().split())
    if (
        len(term) < 2
        or len(term) > 160
        or _SIMPLE_CASE_TERM.fullmatch(term) is None
        or _UNSAFE_CASE_TERM.search(term)
        or _INSTRUCTION_OR_ASSERTION_TERM.search(term)
    ):
        return None
    return term


def _variant_case_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    term = " ".join(value.strip().split())
    if any(
        pattern.fullmatch(term) is not None
        for pattern in (
            _NAMED_VARIANT_IDENTIFIER,
            _COORDINATE_VARIANT_IDENTIFIER,
        )
    ):
        return term
    return None


def _gene_case_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    term = value.strip()
    return term if _GENE_SYMBOL.fullmatch(term) is not None else None


def _protein_substitution_case_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    term = value.strip().upper()
    return (
        term
        if _PROTEIN_SUBSTITUTION_IDENTIFIER.fullmatch(term) is not None
        and term[0] != term[-1]
        else None
    )


def _profile_case_term(value: object) -> str | None:
    """Return one approved, label-shaped profile term as an opaque anchor.

    Treatment and medication words are valid profile labels. They remain
    ineligible when the label resembles an instruction, diagnosis assertion,
    or agent-control text; the surrounding narrative is validated separately.
    """

    if not isinstance(value, str):
        return None
    term = " ".join(value.strip().split())
    if (
        len(term) < 2
        or len(term) > 160
        or _SIMPLE_CASE_TERM.fullmatch(term) is None
        or _UNSAFE_PROFILE_CASE_TERM.search(term)
        or _INSTRUCTION_OR_ASSERTION_TERM.search(term)
    ):
        return None
    return term


def _typed_evidence_case_terms(value: object) -> list[str]:
    """Read only explicitly typed entity fields, never titles or source prose."""

    terms: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            field = str(key)
            if field in _EVIDENCE_VARIANT_TERM_FIELDS:
                values = (
                    nested
                    if isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes, bytearray))
                    else (nested,)
                )
                terms.extend(
                    term
                    for item in values
                    if (term := _variant_case_term(item)) is not None
                )
            elif field in _EVIDENCE_GENE_TERM_FIELDS:
                values = (
                    nested
                    if isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes, bytearray))
                    else (nested,)
                )
                terms.extend(
                    term
                    for item in values
                    if (term := _gene_case_term(item)) is not None
                )
            elif field in _EVIDENCE_PROTEIN_SUBSTITUTION_TERM_FIELDS:
                values = (
                    nested
                    if isinstance(nested, Sequence)
                    and not isinstance(nested, (str, bytes, bytearray))
                    else (nested,)
                )
                terms.extend(
                    term
                    for item in values
                    if (term := _protein_substitution_case_term(item)) is not None
                )
            if isinstance(nested, (Mapping, list, tuple)):
                terms.extend(_typed_evidence_case_terms(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            if isinstance(nested, (Mapping, list, tuple)):
                terms.extend(_typed_evidence_case_terms(nested))
    return list(dict.fromkeys(terms))


__all__ = [
    "CASE_NARRATIVE_CONTRACT_TYPE",
    "CASE_NARRATIVE_MAXIMUM_LENGTH",
    "CASE_NARRATIVE_MINIMUM_LENGTH",
    "GAP_KINDS",
    "build_case_narrative_contract",
    "case_anchor_terms",
    "case_narrative_schema_metadata",
]
