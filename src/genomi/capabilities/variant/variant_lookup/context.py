from __future__ import annotations

from pathlib import Path
from typing import Any

from ....active_genome_index.active_genome_index import ActiveGenomeIndexNeed, open_reader
from ....evidence import envelope as _env
from .parsing import _chrom_aliases, _dedupe_records
from .queries import (
    _query_active_genome_index,
    _query_clinvar_allele,
    _query_clinvar_locus,
    _query_clinvar_region,
    _query_clinvar_rsid,
    _query_genotype_support,
    _query_population_allele,
    _query_research_topic,
    _query_research_variant,
)
from .runs import _public_db_descriptor, _run_summary

JsonObject = dict[str, Any]


def _public_context(
    targets: list[JsonObject],
    *,
    evidence_dbs: list[JsonObject],
    genome_build: str,
    limit: int,
    warnings: list[str],
) -> JsonObject:
    clinvar_by_rsid: list[JsonObject] = []
    clinvar_by_allele: list[JsonObject] = []
    clinvar_by_locus: list[JsonObject] = []
    population_frequencies: list[JsonObject] = []
    reviewed_research: list[JsonObject] = []

    for database in evidence_dbs:
        path = Path(database["path"])
        label = database["label"]
        for target in targets:
            target_type = target["target_type"]
            if target_type == "rsid":
                clinvar_by_rsid.extend(_query_clinvar_rsid(path, label, str(target["rsid"]), genome_build=genome_build, limit=limit, warnings=warnings))
                reviewed_research.extend(_query_research_topic(path, label, str(target["rsid"]), limit=limit, warnings=warnings))
            elif target_type == "allele":
                for chrom_value in _chrom_aliases(str(target["chrom"])):
                    allele = {**target, "chrom": chrom_value}
                    clinvar_by_allele.extend(_query_clinvar_allele(path, label, allele, limit=limit, warnings=warnings))
                    population_frequencies.extend(_query_population_allele(path, label, allele, limit=limit, warnings=warnings))
                    reviewed_research.extend(_query_research_variant(path, label, allele, limit=limit, warnings=warnings))
            elif target_type == "locus":
                for chrom_value in _chrom_aliases(str(target["chrom"])):
                    clinvar_by_locus.extend(
                        _query_clinvar_locus(path, label, chrom_value, int(target["pos"]), genome_build=genome_build, limit=limit, warnings=warnings)
                    )
            elif target_type == "region":
                for chrom_value in _chrom_aliases(str(target["chrom"])):
                    clinvar_by_locus.extend(
                        _query_clinvar_region(
                            path,
                            label,
                            chrom_value,
                            int(target["start"]),
                            int(target["end"]),
                            genome_build=genome_build,
                            limit=limit,
                            warnings=warnings,
                        )
                    )

    return {
        "evidence_stores": [_public_db_descriptor(database) for database in evidence_dbs],
        "clinvar_by_rsid": _dedupe_records(clinvar_by_rsid, ("evidence_store", "rsid", "chrom", "pos", "ref", "alt", "clinvar_id")),
        "clinvar_by_allele": _dedupe_records(clinvar_by_allele, ("evidence_store", "chrom", "pos", "ref", "alt", "clinvar_id")),
        "clinvar_by_locus": _dedupe_records(clinvar_by_locus, ("evidence_store", "chrom", "pos", "ref", "alt", "clinvar_id")),
        "population_frequencies": _dedupe_records(
            population_frequencies,
            ("evidence_store", "chrom", "pos", "ref", "alt", "source", "population"),
        ),
        "reviewed_research": _dedupe_records(reviewed_research, ("evidence_store", "finding_id")),
    }


def _sample_context(
    targets: list[JsonObject],
    *,
    runs: list[tuple[JsonObject, str]],
    include_fail: bool,
    limit: int,
    warnings: list[str],
) -> JsonObject:
    searched_active_genome_indexes: list[JsonObject] = []
    matches: list[JsonObject] = []
    for run, selection in runs:
        summary = _run_summary(run, selection)
        searched_active_genome_indexes.append(summary)
        active_genome_index_path = run.get("active_genome_index_path")
        if not active_genome_index_path:
            summary["query_available"] = False
            continue
        # The reader is the one door to AGI data. need=NONE: variant.resolve
        # does its own format-aware availability check below — consumer-array
        # indexes (23andme etc.) are queryable without the vcf-centric
        # completion marker, and a variants_ready gVCF is fine since variant
        # rows are final — so the generic readiness gate must not apply here.
        reader = open_reader(
            Path(str(active_genome_index_path)),
            need=ActiveGenomeIndexNeed.NONE,
            vcf_path=run.get("vcf"),
            genome_build=run.get("genome_build"),
        )
        if run.get("source_format") in {"vcf", "gvcf"}:
            summary["active_genome_index_readiness"] = reader.readiness
            if not reader.variants_ready:
                summary["query_available"] = False
                summary["availability_note"] = reader.readiness.get("reason") or "active_genome_index_not_complete"
                warnings.append(
                    f"Active Genome Index {run.get('agi_id')} is not complete; rerun genomi.parse_source to resume/rebuild it."
                )
                continue
        elif not reader.active_genome_index_path.exists():
            summary["query_available"] = False
            summary["availability_note"] = "active_genome_index_not_found"
            continue
        summary["query_available"] = True
        for target in targets:
            matches.extend(
                _query_active_genome_index(
                    reader,
                    run=run,
                    selection=selection,
                    target=target,
                    include_fail=include_fail,
                    limit=limit,
                    warnings=warnings,
                )
            )
    deduped_matches = _dedupe_records(
        matches, ("agi_id", "chrom", "pos", "ref", "alt", "rsid", "genotype", "filter")
    )
    return {
        "searched_active_genome_indexes": searched_active_genome_indexes,
        "searched_known_active_genome_indexes": any(selection == "known_active_genome_index" for _run, selection in runs),
        "count": len(deduped_matches),
        "matches": deduped_matches,
    }


def _support_context(
    targets: list[JsonObject],
    *,
    runs: list[tuple[JsonObject, str]],
    evidence_dbs: list[JsonObject],
    genome_build: str,
    limit: int,
    warnings: list[str],
) -> JsonObject:
    genotype_support: list[JsonObject] = []
    agi_ids = {str(run.get("agi_id") or "") for run, _selection in runs}
    for database in evidence_dbs:
        label = database["label"]
        if label.startswith("agi:") and label.split(":", 1)[1] not in agi_ids:
            continue
        path = Path(database["path"])
        for target in targets:
            if target["target_type"] != "allele":
                continue
            for chrom_value in _chrom_aliases(str(target["chrom"])):
                genotype_support.extend(
                    _query_genotype_support(path, label, {**target, "chrom": chrom_value}, genome_build=genome_build, limit=limit, warnings=warnings)
                )
    return {
        "genotype_support": _dedupe_records(genotype_support, ("evidence_store", "chrom", "pos", "ref", "alt", "genome_build", "created_at")),
    }


def _target_inventory(
    *,
    targets: list[JsonObject],
    sample_context: JsonObject,
    public_context: JsonObject,
    support_context: JsonObject,
) -> JsonObject:
    allele_targets = [target for target in targets if target["target_type"] == "allele"]
    support_rows = support_context.get("genotype_support") or []
    frequency_rows = public_context.get("population_frequencies") or []
    research_rows = public_context.get("reviewed_research") or []
    genotype_support_loci = []
    for target in allele_targets[:5]:
        params = {
            "chrom": target["chrom"],
            "pos": target["pos"],
            "ref": target["ref"],
            "alt": target["alt"],
            "genome_build": target.get("genome_build") or "GRCh38",
        }
        genotype_support_loci.append(params)
    return {
        "schema": "genomi-variant-target-inventory-v1",
        "target_count": len(targets),
        "rsid_targets": [target["rsid"] for target in targets if target["target_type"] == "rsid"],
        "allele_targets": allele_targets,
        "genotype_support_loci": genotype_support_loci,
        "has_sample_matches": bool(sample_context.get("matches")),
        "has_genotype_support": bool(support_rows),
        "has_population_frequency": bool(frequency_rows),
        "has_reviewed_research": bool(research_rows),
    }


def _unanswered_components(
    *,
    targets: list[JsonObject],
    sample_context: JsonObject,
    public_context: JsonObject,
    support_context: JsonObject,
) -> list[JsonObject]:
    components: list[JsonObject] = []
    if not targets:
        components.append(_unanswered_component("target_resolution", "missing", ["rsid", "chrom", "pos", "ref", "alt", "region", "query"]))
        return components
    if not _has_any_context_evidence(sample_context=sample_context, public_context=public_context, support_context=support_context):
        components.append(_unanswered_component("public_context", "absent", ["condition", "phenotype", "drug", "source_document"]))
    if not sample_context.get("searched_active_genome_indexes"):
        components.append(_unanswered_component("sample_context", "unselected", ["active_genome_index", "agi_id"]))
    elif not sample_context.get("matches"):
        components.append(_unanswered_component("sample_context", "no_match_in_selected_active_genome_indexes", []))
    if sample_context.get("matches") and not support_context.get("genotype_support"):
        components.append(_unanswered_component("technical_support", "sample_signal_without_genotype_support", ["genotype_support"]))
    return components


def _unanswered_component(
    component: str,
    state: str,
    missing_inputs: list[str],
) -> JsonObject:
    return {
        "component": component,
        "state": state,
        "missing_inputs": missing_inputs,
    }


def _has_any_context_evidence(*, sample_context: JsonObject, public_context: JsonObject, support_context: JsonObject) -> bool:
    return bool(
        sample_context.get("matches")
        or support_context.get("genotype_support")
        or public_context.get("clinvar_by_rsid")
        or public_context.get("clinvar_by_allele")
        or public_context.get("clinvar_by_locus")
        or public_context.get("population_frequencies")
        or public_context.get("reviewed_research")
    )


def _build_variant_envelope(
    *,
    targets: list[JsonObject],
    sample_context: JsonObject,
    public_context: JsonObject,
    support_context: JsonObject,
    unanswered_components: list[JsonObject],
    query_scope: JsonObject,
) -> JsonObject:
    has_sample = _has_any_context_evidence(
        sample_context=sample_context,
        public_context={},
        support_context={},
    )
    has_public = _has_any_context_evidence(
        sample_context={},
        public_context=public_context,
        support_context={},
    )
    has_support = _has_any_context_evidence(
        sample_context={},
        public_context={},
        support_context=support_context,
    )
    observations = {
        "target_count": len(targets),
        "sample_match_count": int((sample_context or {}).get("total_matches") or 0) if isinstance(sample_context, dict) else 0,
        "public_record_count": int((public_context or {}).get("total_records") or 0) if isinstance(public_context, dict) else 0,
        "support_record_count": int((support_context or {}).get("total_records") or 0) if isinstance(support_context, dict) else 0,
        "unanswered_count": len(unanswered_components),
    }
    personal_context = _env._personal_context(uses_personal_dna=bool(query_scope.get("include_active_genome_index")))
    coverage = _env._coverage(consulted_sources=["active_genome_index", "shared_evidence_db"])
    if not targets:
        return _env.not_assessed(
            operation="variant.resolve",
            reason="No rsID, exact allele, locus, or region target was resolved from the input.",
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
        )
    if has_sample or has_public or has_support:
        return _env.evidence_present(
            operation="variant.resolve",
            query_scope=query_scope,
            personal_context=personal_context,
            coverage=coverage,
            observations=observations,
            answer_readiness=_env.SCOPED_ANSWER_ONLY,
        )
    return _env.empty_consulted_scope(
        operation="variant.resolve",
        query_scope=query_scope,
        personal_context=personal_context,
        coverage=coverage,
        observations=observations,
    )
