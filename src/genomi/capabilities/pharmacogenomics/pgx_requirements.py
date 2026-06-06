from __future__ import annotations

import json
from importlib import resources as importlib_resources
from typing import Any

from .pharmcat._common import PHARMCAT_FAQ_URL, PHARMCAT_GENES_DRUGS_URL

JsonObject = dict[str, Any]
PGX_GENE_REQUIREMENTS_RESOURCE = ("data", "gene_requirements.json")
_GENE_REQUIREMENTS_CACHE: dict[str, Any] | None = None


def gene_requirements_catalog() -> JsonObject:
    global _GENE_REQUIREMENTS_CACHE
    if _GENE_REQUIREMENTS_CACHE is None:
        resource = importlib_resources.files(__package__).joinpath(*PGX_GENE_REQUIREMENTS_RESOURCE)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("named_allele_matcher_genes"), list)
            or not isinstance(payload.get("outside_call_genes"), dict)
            or not isinstance(payload.get("special_gene_requirements"), dict)
        ):
            raise RuntimeError("PGx gene requirement data must define gene requirement groups")
        _GENE_REQUIREMENTS_CACHE = payload
    return dict(_GENE_REQUIREMENTS_CACHE)


NAMED_ALLELE_MATCHER_GENES = set(gene_requirements_catalog()["named_allele_matcher_genes"])
OUTSIDE_CALL_GENES: dict[str, JsonObject] = dict(gene_requirements_catalog()["outside_call_genes"])
SPECIAL_GENE_REQUIREMENTS: dict[str, JsonObject] = dict(gene_requirements_catalog()["special_gene_requirements"])


def pharmacogene_requirements(
    *,
    gene: str | None = None,
) -> JsonObject:
    selected_gene = _normalize_gene(gene)
    records = [_record_for_gene(selected_gene)] if selected_gene else [_record_for_gene(item) for item in sorted(_all_genes())]
    payload: JsonObject = {
        "status": "completed",
        "query": {"gene": selected_gene},
        "records": records,
        "summary": {
            "record_count": len(records),
            "named_allele_matcher_gene_count": len(NAMED_ALLELE_MATCHER_GENES),
            "outside_call_gene_count": len(OUTSIDE_CALL_GENES),
        },
        "source_documents": _source_documents(),
    }
    return payload


def _record_for_gene(gene: str | None) -> JsonObject:
    if not gene:
        return {
            "gene": None,
            "category": "needs_gene",
            "sample_evidence_requirements": ["Select a pharmacogene before applying gene-specific PGx sample requirements."],
            "candidate_tools": ["pharmacogenomics.review_medication", "pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb"],
            "source_urls": [],
        }
    if gene in OUTSIDE_CALL_GENES:
        record = OUTSIDE_CALL_GENES[gene]
        return {
            "gene": gene,
            "category": record["category"],
            "sample_evidence_requirements": record["requirements"],
            "preferred_evidence": record["preferred_evidence"],
            "candidate_callers": record["candidate_callers"],
            "candidate_tools": ["pharmacogenomics.prepare_outside_call_tsv", "pharmacogenomics.validate_outside_call_tsv", "pharmacogenomics.preflight_pharmcat", "pharmacogenomics.check_pharmcat", "pharmacogenomics.run_pharmcat", "pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb"],
            "source_urls": record["source_urls"],
        }
    if gene in NAMED_ALLELE_MATCHER_GENES:
        record = {
            "gene": gene,
            "category": "pharmcat_named_allele_matcher",
            "sample_evidence_requirements": [
                "Active Genome Index suitable for PharmCAT input requirements.",
                "Genotype fields at PharmCAT allele-defining positions.",
                "PharmCAT output artifacts plus missing PGx position review for broad PGx synthesis.",
            ],
            "preferred_evidence": ["PharmCAT report JSON or HTML", "calls-only TSV", "missing PGx position summary"],
            "candidate_tools": ["pharmacogenomics.preflight_pharmcat", "pharmacogenomics.check_pharmcat", "pharmacogenomics.run_pharmcat", "pharmacogenomics.review_medication"],
            "source_urls": [PHARMCAT_GENES_DRUGS_URL, PHARMCAT_FAQ_URL],
        }
        if gene in SPECIAL_GENE_REQUIREMENTS:
            special = SPECIAL_GENE_REQUIREMENTS[gene]
            record["category"] = special["category"]
            record["sample_evidence_requirements"] = special["requirements"]
            record["source_urls"] = sorted(set(record["source_urls"]) | set(special["source_urls"]))
        return record
    return {
        "gene": gene,
        "category": "not_in_catalog",
        "sample_evidence_requirements": [
            "Use public source evidence to identify relevant variants, haplotypes, diplotypes, phenotypes, or assays.",
            "Use Active Genome Index lookup only for selected public targets.",
            "Use source citations before making a PGx interpretation.",
        ],
        "preferred_evidence": ["ClinPGx source evidence", "PGxDB association evidence", "targeted Active Genome Index lookup"],
        "candidate_tools": ["pharmacogenomics.review_medication", "pharmacogenomics.fetch_clinpgx", "pharmacogenomics.fetch_pgxdb", "variant.resolve"],
        "source_urls": [],
    }


def _source_documents() -> list[JsonObject]:
    return list(gene_requirements_catalog().get("source_documents") or [])


def _all_genes() -> set[str]:
    return set(NAMED_ALLELE_MATCHER_GENES) | set(OUTSIDE_CALL_GENES) | set(SPECIAL_GENE_REQUIREMENTS)


def _normalize_gene(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned.upper() if cleaned else None
