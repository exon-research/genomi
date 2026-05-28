from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ....evidence import envelope as _env
from ....evidence import (
    extract_clinvar_candidates,
    fetch_gene_evidence,
    query_research_findings,
    search_research_findings,
)
from ....evidence.candidate_evidence import (
    AGENT_REASONING_ONLY,
    DIRECT_SOURCE_MATCH,
    LITERATURE_PLAUSIBILITY,
    NEARBY_TRAIT_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    SAME_GENE_OR_LOCUS,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    empty_lanes,
    evidence_view,
    lane,
)
from ....evidence.sources import evidence_source_catalog
from ....evidence.task_profiles import RARE_DISEASE_CANCER_RISK_INVESTIGATION
from ....runtime.external import utc_now
from ....runtime.handoff import evidence_context

RISK_INVESTIGATION_SCHEMA_VERSION = "genomi-risk-investigation-v1"
RISK_INVESTIGATION_TYPES = ("auto", "rare_disease", "cancer_risk")

CANCER_TERMS = (
    "cancer",
    "tumor",
    "tumour",
    "oncology",
    "oncogene",
    "tumor suppressor",
    "tumour suppressor",
    "carcinoma",
    "sarcoma",
    "leukemia",
    "lymphoma",
    "melanoma",
    "brca",
    "hereditary cancer",
)
RARE_DISEASE_TERMS = (
    "rare disease",
    "orphan",
    "syndrome",
    "inheritance",
    "monogenic",
    "mendelian",
    "phenotype",
    "hpo",
)
RARE_DISEASE_SOURCE_IDS = (
    "clinvar",
    "gnomad",
    "clingen_gene_validity",
    "gencc",
    "genereviews",
    "genecards",
    "malacards",
    "pubmed_or_primary_literature",
)
CANCER_RISK_SOURCE_IDS = (
    "clinvar",
    "gnomad",
    "clingen_gene_validity",
    "gencc",
    "genereviews",
    "genecards",
    "malacards",
    "nci_cancer_genetics",
    "cosmic_cancer_gene_census",
    "pubmed_or_primary_literature",
)


def _normalize_genes(gene: str | None, genes: Iterable[str] | None) -> list[str]:
    values: list[str] = []
    for item in ([gene] if gene else []):
        values.append(item)
    if genes is not None:
        values.extend(str(item) for item in genes)
    normalized: list[str] = []
    for item in values:
        value = str(item or "").strip().upper()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _clean_text(value: str | None) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _short_search_query(query: str) -> str:
    tokens = [token for token in query.split() if token]
    return " ".join(tokens[:6])


def _safe_external_targets(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "genes": target.get("genes") or [],
        "condition": target.get("condition"),
        "topic": target.get("topic"),
        "question_without_private_context": target.get("question"),
    }


def _first_review_target(target: dict[str, Any]) -> str | None:
    genes = target.get("genes") or []
    if genes:
        return f"gene:{genes[0]}"
    if target.get("condition"):
        return f"condition:{target['condition']}"
    if target.get("topic"):
        return f"topic:{target['topic']}"
    return None


def _variant_candidate_id(variant: dict[str, Any]) -> str:
    return "variant:{chrom}-{pos}-{ref}-{alt}".format(
        chrom=variant.get("chrom"),
        pos=variant.get("pos"),
        ref=variant.get("ref"),
        alt=variant.get("alt"),
    )


def _record_template(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": target,
        "source": {
            "title": "",
            "url": "",
            "type": "",
            "accessed_at": utc_now(),
        },
        "searched_query": "",
        "finding": {
            "type": "",
            "text": "",
            "summary": "",
        },
        "captured_by": "agent",
    }


def _dedupe(values: Iterable[str]) -> list[str]:
    output = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output
