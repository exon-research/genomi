from __future__ import annotations

import re

from .. import pgx_requirements, pgx_star
from ._common import JsonObject, _compact_selected_fields, _compact_text, _dedupe, _dedupe_params, _normalize_rsid, _pgxdb_record_source_url
from .record_research import _is_stored_sample_pgx_record, _is_stored_source_pgx_record


def _follow_up_rsids(rsid: str | None, clinpgx_result: JsonObject, pgxdb_result: JsonObject, *, limit: int) -> list[str]:
    rsids: set[str] = set()
    if rsid:
        rsids.add(rsid)
    for value in clinpgx_result.get("sample_follow_up_targets", {}).get("rsids") or []:
        normalized = _normalize_rsid(str(value))
        if normalized:
            rsids.add(normalized)
    for record in pgxdb_result.get("pgx_records") or []:
        normalized = _normalize_rsid(record.get("rsid"))
        if normalized:
            rsids.add(normalized)
    return sorted(rsids)[:limit]


def _follow_up_star_genes(gene: str | None, clinpgx_result: JsonObject) -> list[str]:
    from ._common import _normalize_gene

    genes: set[str] = set()
    normalized_gene = _normalize_gene(gene)
    if normalized_gene:
        genes.add(normalized_gene)
    for item in clinpgx_result.get("sample_follow_up_targets", {}).get("genes") or []:
        if isinstance(item, dict):
            normalized = _normalize_gene(item.get("symbol") or item.get("name"))
        else:
            normalized = _normalize_gene(str(item))
        if normalized:
            genes.add(normalized)
    return sorted(genes)


def _star_marker_match_count(star_allele_calls: list[JsonObject]) -> int:
    total = 0
    for call in star_allele_calls:
        for marker_call in call.get("marker_calls") or []:
            if _is_observed_star_marker(marker_call):
                total += 1
    return total


def _is_observed_star_marker(marker: JsonObject) -> bool:
    return str(marker.get("evidence_status") or "") in {
        "observed_effect_allele",
        "observed_reference_or_other_allele",
    }


def _technical_support_count(sample_lookups: list[JsonObject]) -> int:
    total = 0
    for lookup in sample_lookups:
        total += len(lookup.get("support_context", {}).get("genotype_support") or [])
    return total


def _sequencing_sample_match_count(sample_lookups: list[JsonObject]) -> int:
    total = 0
    for lookup in sample_lookups:
        for match in lookup.get("sample_context", {}).get("matches") or []:
            if match.get("source_format") in {"vcf", "gvcf"}:
                total += 1
    return total


def _has_active_genome_index_context(sample_lookups: list[JsonObject]) -> bool:
    for lookup in sample_lookups:
        sample_context = lookup.get("sample_context") or {}
        for active_genome_index in sample_context.get("searched_active_genome_indexes") or []:
            if active_genome_index.get("source_format") in {"vcf", "gvcf"}:
                return True
        for match in sample_context.get("matches") or []:
            if match.get("source_format") in {"vcf", "gvcf"}:
                return True
    return False


def _readiness(
    *,
    source_evidence_count: int,
    sample_match_count: int,
    star_marker_match_count: int,
    stored_sample_evidence_count: int,
    user_sample_evidence_count: int,
    rsid_targets: list[str],
    star_genes: list[str],
    star_allele_calls: list[JsonObject],
    clinpgx_result: JsonObject,
    sample_context_requested: bool,
) -> JsonObject:
    requirements = []
    supported_star_marker_coverage = _has_supported_star_marker_coverage(star_allele_calls)
    sample_evidence_count = sample_match_count + star_marker_match_count + stored_sample_evidence_count + user_sample_evidence_count
    personal_support = bool(source_evidence_count) and (
        bool(sample_evidence_count) or (bool(star_genes) and supported_star_marker_coverage)
    )
    if not source_evidence_count:
        requirements.append("source-backed PGx guideline, label, clinical annotation, or association evidence")
    if sample_context_requested and (rsid_targets or star_genes) and sample_evidence_count == 0:
        requirements.append("matching Active Genome Index evidence for selected PGx variant or marker targets")
    if sample_context_requested and star_genes and not star_allele_calls and not user_sample_evidence_count:
        requirements.append("supported pharmacogene star-allele, diplotype, phenotype, or specialized PGx caller evidence")
    if sample_context_requested and star_allele_calls and not supported_star_marker_coverage and not user_sample_evidence_count:
        requirements.append("observed marker coverage for supported star-allele interpretation or a validated specialized PGx caller")
    if sample_context_requested and not rsid_targets and not star_genes:
        requirements.append("selected variant, haplotype, diplotype, phenotype, or pharmacogene evidence target")
    if sample_context_requested:
        requirements.extend(clinpgx_result.get("clinical_verification", {}).get("requires_before_personal_actionability") or [])
    if personal_support:
        personal_statement_support = "source_and_sample_evidence_present"
    elif not sample_context_requested and source_evidence_count:
        personal_statement_support = "public_source_evidence_only"
    else:
        personal_statement_support = "needs_more_evidence"
    return {
        "status": "informational_evidence_review_requires_clinical_confirmation",
        "public_pgx_evidence": bool(source_evidence_count),
        "sample_context_requested": sample_context_requested,
        "sample_variant_evidence": bool(sample_evidence_count),
        "supported_star_marker_coverage": supported_star_marker_coverage,
        "personal_statement_support": personal_statement_support,
        "requires_before_personal_actionability": _dedupe(requirements),
    }


def _has_supported_star_marker_coverage(star_allele_calls: list[JsonObject]) -> bool:
    for call in star_allele_calls:
        diplotype = call.get("diplotype") or {}
        if diplotype.get("marker_support_status") == "common_marker_subset_observed":
            return True
    return False


def _answer_support(
    *,
    source_evidence_count: int,
    stored_sample_evidence_count: int,
    user_provided_sample_evidence: list[JsonObject],
    technical_support_count: int,
    sequencing_sample_match_count: int,
    clinpgx_result: JsonObject,
    pgxdb_result: JsonObject,
    fda_result: JsonObject,
    stored_research: JsonObject,
    sample_lookups: list[JsonObject],
    star_allele_calls: list[JsonObject],
) -> JsonObject:
    matched_associations = _matched_pgxdb_associations(pgxdb_result, sample_lookups)
    star_summaries = _star_diplotype_summaries(star_allele_calls)
    stored_sample_summaries = _stored_sample_pgx_summaries(stored_research)
    user_sample_summaries = _user_provided_sample_pgx_summaries(user_provided_sample_evidence)
    sample_signal_count = (
        len(matched_associations)
        + sum(1 for item in star_summaries if item.get("possible_diplotype") or item.get("called_star_alleles"))
        + stored_sample_evidence_count
        + len(user_sample_summaries)
    )
    star_sequencing_signal_count = _sequencing_star_marker_count(star_allele_calls)
    technical_status = _answer_technical_status(
        technical_support_count=technical_support_count,
        sequencing_sample_signal_count=sequencing_sample_match_count + star_sequencing_signal_count,
        stored_sample_signal_count=stored_sample_evidence_count,
        user_sample_signal_count=len(user_sample_summaries),
        sample_signal_count=sample_signal_count,
    )
    if source_evidence_count and sample_signal_count and technical_status == "needs_vcf_genotype_support":
        status = "source_and_sample_evidence_present_technical_support_pending"
    elif source_evidence_count and sample_signal_count:
        status = "source_and_sample_evidence_present"
    elif source_evidence_count:
        status = "public_source_evidence_present"
    elif sample_signal_count:
        status = "sample_evidence_present"
    else:
        status = "needs_evidence"
    return {
        "schema": "genomi-pgx-answer-support-v1",
        "status": status,
        "public_signal_count": source_evidence_count,
        "sample_signal_count": sample_signal_count,
        "technical_sample_support": {
            "status": technical_status,
            "technical_support_count": technical_support_count,
            "sequencing_sample_signal_count": sequencing_sample_match_count + star_sequencing_signal_count,
            "stored_sample_signal_count": stored_sample_evidence_count,
            "user_sample_signal_count": len(user_sample_summaries),
        },
        "matched_variant_associations": matched_associations,
        "star_diplotype_summaries": star_summaries,
        "stored_sample_pgx_summaries": stored_sample_summaries,
        "user_provided_sample_pgx_summaries": user_sample_summaries,
        "source_recommendation_summaries": _source_recommendation_summaries(clinpgx_result, pgxdb_result, fda_result, stored_research),
        "clinical_boundary": "informational_evidence_review",
        "semantics": [
            "This section links selected sample evidence to source evidence for host-agent synthesis.",
            "VCF-derived sample evidence needs genotype-support follow-up before stronger personal actionability language.",
            "User-provided sample PGx facts are treated as supplied evidence and need independent confirmation for clinical use.",
            "Clinical medication decisions require clinician or pharmacist confirmation.",
        ],
    }


def _answer_technical_status(
    *,
    technical_support_count: int,
    sequencing_sample_signal_count: int,
    stored_sample_signal_count: int,
    user_sample_signal_count: int,
    sample_signal_count: int,
) -> str:
    if technical_support_count:
        return "ready"
    if sequencing_sample_signal_count:
        return "needs_vcf_genotype_support"
    if stored_sample_signal_count:
        return "stored_sample_pgx_evidence_available"
    if user_sample_signal_count:
        return "user_provided_sample_pgx_evidence_available"
    if sample_signal_count:
        return "observed_genotype_available"
    return "pending_sample_match"


def _sequencing_star_marker_count(star_allele_calls: list[JsonObject]) -> int:
    count = 0
    for call in star_allele_calls:
        for marker in call.get("marker_calls") or []:
            if not _is_observed_star_marker(marker):
                continue
            for sample_call in marker.get("sample_calls") or []:
                if sample_call.get("source_format") in {"vcf", "gvcf"}:
                    count += 1
                    break
    return count


def _matched_pgxdb_associations(pgxdb_result: JsonObject, sample_lookups: list[JsonObject]) -> list[JsonObject]:
    matches_by_rsid = _sample_matches_by_rsid(sample_lookups)
    matched = []
    for record in pgxdb_result.get("pgx_records") or []:
        rsid = _normalize_rsid(record.get("rsid"))
        if not rsid:
            continue
        for sample_match in matches_by_rsid.get(rsid, []):
            observed = _observed_sample_genotype(sample_match)
            comparison = _compare_reported_alleles(record.get("alleles"), observed)
            matched.append(
                {
                    "rsid": rsid,
                    "drug": record.get("drug"),
                    "sample": observed,
                    "pgxdb": {
                        "alleles": record.get("alleles"),
                        "direction_of_effect": record.get("direction_of_effect"),
                        "pd_pk_terms": record.get("pd_pk_terms"),
                        "phenotype_category": record.get("phenotype_category"),
                        "significance": record.get("significance"),
                        "sentence": record.get("sentence"),
                        "pmid": record.get("pmid"),
                        "source_url": _pgxdb_record_source_url(record),
                    },
                    "match_status": comparison["status"],
                    "match_evidence": comparison,
                }
            )
    return matched


def _sample_matches_by_rsid(sample_lookups: list[JsonObject]) -> dict[str, list[JsonObject]]:
    by_rsid: dict[str, list[JsonObject]] = {}
    for lookup in sample_lookups:
        query_rsid = _normalize_rsid(lookup.get("query", {}).get("rsid"))
        for match in lookup.get("sample_context", {}).get("matches") or []:
            rsid = _normalize_rsid(match.get("rsid")) or query_rsid
            if not rsid:
                continue
            by_rsid.setdefault(rsid, []).append(match)
    return by_rsid


def _observed_sample_genotype(match: JsonObject) -> JsonObject:
    alleles = _observed_alleles(match)
    canonical = _canonical_genotype_token(alleles)
    return {
        "genotype": match.get("genotype"),
        "observed_alleles": alleles,
        "canonical_genotype": canonical,
        "ref": match.get("ref"),
        "alt": match.get("alt"),
        "source_format": match.get("source_format"),
        "filter": match.get("filter"),
        "depth": match.get("depth"),
        "genotype_quality": match.get("genotype_quality"),
    }


def _observed_alleles(match: JsonObject) -> list[str]:
    genotype = str(match.get("genotype") or "").strip().upper()
    ref = str(match.get("ref") or "").strip().upper()
    alts = [item.strip().upper() for item in str(match.get("alt") or "").split(",") if item.strip()]
    if re.fullmatch(r"[0-9.]+([/|][0-9.]+)*", genotype):
        alleles = []
        for token in re.split(r"[/|]", genotype):
            if token in {"", "."}:
                continue
            try:
                index = int(token)
            except ValueError:
                continue
            if index == 0 and ref:
                alleles.append(ref)
            elif index > 0 and index <= len(alts):
                alleles.append(alts[index - 1])
        return alleles
    letter_tokens = re.findall(r"[ACGT]", genotype)
    return letter_tokens if letter_tokens else []


def _canonical_genotype_token(alleles: list[str]) -> str | None:
    if not alleles:
        return None
    return "".join(sorted(alleles))


def _compare_reported_alleles(reported: object, observed: JsonObject) -> JsonObject:
    canonical = observed.get("canonical_genotype")
    reported_tokens = _reported_genotype_tokens(reported)
    if canonical and canonical in reported_tokens:
        return {"status": "reported_genotype_matches_sample", "reported_tokens": sorted(reported_tokens)}
    reversed_canonical = str(canonical or "")[::-1]
    if reversed_canonical and reversed_canonical in reported_tokens:
        return {"status": "reported_genotype_matches_sample", "reported_tokens": sorted(reported_tokens)}
    observed_alleles = {str(value).upper() for value in observed.get("observed_alleles") or []}
    if observed_alleles and reported_tokens and observed_alleles.intersection(set("".join(reported_tokens))):
        return {"status": "reported_allele_overlaps_sample", "reported_tokens": sorted(reported_tokens)}
    if reported_tokens:
        return {"status": "sample_variant_observed_reported_allele_not_matched", "reported_tokens": sorted(reported_tokens)}
    return {"status": "sample_variant_observed_no_reported_genotype_expression", "reported_tokens": []}


def _reported_genotype_tokens(value: object) -> set[str]:
    if value is None:
        return set()
    text = str(value).upper()
    tokens = set()
    for first, second in re.findall(r"\b([ACGT])\s*[/|]\s*([ACGT])\b", text):
        tokens.add("".join(sorted([first, second])))
    for token in re.findall(r"\b[ACGT]{1,2}\b", text):
        tokens.add("".join(sorted(token)))
    return tokens


def _star_diplotype_summaries(star_allele_calls: list[JsonObject]) -> list[JsonObject]:
    summaries = []
    for call in star_allele_calls:
        diplotype = call.get("diplotype") or {}
        summaries.append(
            {
                "gene": call.get("gene"),
                "definition_set": call.get("definition_set"),
                "possible_diplotype": diplotype.get("possible_diplotype"),
                "predicted_phenotype": diplotype.get("predicted_phenotype"),
                "marker_support_status": diplotype.get("marker_support_status"),
                "called_star_alleles": [
                    {
                        "star_allele": item.get("star_allele"),
                        "function": item.get("function"),
                        "rsid": item.get("rsid"),
                        "support": item.get("support"),
                    }
                    for item in call.get("called_star_alleles") or []
                ],
                "observed_marker_count": sum(
                    1
                    for marker in call.get("marker_calls") or []
                    if _is_observed_star_marker(marker)
                ),
            }
        )
    return summaries


def _stored_sample_pgx_summaries(stored_research: JsonObject) -> list[JsonObject]:
    summaries = []
    for record in stored_research.get("records") or []:
        if not _is_stored_sample_pgx_record(record):
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
        summaries.append(
            {
                "store": record.get("store"),
                "source": source.get("title"),
                "source_url": source.get("url"),
                "source_artifact": source.get("artifact"),
                "source_artifact_metadata": source.get("artifact_metadata"),
                "evidence_class": finding.get("type"),
                "summary": finding.get("summary") or finding.get("text"),
                "captured_by": record.get("captured_by"),
                "captured_at": record.get("captured_at"),
            }
        )
    return summaries


def _user_provided_sample_pgx_summaries(user_provided_sample_evidence: list[JsonObject]) -> list[JsonObject]:
    summaries = []
    for evidence in user_provided_sample_evidence:
        summaries.append(
            {
                "source": "user_provided",
                "evidence_class": evidence.get("evidence_class"),
                "status": evidence.get("status"),
                "gene": evidence.get("gene"),
                "rsid": evidence.get("rsid"),
                "known_genotype": evidence.get("known_genotype"),
                "known_diplotype": evidence.get("known_diplotype"),
                "known_phenotype": evidence.get("known_phenotype"),
                "known_activity_score": evidence.get("known_activity_score"),
                "known_pgx_source": evidence.get("known_pgx_source"),
                "clinical_boundary": evidence.get("clinical_boundary"),
            }
        )
    return summaries


def _source_recommendation_summaries(
    clinpgx_result: JsonObject,
    pgxdb_result: JsonObject,
    fda_result: JsonObject,
    stored_research: JsonObject,
) -> list[JsonObject]:
    summaries = []
    for record in clinpgx_result.get("guideline_annotations") or []:
        summaries.append(
            {
                "source": record.get("guideline_source") or "ClinPGx",
                "evidence_class": record.get("evidence_class"),
                "name": record.get("name"),
                "summary": record.get("summary") or record.get("text_excerpt"),
                "source_url": record.get("source_url"),
            }
        )
    for record in clinpgx_result.get("label_annotations") or []:
        summaries.append(
            {
                "source": record.get("label_source") or "ClinPGx",
                "evidence_class": record.get("evidence_class"),
                "name": record.get("name"),
                "summary": record.get("summary") or record.get("prescribing_excerpt") or record.get("text_excerpt"),
                "source_url": record.get("source_url"),
            }
        )
    for record in pgxdb_result.get("pgx_records") or []:
        summaries.append(
            {
                "source": "PGxDB",
                "evidence_class": "pgxdb_pharmacogenomic_association",
                "variant_or_haplotype": record.get("variant_or_haplotype"),
                "drug": record.get("drug"),
                "summary": record.get("sentence") or record.get("notes"),
                "source_url": _pgxdb_record_source_url(record),
            }
        )
    for record in pgxdb_result.get("medication_scoped_gene_drug_records") or []:
        summaries.append(
            {
                "source": "PGxDB",
                "evidence_class": "pgxdb_gene_drug_context",
                "gene": record.get("gene"),
                "drugbank_id": record.get("drugbank_id"),
                "target_scope": record.get("target_scope"),
                "summary": _compact_text(
                    " ".join(
                        str(item)
                        for item in (record.get("actions"), record.get("known_action"), record.get("interaction_type"))
                        if item
                    )
                ),
                "source_url": "https://pgx-db.org/rest-api/gene/drug/",
            }
        )
    for record in fda_result.get("rows") or []:
        summaries.append(
            {
                "source": "FDA PGx tables",
                "evidence_class": record.get("evidence_class"),
                "gene": record.get("gene_or_biomarker"),
                "drug": record.get("drug"),
                "summary": record.get("description") or record.get("labeling_sections") or record.get("affected_subgroups"),
                "source_url": record.get("source_url"),
            }
        )
    for record in stored_research.get("records") or []:
        if not _is_stored_source_pgx_record(record):
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        finding = record.get("finding") if isinstance(record.get("finding"), dict) else {}
        summaries.append(
            {
                "source": source.get("title") or "stored reviewed PGx research",
                "evidence_class": finding.get("type") or "stored_reviewed_pgx_research",
                "summary": finding.get("summary") or finding.get("text"),
                "source_url": source.get("url"),
                "store": record.get("store"),
                "captured_by": record.get("captured_by"),
                "captured_at": record.get("captured_at"),
            }
        )
    return summaries


def _target_inventory(
    *,
    drug: str | None,
    gene: str | None,
    rsid_targets: list[str],
    star_genes: list[str],
    star_allele_calls: list[JsonObject],
    public_evidence_count: int,
    sample_lookups: list[JsonObject],
    technical_support_count: int,
    active_genome_index_context_available: bool,
) -> JsonObject:
    implemented_marker_definition_genes = [target for target in star_genes if target in pgx_star.implemented_marker_definition_genes()]
    outside_call_genes = sorted(gene_name for gene_name in star_genes if gene_name in pgx_requirements.OUTSIDE_CALL_GENES)
    genotype_support_loci = []
    if not technical_support_count:
        genotype_support_loci.extend(_genotype_support_loci(sample_lookups))
        genotype_support_loci.extend(_star_marker_genotype_support_loci(star_allele_calls))
    return {
        "schema": "genomi-pgx-target-inventory-v1",
        "drug": drug,
        "selected_gene": gene,
        "public_evidence_count": public_evidence_count,
        "active_genome_index": {"active_genome_index_context_available": active_genome_index_context_available},
        "rsid_targets": rsid_targets,
        "pharmacogene_targets": star_genes,
        "implemented_marker_definition_genes": implemented_marker_definition_genes,
        "outside_call_genes": outside_call_genes,
        "genotype_support_loci": _dedupe_params(genotype_support_loci),
        "source_query_targets": {
            "drug": drug,
            "gene": gene,
            "rsids": rsid_targets,
        },
        "pharmcat_context": {
            "active_genome_index_context_available": active_genome_index_context_available,
            "public_evidence_count": public_evidence_count,
        },
    }


def _genotype_support_loci(sample_lookups: list[JsonObject]) -> list[JsonObject]:
    loci: list[JsonObject] = []
    for lookup in sample_lookups:
        genome_build = str(lookup.get("query", {}).get("genome_build") or "GRCh38")
        for match in lookup.get("sample_context", {}).get("matches") or []:
            if match.get("source_format") not in {"vcf", "gvcf"}:
                continue
            params = _genotype_support_params(match, genome_build=genome_build)
            if params:
                loci.append(params)
    return loci[:5]


def _star_marker_genotype_support_loci(star_allele_calls: list[JsonObject]) -> list[JsonObject]:
    loci: list[JsonObject] = []
    for call in star_allele_calls:
        genome_build = str(call.get("genome_build") or "GRCh38")
        for marker in call.get("marker_calls") or []:
            for sample_call in marker.get("sample_calls") or []:
                if sample_call.get("source_format") not in {"vcf", "gvcf"}:
                    continue
                params = _genotype_support_params(sample_call, genome_build=genome_build)
                if not params:
                    continue
                loci.append(params)
    return loci[:10]


def _genotype_support_params(match: JsonObject, *, genome_build: str) -> JsonObject | None:
    chrom = match.get("chrom")
    pos = match.get("pos")
    ref = match.get("ref")
    alt = match.get("alt")
    if not chrom or pos in {None, ""} or not ref or not alt:
        return None
    try:
        parsed_pos = int(pos)
    except (TypeError, ValueError):
        return None
    return {
        "chrom": str(chrom),
        "pos": parsed_pos,
        "ref": str(ref),
        "alt": str(alt),
        "genome_build": genome_build,
    }
