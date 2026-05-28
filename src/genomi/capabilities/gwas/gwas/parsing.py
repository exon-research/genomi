from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

from .constants import (
    _CAUSAL_GENE_REQUEST_TERMS,
    _EXPLICIT_GWAS_GENE_FIELD_TERMS,
    _LOCUS_GENE_REQUEST_TERMS,
)
from .phenotype_match import _association_traits, _best_phenotype_match
from .text_utils import (
    _as_list,
    _clean_text,
    _dedupe_text,
    _embedded_list,
    _link_href,
    _locations,
    _mapped_genes,
    _normalize_genes,
    _pvalue_from_parts,
    _record_research_payload,
    _reported_genes,
    _risk_alleles,
)


def _fetch_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "genomi/0.1"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt:
                raise
            time.sleep(0.5)
    return {}


def _generic_association_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    records = _embedded_list(response, "associations")
    if records:
        return records
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    associations = response.get("associations")
    if isinstance(associations, list):
        return [item for item in associations if isinstance(item, dict)]
    return []


def _generic_efo_trait_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    embedded = response.get("_embedded") if isinstance(response.get("_embedded"), dict) else {}
    for key in ("efo_traits", "efoTraitDtoes", "efo-traits"):
        values = embedded.get(key)
        if isinstance(values, list):
            return [value for value in values if isinstance(value, dict)]
    values = response.get("efo_traits")
    if isinstance(values, list):
        return [value for value in values if isinstance(value, dict)]
    return []


def _fetch_gwas_efo_traits(
    url: str,
    *,
    fetch: Callable[[str], dict[str, Any]],
    errors: list[dict[str, str]],
) -> list[dict[str, Any]]:
    try:
        response = fetch(url)
    except urllib.error.HTTPError as exc:
        errors.append({"url": url, "error": f"HTTP {exc.code}"})
        return []
    except urllib.error.URLError as exc:
        errors.append({"url": url, "error": str(exc.reason)})
        return []
    except TimeoutError as exc:
        errors.append({"url": url, "error": str(exc)})
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append({"url": url, "error": f"parse error: {exc}"})
        return []
    except OSError as exc:
        errors.append({"url": url, "error": f"I/O error: {exc}"})
        return []
    return _generic_efo_trait_records(response)


def _fetch_gwas_catalog_records(
    url: str,
    *,
    fetch: Callable[[str], dict[str, Any]],
    errors: list[dict[str, str]],
) -> list[dict[str, Any]]:
    try:
        response = fetch(url)
    except urllib.error.HTTPError as exc:
        errors.append({"url": url, "error": f"HTTP {exc.code}"})
        return []
    except urllib.error.URLError as exc:
        errors.append({"url": url, "error": str(exc.reason)})
        return []
    except TimeoutError as exc:
        errors.append({"url": url, "error": str(exc)})
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        errors.append({"url": url, "error": f"parse error: {exc}"})
        return []
    except OSError as exc:
        errors.append({"url": url, "error": f"I/O error: {exc}"})
        return []
    return _generic_association_records(response)


def _gene_association_record(
    record: dict[str, Any],
    phenotype: str,
    *,
    source_origin: str,
    phenotype_queries: Iterable[str] | None = None,
) -> dict[str, Any]:
    trait_texts = _gene_record_traits(record)
    match = _best_phenotype_match(phenotype_queries or [phenotype], trait_texts)
    reported_genes = _gene_reported_genes(record)
    mapped_genes = _gene_mapped_genes(record)
    named_genes = _gene_record_genes(record)
    genes = _normalize_genes([*reported_genes, *mapped_genes, *named_genes])
    pvalue = record.get("pvalue") or record.get("p_value") or record.get("pValue") or _pvalue_from_parts(record)
    association_url = _link_href(record, "self") or _link_href(record, "association") or record.get("association_url") or record.get("url")
    association_id = str(record.get("association_id") or record.get("id") or "").strip() or (str(association_url).rstrip("/").split("/")[-1] if association_url else None)
    return {
        "association_id": association_id,
        "association_url": association_url,
        "source_origin": source_origin,
        "pvalue": pvalue,
        "traits": trait_texts,
        "genes": genes,
        "reported_genes": reported_genes,
        "mapped_genes": mapped_genes,
        "source_gene_fields": {
            "reported_genes": reported_genes,
            "mapped_genes": mapped_genes,
            "all_named_genes": genes,
        },
        "study": _gene_record_study(record),
        "phenotype_match": match,
        "finding": _gene_finding_text(genes, trait_texts, pvalue),
    }


def _gene_record_traits(record: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        record.get("trait"),
        record.get("efo_trait"),
        record.get("efoTrait"),
        record.get("disease_trait"),
        record.get("diseaseTrait"),
    ]
    values.extend(_as_list(record.get("reported_trait")))
    values.extend(_as_list(record.get("reportedTrait")))
    study = record.get("study") if isinstance(record.get("study"), dict) else {}
    disease_trait = study.get("diseaseTrait") if isinstance(study.get("diseaseTrait"), dict) else {}
    values.append(disease_trait.get("trait"))
    values.extend(_association_traits(record))
    for key in ("efoTraits", "efo_traits", "bg_efo_traits", "traits"):
        raw = record.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    values.append(item.get("trait") or item.get("efo_trait") or item.get("name"))
                else:
                    values.append(item)
    return _dedupe_text(_clean_text(value) for value in values if _clean_text(value))


def _gene_record_genes(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("genes", "mapped_genes", "mappedGenes", "mapped_gene", "reported_genes", "reportedGenes", "reported_gene", "mappedGene", "reportedGene"):
        values.extend(_as_list(record.get(key)))
    values.extend(_reported_genes(record.get("loci") or []))
    values.extend(_mapped_genes(record.get("snps") or []))
    return _normalize_genes(values)


def _gene_reported_genes(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("reported_genes", "reportedGenes", "reported_gene", "reportedGene", "authorReportedGenes"):
        values.extend(_as_list(record.get(key)))
    values.extend(_reported_genes(record.get("loci") or []))
    return _normalize_genes(values)


def _gene_mapped_genes(record: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("mapped_genes", "mappedGenes", "mapped_gene", "mappedGene"):
        values.extend(_as_list(record.get(key)))
    values.extend(_mapped_genes(record.get("snps") or []))
    return _normalize_genes(values)


def _gene_record_study(record: dict[str, Any]) -> dict[str, Any]:
    study = record.get("study") if isinstance(record.get("study"), dict) else {}
    publication = study.get("publicationInfo") if isinstance(study.get("publicationInfo"), dict) else {}
    return {
        "accession": study.get("accessionId") or record.get("accession_id") or record.get("study_accession") or record.get("studyAccession"),
        "pubmed_id": publication.get("pubmedId") or record.get("pubmed_id") or record.get("pubmedId"),
        "title": publication.get("title") or record.get("title"),
    }


def _dedupe_gene_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str | None, tuple[str, ...], tuple[str, ...]]] = set()
    for record in records:
        key = (
            record.get("association_id"),
            tuple(record.get("genes") or []),
            tuple(record.get("traits") or []),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _causal_gene_task_text(task_text: str | None) -> bool:
    text = _clean_text(task_text)
    if not text:
        return False
    if any(term in text for term in _CAUSAL_GENE_REQUEST_TERMS):
        return True
    return bool(any(term in text for term in _LOCUS_GENE_REQUEST_TERMS) and "gene" in text)


def _explicit_gwas_gene_field_task_text(task_text: str | None) -> bool:
    text = _clean_text(task_text)
    if not text:
        return False
    return any(term in text for term in _EXPLICIT_GWAS_GENE_FIELD_TERMS)


def _gene_finding_text(genes: list[str], traits: list[str], pvalue: Any) -> str:
    gene_text = ", ".join(genes) or "candidate gene not specified"
    trait_text = traits[0] if traits else "trait not specified"
    return f"{gene_text} is named in a GWAS Catalog association for {trait_text}; p-value {pvalue}."


def _association_record(
    rsid: str,
    association: dict[str, Any],
    phenotype: str,
    *,
    phenotype_queries: Iterable[str] | None = None,
) -> dict[str, Any]:
    study = association.get("study") if isinstance(association.get("study"), dict) else {}
    disease_trait = study.get("diseaseTrait") if isinstance(study.get("diseaseTrait"), dict) else {}
    publication = study.get("publicationInfo") if isinstance(study.get("publicationInfo"), dict) else {}
    snps = association.get("snps") if isinstance(association.get("snps"), list) else []
    loci = association.get("loci") if isinstance(association.get("loci"), list) else []
    traits = _association_traits(association)
    disease_trait_text = _clean_text(disease_trait.get("trait"))
    trait_texts = [trait for trait in [disease_trait_text, *traits] if trait]
    match = _best_phenotype_match(phenotype_queries or [phenotype], trait_texts)
    association_url = _link_href(association, "self") or _link_href(association, "association")
    association_id = association_url.rstrip("/").split("/")[-1] if association_url else None
    return {
        "variant": rsid,
        "association_id": association_id,
        "association_url": association_url,
        "pvalue": association.get("pvalue") or _pvalue_from_parts(association),
        "pvalue_mantissa": association.get("pvalueMantissa"),
        "pvalue_exponent": association.get("pvalueExponent"),
        "risk_frequency": association.get("riskFrequency"),
        "effect": {
            "or_per_copy": association.get("orPerCopyNum"),
            "beta": association.get("betaNum"),
            "beta_unit": association.get("betaUnit"),
            "beta_direction": association.get("betaDirection"),
        },
        "risk_alleles": _risk_alleles(loci),
        "reported_genes": _reported_genes(loci),
        "mapped_genes": _mapped_genes(snps),
        "locations": _locations(snps),
        "traits": trait_texts,
        "study": {
            "accession": study.get("accessionId"),
            "disease_trait": disease_trait_text,
            "initial_sample_size": study.get("initialSampleSize"),
            "replication_sample_size": study.get("replicationSampleSize"),
            "pubmed_id": publication.get("pubmedId"),
            "publication_date": publication.get("publicationDate"),
            "publication": publication.get("publication"),
            "title": publication.get("title"),
            "author": (publication.get("author") or {}).get("fullname") if isinstance(publication.get("author"), dict) else None,
        },
        "phenotype_match": match,
        "finding": _finding_text(rsid, disease_trait_text, association),
        "record_research_payload": _record_research_payload(
            rsid,
            disease_trait_text,
            association_url,
            _finding_text(rsid, disease_trait_text, association),
        ),
    }


def _finding_text(rsid: str, disease_trait: str, association: dict[str, Any]) -> str:
    pvalue = association.get("pvalue") or _pvalue_from_parts(association)
    risk_alleles = ", ".join(_risk_alleles(association.get("loci") or [])) or "not specified"
    trait = disease_trait or "trait not specified"
    return f"{rsid} is associated with {trait} in GWAS Catalog; p-value {pvalue}; reported risk allele(s): {risk_alleles}."
