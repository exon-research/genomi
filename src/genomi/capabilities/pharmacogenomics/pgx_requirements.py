from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from importlib import resources as importlib_resources
from typing import Any

JsonObject = dict[str, Any]


PHARMCAT_GENES_DRUGS_URL = "https://pharmcat.clinpgx.org/Genes-Drugs/"
PHARMCAT_CYP2D6_URL = "https://pharmcat.clinpgx.org/using/Calling-CYP2D6/"
PHARMCAT_OUTSIDE_CALL_URL = "https://pharmcat.clinpgx.org/using/Outside-Call-Format/"
PHARMCAT_FAQ_URL = "https://pharmcat.clinpgx.org/faqs/"
PGX_GENE_REQUIREMENTS_SCHEMA = "genomi-pgx-gene-requirements-catalog-v1"
PGX_GENE_REQUIREMENTS_RESOURCE = ("data", "gene_requirements.json")
PHARMCAT_NAMED_MATCHER_SECTION = "genes-pharmcat-will-attempt-to-match"
PHARMCAT_OUTSIDE_CALLER_SECTION = "genes-handled-by-outside-callers"
_GENE_REQUIREMENTS_CACHE: dict[str, Any] | None = None


def gene_requirements_catalog() -> JsonObject:
    global _GENE_REQUIREMENTS_CACHE
    if _GENE_REQUIREMENTS_CACHE is None:
        resource = importlib_resources.files(__package__).joinpath(*PGX_GENE_REQUIREMENTS_RESOURCE)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if payload.get("schema") != PGX_GENE_REQUIREMENTS_SCHEMA:
            raise RuntimeError("PGx gene requirement data has an unsupported schema")
        _GENE_REQUIREMENTS_CACHE = payload
    return dict(_GENE_REQUIREMENTS_CACHE)


NAMED_ALLELE_MATCHER_GENES = set(gene_requirements_catalog()["named_allele_matcher_genes"])
OUTSIDE_CALL_GENES: dict[str, JsonObject] = dict(gene_requirements_catalog()["outside_call_genes"])
SPECIAL_GENE_REQUIREMENTS: dict[str, JsonObject] = dict(gene_requirements_catalog()["special_gene_requirements"])


def pharmacogene_requirements(
    *,
    gene: str | None = None,
    refresh_sources: bool = False,
    pharmcat_genes_drugs_url: str | None = None,
    fetch_text: Any | None = None,
) -> JsonObject:
    selected_gene = _normalize_gene(gene)
    records = [_record_for_gene(selected_gene)] if selected_gene else [_record_for_gene(item) for item in sorted(_all_genes())]
    payload: JsonObject = {
        "schema": "genomi-pgx-gene-requirements-v1",
        "status": "completed",
        "query": {
            "gene": selected_gene,
            "refresh_sources": bool(refresh_sources),
            "pharmcat_genes_drugs_url": _clean_url(pharmcat_genes_drugs_url) or PHARMCAT_GENES_DRUGS_URL,
        },
        "records": records,
        "summary": {
            "record_count": len(records),
            "named_allele_matcher_gene_count": len(NAMED_ALLELE_MATCHER_GENES),
            "outside_call_gene_count": len(OUTSIDE_CALL_GENES),
        },
        "source_documents": _source_documents(),
    }
    if refresh_sources:
        snapshot = _pharmcat_gene_source_snapshot(
            _clean_url(pharmcat_genes_drugs_url) or PHARMCAT_GENES_DRUGS_URL,
            fetch_text=fetch_text,
        )
        payload["source_snapshot"] = snapshot
        if snapshot.get("status") == "completed":
            payload["catalog_comparison"] = _catalog_source_comparison(snapshot)
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


def _clean_url(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _pharmcat_gene_source_snapshot(url: str, *, fetch_text: Any | None = None) -> JsonObject:
    try:
        text = fetch_text(url) if fetch_text is not None else _fetch_text(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "status": "source_unavailable",
            "source_url": url,
            "error": str(exc),
        }
    named_genes = _extract_pharmcat_section_genes(text, PHARMCAT_NAMED_MATCHER_SECTION)
    outside_genes = _extract_pharmcat_section_genes(text, PHARMCAT_OUTSIDE_CALLER_SECTION)
    return {
        "status": "completed",
        "source_url": url,
        "source": "PharmCAT Genes & Drugs",
        "named_allele_matcher_genes": named_genes,
        "outside_call_genes": outside_genes,
        "summary": {
            "named_allele_matcher_gene_count": len(named_genes),
            "outside_call_gene_count": len(outside_genes),
        },
    }


def _extract_pharmcat_section_genes(text: str, section_id: str) -> list[str]:
    start_match = re.search(rf'<h3\s+id="{re.escape(section_id)}"', text, flags=re.IGNORECASE)
    if not start_match:
        return []
    next_heading = re.search(r"<h3\s+id=", text[start_match.end() :], flags=re.IGNORECASE)
    end = start_match.end() + next_heading.start() if next_heading else len(text)
    section = text[start_match.end() : end]
    genes: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a\s+href="/Phenotypes-List#[^"]+">([^<]+)</a>', section, flags=re.IGNORECASE):
        gene = _normalize_gene(html.unescape(match.group(1)))
        if gene and gene not in seen:
            seen.add(gene)
            genes.append(gene)
    return genes


def _catalog_source_comparison(snapshot: JsonObject) -> JsonObject:
    named_source = set(snapshot.get("named_allele_matcher_genes") or [])
    outside_source = set(snapshot.get("outside_call_genes") or [])
    return {
        "packaged_catalog_schema": PGX_GENE_REQUIREMENTS_SCHEMA,
        "source_url": snapshot.get("source_url"),
        "named_allele_matcher": {
            "source_not_in_packaged": sorted(named_source - NAMED_ALLELE_MATCHER_GENES),
            "packaged_not_in_source": sorted(NAMED_ALLELE_MATCHER_GENES - named_source),
        },
        "outside_call": {
            "source_not_in_packaged": sorted(outside_source - set(OUTSIDE_CALL_GENES)),
            "packaged_not_in_source": sorted(set(OUTSIDE_CALL_GENES) - outside_source),
        },
    }


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html, text/plain",
            "User-Agent": "Mozilla/5.0 (compatible; Genomi/0.1)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")
