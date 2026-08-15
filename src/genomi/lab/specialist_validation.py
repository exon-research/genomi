"""Deterministic release validation for de-identified specialist briefs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .models import JsonObject, required_text
from .specialist_policies import EXPECTED_CONNECTORS, policy_manifest


OUTBOUND_BRIEF_FIELDS = frozenset(
    {
        "specialist_role",
        "execution_policy",
        "research_question",
        "public_concepts",
        "abstract_event_relations",
        "public_evidence",
        "allowed_tools",
        "privacy_constraints",
    }
)
PUBLIC_CONCEPT_FIELDS = frozenset({"type", "identifier", "label", "reference_sequence"})
ABSTRACT_RELATION_FIELDS = frozenset({"event_class_a", "relation", "event_class_b"})
PUBLIC_EVIDENCE_FIELDS = frozenset(
    {"source", "title", "uri", "summary", "doi", "pmid", "accession"}
)
PRIVACY_CONSTRAINTS = (
    "Use only the de-identified public research question in this brief.",
    "Do not infer or request patient identity, records, genome, dates, or case context.",
    "Return general evidence, uncertainty, alternatives, and information gaps only.",
    "Do not recommend patient treatment or testing.",
)

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()/-]{7,}\d)(?!\w)")
_SSN_OR_MRN = re.compile(r"\b(?:SSN|MRN|medical\s+record\s+(?:number|id))\b", re.I)
_ISO_DATE = re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b")
_PROSE_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+(?:19|20)\d{2}\b",
    re.I,
)
_PATH = re.compile(
    r"(?:^|[\s'\"])(?:/(?:Users|home|private|tmp|var|Volumes)/[^\s'\"]+|"
    r"[A-Za-z]:\\[^\s'\"]+|~/(?:[^\s'\"]+))"
)
_VCF = re.compile(
    r"(?:#CHROM\b|\bVCFv4\.\d\b|\b(?:chr)?(?:[1-9]|1\d|2[0-2]|X|Y|MT)"
    r"\s+\d+\s+(?:\.|rs\d+)\s+[ACGTN]+\s+[ACGTN,<*>]+)",
    re.I,
)
_GENOTYPE = re.compile(r"\b(?:0|1|2)[/|](?:0|1|2)\b")
_NUCLEOTIDE_SEQUENCE = re.compile(r"\b[ACGTN]{30,}\b", re.I)
_INTERNAL_IDENTIFIER = re.compile(
    r"\b(?:investigation|cycle|workspace|profile|patient-molecular-snapshot|"
    r"evidence-snapshot|observation-revision|consent|disclosure|specialist-brief|"
    r"specialist-assignment|source-artifact|specimen|assay|agi)-[A-Za-z0-9._-]+\b",
    re.I,
)
_AGI_TERMS = re.compile(
    r"\b(?:AGI|Active Genome Index|agi_snapshot_id|agi_id|genomi(?:lab)?\s+session)\b",
    re.I,
)
_PATIENT_LINKAGE = re.compile(
    r"\b(?:this|the|our)\s+(?:patient|subject|proband|case)\b|"
    r"\b(?:patient|subject|proband)(?:'s|’s)\b|"
    r"\b(?:his|her|their|my)\s+(?:genome|records?|diagnosis|variant|medications?|history)\b",
    re.I,
)
_WORDS = re.compile(r"[a-z0-9]+", re.I)


def build_outbound_specialist_brief(
    *,
    specialist_role: object,
    execution_policy: object,
    research_question: object,
    public_concepts: object,
    abstract_relations: object,
    public_evidence: object,
) -> JsonObject:
    """Build the only outbound shape accepted by the release validator."""

    policy = _resolved_policy(execution_policy)
    outbound: JsonObject = {
        "specialist_role": required_text(specialist_role, "specialist_role", 300),
        "execution_policy": policy["id"],
        "research_question": required_text(
            research_question, "research_question", 4_000
        ),
        "public_concepts": _object_array(public_concepts, "public_concepts"),
        "abstract_event_relations": _object_array(
            abstract_relations, "abstract_relations"
        ),
        "public_evidence": _object_array(public_evidence, "public_evidence"),
        "allowed_tools": list(policy["allowed_connectors"]),
        "privacy_constraints": list(PRIVACY_CONSTRAINTS),
    }
    validate_specialist_brief(outbound, policy=policy)
    return outbound


def validate_specialist_brief(
    outbound: object,
    *,
    policy: Mapping[str, object] | object,
    forbidden_texts: Iterable[object] = (),
) -> None:
    """Reject a specialist payload unless it proves the public-only contract.

    ``forbidden_texts`` should include user identifiers, original patient
    wording, and report text available to the Main Orchestrator.  Exact term
    and eight-word overlap checks make accidental verbatim disclosure a
    deterministic server error rather than a prompt instruction.
    """

    resolved_policy = _resolved_policy(policy)
    if not isinstance(outbound, Mapping):
        raise ValueError("outbound specialist brief must be an object")
    _exact_fields(outbound, OUTBOUND_BRIEF_FIELDS, "outbound specialist brief")
    if outbound.get("execution_policy") != resolved_policy["id"]:
        raise ValueError("outbound execution_policy does not match the selected policy")
    if tuple(outbound.get("allowed_tools") or ()) != tuple(
        resolved_policy["allowed_connectors"]
    ):
        raise ValueError("outbound allowed_tools do not match the selected policy")
    if tuple(outbound.get("privacy_constraints") or ()) != PRIVACY_CONSTRAINTS:
        raise ValueError("outbound privacy_constraints must use the fixed contract")

    required_text(outbound.get("specialist_role"), "specialist_role", 300)
    required_text(outbound.get("research_question"), "research_question", 4_000)
    concepts = _object_array(outbound.get("public_concepts"), "public_concepts")
    relations = _object_array(outbound.get("abstract_event_relations"), "abstract_event_relations")
    evidence = _object_array(outbound.get("public_evidence"), "public_evidence")
    for index, item in enumerate(concepts):
        _allowed_fields(item, PUBLIC_CONCEPT_FIELDS, f"public_concepts[{index}]")
        required_text(item.get("type"), f"public_concepts[{index}].type", 100)
        required_text(
            item.get("identifier"), f"public_concepts[{index}].identifier", 500
        )
        sequence = item.get("reference_sequence")
        if sequence not in (None, ""):
            if "public_reference_sequence" not in resolved_policy["allowed_input_classes"]:
                raise ValueError("the selected execution policy forbids reference_sequence")
            sequence_text = required_text(
                sequence, f"public_concepts[{index}].reference_sequence", 5_000
            )
            if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]{20,5000}", sequence_text):
                raise ValueError("reference_sequence must be a public protein sequence")
    for index, item in enumerate(relations):
        _exact_fields(item, ABSTRACT_RELATION_FIELDS, f"abstract_event_relations[{index}]")
        for field in ABSTRACT_RELATION_FIELDS:
            required_text(item.get(field), f"abstract_event_relations[{index}].{field}", 500)
    for index, item in enumerate(evidence):
        _allowed_fields(item, PUBLIC_EVIDENCE_FIELDS, f"public_evidence[{index}]")
        if not any(item.get(field) for field in ("title", "uri", "doi", "pmid", "accession")):
            raise ValueError(f"public_evidence[{index}] requires a public source locator")

    forbidden = [str(item).strip() for item in forbidden_texts if str(item).strip()]
    for path, text in _strings(outbound):
        if path.endswith("reference_sequence"):
            continue
        _validate_released_text(path, text, forbidden)


def _validate_released_text(path: str, text: str, forbidden: list[str]) -> None:
    checks = (
        (_EMAIL, "direct email identifier"),
        (_PHONE, "direct phone identifier"),
        (_SSN_OR_MRN, "direct record identifier"),
        (_ISO_DATE, "exact date"),
        (_PROSE_DATE, "exact date"),
        (_PATH, "filesystem path"),
        (_VCF, "VCF-shaped data"),
        (_GENOTYPE, "genotype-shaped data"),
        (_NUCLEOTIDE_SEQUENCE, "raw nucleotide sequence"),
        (_INTERNAL_IDENTIFIER, "internal record identifier"),
        (_AGI_TERMS, "Active Genome Index terminology"),
        (_PATIENT_LINKAGE, "patient-linked phrasing"),
    )
    for pattern, label in checks:
        if pattern.search(text):
            raise ValueError(f"{path} contains {label}")
    normalized = " ".join(_WORDS.findall(text.lower()))
    if not normalized:
        return
    for raw in forbidden:
        candidate = " ".join(_WORDS.findall(raw.lower()))
        if not candidate:
            continue
        if len(candidate) >= 3 and candidate in normalized:
            raise ValueError(f"{path} contains stored private wording")
        private_windows = _word_windows(candidate, 8)
        if private_windows and private_windows & _word_windows(normalized, 8):
            raise ValueError(f"{path} overlaps stored patient or report text")


def _strings(value: object, path: str = "outbound") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _word_windows(text: str, size: int) -> set[str]:
    words = text.split()
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


def _resolved_policy(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        identifier = value.get("id")
    else:
        identifier = str(value)
    if identifier not in EXPECTED_CONNECTORS:
        raise ValueError(
            "execution_policy must be one of: "
            + ", ".join(sorted(EXPECTED_CONNECTORS))
        )
    manifest = policy_manifest()
    profiles = manifest.get("profiles") or []
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == identifier:
            return dict(profile)
    raise ValueError("selected specialist execution policy is unavailable")


def _object_array(value: object, field: str) -> list[JsonObject]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be an array of objects")
    return [dict(item) for item in value]


def _exact_fields(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    actual = set(value)
    if actual != set(allowed):
        raise ValueError(
            f"{field} fields must be exactly {sorted(allowed)}; got {sorted(actual)}"
        )


def _allowed_fields(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"{field} contains unsupported fields: {sorted(unknown)}")


__all__ = [
    "ABSTRACT_RELATION_FIELDS",
    "OUTBOUND_BRIEF_FIELDS",
    "PRIVACY_CONSTRAINTS",
    "PUBLIC_CONCEPT_FIELDS",
    "PUBLIC_EVIDENCE_FIELDS",
    "build_outbound_specialist_brief",
    "validate_specialist_brief",
]
