from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

GENE_IDENTIFICATION_SCHEMA_VERSION = "genomi-gene-evidence-comparison-v1"
TRAIT_GENE_RECORDS_SCHEMA_VERSION = "genomi-trait-gene-records-v1"
OPENTARGETS_GRAPHQL_API_URL = "https://api.platform.opentargets.org/api/v4/graphql"
OPENTARGETS_TRAIT_TARGET_LIMIT = 100

GWAS_PRIOR = "gwas_catalog_association"
LOCUS_TO_GENE_PRIOR = "locus_to_gene_prioritization"
DRUG_TARGET_PRIOR = "drug_target_mechanism"
PHENOTYPE_PRIOR = "expert_phenotype_annotation"
STRONG_LOCUS_TO_GENE_TERMS = (
    "locus-to-gene",
    "locus to gene",
    "variant-to-gene",
    "variant to gene",
    "v2g",
    "l2g",
    "colocalization",
    "colocalisation",
    "eqtl",
    "sqtl",
    "qtl",
    "fine-mapping",
    "finemapping",
    "credible set",
    "posterior inclusion probability",
    "posterior probability",
)
WEAK_LOCUS_NEIGHBOR_TERMS = (
    "nearest gene",
    "mapped gene",
    "nearby gene",
    "same locus",
    "risk locus",
    "trait-associated locus",
    "associated locus",
)
CAUSAL_GENE_CONTEXT_TERMS = (
    "causal gene",
    "causative gene",
    "effector gene",
    "likely causal",
    "putative causal",
    "causal at",
    "causal within",
    "causal for",
    "gene-at-locus",
    "gene at locus",
    "target gene",
    "driver gene",
)
LOCUS_GENE_CONTEXT_TERMS = (
    "within a locus",
    "within the locus",
    "within this locus",
    "at a locus",
    "at the locus",
    "at this locus",
    "trait-associated locus",
    "associated locus",
    "risk locus",
)
EXPLICIT_GWAS_GENE_FIELD_TERMS = (
    "gwas catalog reported gene",
    "gwas catalog mapped gene",
    "reported_gene",
    "reported gene",
    "reported genes",
    "mapped_gene",
    "mapped gene",
    "mapped genes",
    "source gene field",
    "source gene-field",
    "gene field",
    "gene-field",
)
TRAIT_CAUSAL_DIRECT_TERMS = (
    "causal gene",
    "causative gene",
    "effector gene",
    "driver gene",
    "canonical gene",
    "canonical causal",
    "mechanism",
    "mechanistic",
    "therapeutic target",
    "drug target",
    "genetic target",
    "target validation",
    "target-disease",
    "target disease",
    "loss of function protects",
    "gain of function",
    "mendelian randomization",
    "mendelian randomisation",
)
TRAIT_CAUSAL_DIRECT_SOURCES = (
    "chembl",
    "drugbank",
    "pharmaproject",
    "pharma project",
    "opentargets genetics",
    "open targets genetics",
    "opentargets platform",
    "open targets platform",
    "genecards",
    "malacards",
    "omim",
    "orphanet",
    "cliningen",
    "clingen",
    "genc c",
    "gencc",
    "ncbi gene",
    "pubmed",
)
TRAIT_CAUSAL_ASSOCIATION_ONLY_TERMS = (
    "gwas-catalog",
    "gwas catalog",
    "mapped gene",
    "mapped_gene",
    "reported gene",
    "reported_gene",
    "nearest gene",
    "association",
    "associated locus",
    "risk locus",
    "trait-associated locus",
)

EVIDENCE_PRIORS: dict[str, dict[str, str]] = {
    GWAS_PRIOR: {
        "component": "gwas_catalog",
        "title": "GWAS Catalog trait-association evidence",
    },
    LOCUS_TO_GENE_PRIOR: {
        "component": "locus_to_gene",
        "title": "locus-to-gene, variant-to-gene, fine-mapping, colocalization, or eQTL evidence",
    },
    DRUG_TARGET_PRIOR: {
        "component": "drug_target",
        "title": "direct drug-target or mechanism evidence",
    },
    PHENOTYPE_PRIOR: {
        "component": "phenotype",
        "title": "expert phenotype, HPO, or rare-disease annotation evidence",
    },
}

def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _dedupe(values: Iterable[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _meaningful_tokens(text: str) -> list[str]:
    stopwords = {"and", "or", "the", "a", "an", "of", "for", "to", "in", "with", "trait", "phenotype", "risk", "locus"}
    tokens: list[str] = []
    for token in text.casefold().replace("-", " ").replace("_", " ").split():
        stripped = "".join(ch for ch in token if ch.isalnum())
        if len(stripped) < 3 or stripped in stopwords:
            continue
        tokens.append(stripped)
    return _dedupe(tokens)


def _normalize_genes(genes: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for gene in genes:
        value = str(gene or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def _dedupe_by_key(records: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        key = tuple(_clean_text(record.get(field)).casefold() for field in fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _dedupe_dicts(records: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        key = tuple(_clean_text(record.get(field)).casefold() for field in fields)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _combined_source_records(*record_sets: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record_set in record_sets:
        if record_set is None:
            continue
        records.extend(record for record in record_set if isinstance(record, dict))
    return records


def _record_gene_values(record: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("gene", "genes", "candidate", "candidate_gene", "target_gene", "symbol", "gene_symbol", "scored_gene"):
        raw = record.get(key)
        if isinstance(raw, list):
            values.extend(raw)
        elif raw:
            values.append(raw)
    verified = record.get("verified_fields") if isinstance(record.get("verified_fields"), dict) else {}
    raw_verified = verified.get("genes")
    if isinstance(raw_verified, list):
        values.extend(raw_verified)
    elif raw_verified:
        values.append(raw_verified)
    return values


def _iterable_len(value: Iterable[Any] | None) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def _finding_text_from_record(record: dict[str, Any]) -> Any:
    finding = record.get("finding")
    if isinstance(finding, dict):
        return finding.get("text") or finding.get("summary")
    return finding or record.get("summary") or record.get("description")


def _record_count(result: dict[str, Any]) -> int:
    for key in ("association_records", "source_records"):
        records = result.get(key)
        if isinstance(records, list):
            return len(records)
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    for key in ("association_record_count", "source_record_count", "record_count"):
        if summary.get(key) is not None:
            return int(summary[key])
    return 0


def _candidate_records_found(result: dict[str, Any]) -> int:
    matrix = result.get("candidate_matrix") if isinstance(result.get("candidate_matrix"), list) else []
    return sum(1 for row in matrix if isinstance(row, dict) and row.get("rank") is not None)


def _coverage_note(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    if status == "source_unavailable":
        return "source unavailable"
    if _candidate_records_found(result) == 0:
        return "no candidate records found"
    return "candidate evidence found"


def _strip_large_top_level(result: dict[str, Any]) -> dict[str, Any]:
    omitted = {"evidence_view", "candidate_matrix", "source_records", "association_records"}
    return {key: value for key, value in result.items() if key not in omitted}


def _source_review_plan(phenotype_text: str, drug_context: dict[str, str]) -> dict[str, Any]:
    source_order = ["HPO, OMIM, Orphanet, ClinGen, or GenCC for rare-disease phenotype matching"]
    if phenotype_text:
        source_order.append("GWAS Catalog for public trait association")
    if any(drug_context.values()):
        source_order.append("ChEMBL, DrugBank, or PharmaProjects for direct target evidence")
    return {
        "safe_external_targets": ["phenotype terms", "HPO IDs", "candidate genes", "drug or drug class when supplied"],
        "source_order": source_order,
        "write_back_rule": "Record narrow reviewed source findings before treating a candidate as causal.",
    }


def _fetch_opentargets_graphql(api_url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "genomi/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise ValueError(str(payload["errors"]))
    return payload
