from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .constants import (
    GWAS_CATALOG_SOURCE_URL,
    _LOW_INFORMATION_TRAIT_TOKENS,
    _TOKEN_RE,
    _TRAIT_TOKEN_ALIASES,
)


def _normalize_rsids(variants: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    rsids: list[str] = []
    for variant in variants:
        value = str(variant).strip()
        if not value:
            continue
        if value.lower().startswith("rs"):
            value = "rs" + value[2:]
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        rsids.append(value)
    return rsids


def _normalize_genes(genes: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for gene in genes:
        if isinstance(gene, dict):
            gene = gene.get("geneName") or gene.get("symbol") or gene.get("name")
        value = str(gene or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_gene(gene: Any) -> str:
    normalized = _normalize_genes([gene])
    return normalized[0] if normalized else ""


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _dedupe_text(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _embedded_list(response: dict[str, Any], name: str) -> list[dict[str, Any]]:
    embedded = response.get("_embedded") if isinstance(response.get("_embedded"), dict) else {}
    values = embedded.get(name)
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _risk_alleles(loci: Iterable[Any]) -> list[str]:
    alleles: list[str] = []
    for locus in loci:
        if not isinstance(locus, dict):
            continue
        for allele in locus.get("strongestRiskAlleles") or []:
            if isinstance(allele, dict) and allele.get("riskAlleleName"):
                alleles.append(str(allele["riskAlleleName"]))
    return sorted(set(alleles))


def _reported_genes(loci: Iterable[Any]) -> list[str]:
    genes: list[str] = []
    for locus in loci:
        if not isinstance(locus, dict):
            continue
        for gene in locus.get("authorReportedGenes") or []:
            if isinstance(gene, dict) and gene.get("geneName"):
                genes.append(str(gene["geneName"]).upper())
            elif isinstance(gene, str):
                genes.append(gene.upper())
    return sorted(set(genes))


def _mapped_genes(snps: Iterable[Any]) -> list[str]:
    genes: list[str] = []
    for snp in snps:
        if not isinstance(snp, dict):
            continue
        for context in snp.get("genomicContexts") or []:
            if isinstance(context, dict) and isinstance(context.get("gene"), dict) and context["gene"].get("geneName"):
                genes.append(str(context["gene"]["geneName"]).upper())
    return sorted(set(genes))


def _locations(snps: Iterable[Any]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for snp in snps:
        if not isinstance(snp, dict):
            continue
        for location in snp.get("locations") or []:
            if isinstance(location, dict):
                locations.append(
                    {
                        "chrom": location.get("chromosomeName"),
                        "pos": location.get("chromosomePosition"),
                        "region": (location.get("region") or {}).get("name") if isinstance(location.get("region"), dict) else None,
                    }
                )
    return locations


def _record_research_payload(rsid: str, trait: str, association_url: str | None, finding_text: str) -> dict[str, Any]:
    topic = " ".join(part for part in ["GWAS Catalog", trait, rsid] if part)
    return {
        "target": {
            "type": "topic",
            "topic": topic,
        },
        "source": {
            "title": "GWAS Catalog association",
            "url": association_url or GWAS_CATALOG_SOURCE_URL,
            "type": "association_database",
        },
        "finding": {
            "type": "gwas_association",
            "text": finding_text,
            "summary": finding_text,
        },
        "searched_query": topic,
        "captured_by": "genomi call gwas.compare_variant_associations",
    }


def _link_href(record: dict[str, Any], key: str) -> str | None:
    links = record.get("_links") if isinstance(record.get("_links"), dict) else {}
    link = links.get(key)
    if isinstance(link, dict) and link.get("href"):
        return str(link["href"]).replace("{?projection}", "")
    return None


def _best_pvalue(matches: Iterable[dict[str, Any]]) -> float | None:
    values = [_pvalue_sort_value(match.get("pvalue")) for match in matches]
    finite = [value for value in values if value != float("inf")]
    return min(finite) if finite else None


def _pvalue_sort_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _pvalue_from_parts(association: dict[str, Any]) -> float | None:
    mantissa = association.get("pvalueMantissa") or association.get("pValueMantissa") or association.get("pvalue_mantissa")
    exponent = association.get("pvalueExponent") or association.get("pValueExponent") or association.get("pvalue_exponent")
    try:
        return float(mantissa) * (10 ** int(exponent))
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _tokens(value: str) -> list[str]:
    return _TOKEN_RE.findall(value.casefold())


def _meaningful_tokens(value: str) -> list[str]:
    meaningful: list[str] = []
    for raw_token in _tokens(value):
        token = _TRAIT_TOKEN_ALIASES.get(raw_token, raw_token)
        if len(token) <= 1 or token.isnumeric() or token in _LOW_INFORMATION_TRAIT_TOKENS:
            continue
        meaningful.extend(_expanded_trait_token(token))
    return meaningful


def _expanded_trait_token(token: str) -> list[str]:
    if token.startswith("hydroxy") and len(token) > len("hydroxy") + 2:
        return ["hydroxy", token[len("hydroxy"):]]
    return [token]
