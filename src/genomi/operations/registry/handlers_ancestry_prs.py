from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import default_active_genome_index_path
from ...capabilities.ancestry import overlap as ancestry_overlap
from ...capabilities.ancestry import pca as ancestry_pca
from ...capabilities.ancestry import reference_panels as ancestry_reference_panels
from ...capabilities.ancestry import source_context as ancestry_source_context
from ...capabilities.nutrigenomics import operations as nutrigenomics_operations
from ...capabilities.prs import pgs_catalog as prs_pgs_catalog
from ...capabilities.prs import scorer as prs_scorer
from ...capabilities.prs import scoring_files as prs_scoring_files
from ...capabilities.prs import source_context as prs_source_context
from ...runtime.library_status import library_install_request, library_status
from .coerce import (
    _bool,
    _int,
    _optional_float,
    _optional_path,
    _optional_str,
    _path,
    _require_personal_artifact_context,
    _str,
    _with_context,
)
from .errors import JsonObject


def _ancestry_list_reference_panels(_: JsonObject) -> JsonObject:
    return ancestry_reference_panels.list_reference_panels()


def _ancestry_build_source_context(_: JsonObject) -> JsonObject:
    return ancestry_source_context.build_source_context()


def _ancestry_check_sample_overlap(params: JsonObject) -> JsonObject:
    resolved = _ancestry_private_context(params, "checking sample overlap with an ancestry reference panel")
    genome_build = _str(resolved, "genome_build", "GRCh38")
    missing = _ancestry_missing_library(
        "ancestry.check_sample_overlap",
        "checking sample overlap with the 1000 Genomes ancestry PCA panel",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_overlap.check_sample_overlap(
        _path(resolved, "vcf"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        genome_build=genome_build,
    )


def _ancestry_project_pca(params: JsonObject) -> JsonObject:
    resolved = _ancestry_private_context(params, "projecting a sample into ancestry reference-panel PCA space")
    genome_build = _str(resolved, "genome_build", "GRCh38")
    missing = _ancestry_missing_library(
        "ancestry.project_pca",
        "projecting a sample into the 1000 Genomes ancestry PCA panel",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_pca.project_sample_pca(
        _path(resolved, "vcf"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        genome_build=genome_build,
        nearest_reference_count=_int(resolved, "nearest_reference_count", 10),
    )


def _ancestry_estimate_population_context(params: JsonObject) -> JsonObject:
    resolved = _ancestry_private_context(params, "estimating qualitative ancestry reference-panel similarity")
    genome_build = _str(resolved, "genome_build", "GRCh38")
    missing = _ancestry_missing_library(
        "ancestry.estimate_population_context",
        "estimating qualitative 1000 Genomes reference-panel similarity",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_pca.estimate_population_context(
        _path(resolved, "vcf"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        genome_build=genome_build,
        nearest_reference_count=_int(resolved, "nearest_reference_count", 10),
    )


def _nutrigenomics_list_domains(_: JsonObject) -> JsonObject:
    return nutrigenomics_operations.list_domains()


def _nutrigenomics_build_source_context(_: JsonObject) -> JsonObject:
    return nutrigenomics_operations.build_source_context()


def _nutrigenomics_retrieve_domain_markers(params: JsonObject) -> JsonObject:
    return nutrigenomics_operations.retrieve_domain_markers(
        domain_id=params.get("domain_id"),
        min_evidence_tier=params.get("min_evidence_tier") or "established",
        semantic_context=params.get("semantic_context"),
    )


def _nutrigenomics_retrieve_variant_records(params: JsonObject) -> JsonObject:
    return nutrigenomics_operations.retrieve_variant_records(
        rsid=params.get("rsid"),
    )


def _ancestry_private_context(params: JsonObject, action: str) -> JsonObject:
    resolved = _with_context(params, vcf=True, active_genome_index_path=True, genome_build=True, allow_shared_db_without_vcf=False)
    if not resolved.get("vcf") and resolved.get("source"):
        resolved["vcf"] = resolved["source"]
    if resolved.get("vcf") and not resolved.get("active_genome_index_path"):
        resolved["active_genome_index_path"] = str(default_active_genome_index_path(Path(str(resolved["vcf"]))))
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a GRCh38 genome source or select an Active Genome Index before running ancestry projection tools.",
        action,
        source_keys=("source", "vcf"),
    )
    return resolved


def _ancestry_missing_library(operation: str, intent: str, genome_build: str) -> JsonObject | None:
    library = ancestry_source_context.panel_library_for_build(genome_build)
    panel_id = ancestry_source_context.panel_id_for_build(genome_build)
    title = (
        ancestry_source_context.PANEL_TITLE_GRCH38
        if panel_id == ancestry_source_context.PANEL_ID_GRCH38
        else ancestry_source_context.PANEL_TITLE_GRCH37
    )
    status = library_status(library)
    if status["installed"]:
        return None
    request = library_install_request(
        library,
        intent=intent,
        operation=operation,
        genome_build=genome_build,
    )
    request["schema"] = "genomi-ancestry-library-required-v1"
    request["reference_panel"] = {
        "panel_id": panel_id,
        "title": title,
        "library": library,
        "genome_build": genome_build,
        "source_urls": ancestry_source_context.source_urls(),
        "limitations": ancestry_source_context.limitations(),
    }
    return request


def _prs_search_scores(params: JsonObject) -> JsonObject:
    return prs_pgs_catalog.search_scores(
        query=_optional_str(params, "query"),
        trait=_optional_str(params, "trait"),
        pgs_id=_optional_str(params, "pgs_id"),
        efo_id=_optional_str(params, "efo_id"),
        limit=_int(params, "limit", 20),
        semantic_context=params.get("semantic_context"),
    )


def _prs_fetch_score_metadata(params: JsonObject) -> JsonObject:
    return prs_pgs_catalog.get_score_metadata(_str(params, "pgs_id"))


def _prs_import_scoring_file(params: JsonObject) -> JsonObject:
    return prs_scoring_files.import_scoring_file(
        pgs_id=_optional_str(params, "pgs_id"),
        genome_build=_str(params, "genome_build", "GRCh38"),
        scoring_file=_optional_path(params, "scoring_file"),
        scoring_url=_optional_str(params, "scoring_url"),
        force=_bool(params, "force"),
    )


def _prs_list_imported_scores(_: JsonObject) -> JsonObject:
    return prs_scoring_files.list_imported_scores()


def _prs_build_source_context(_: JsonObject) -> JsonObject:
    return prs_source_context.build_source_context()


def _prs_check_score_overlap(params: JsonObject) -> JsonObject:
    resolved = _prs_private_context(params, "checking sample overlap with a local polygenic-score file")
    return prs_scorer.check_score_overlap(
        _path(resolved, "vcf"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        pgs_id=_optional_str(resolved, "pgs_id"),
        score_dir=_optional_path(resolved, "score_dir"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        skip_ambiguous_palindromic=_bool(resolved, "skip_ambiguous_palindromic", True),
    )


def _prs_calculate_score(params: JsonObject) -> JsonObject:
    resolved = _prs_private_context(params, "calculating a polygenic score from local Active Genome Index artifacts")
    return prs_scorer.calculate_score(
        _path(resolved, "vcf"),
        active_genome_index_path=_optional_path(resolved, "active_genome_index_path"),
        pgs_id=_optional_str(resolved, "pgs_id"),
        score_dir=_optional_path(resolved, "score_dir"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        skip_ambiguous_palindromic=_bool(resolved, "skip_ambiguous_palindromic", True),
        score_mean=_optional_float(resolved, "score_mean"),
        score_sd=_optional_float(resolved, "score_sd"),
    )


def _prs_private_context(params: JsonObject, action: str) -> JsonObject:
    resolved = _with_context(params, vcf=True, active_genome_index_path=True, genome_build=True, allow_shared_db_without_vcf=False)
    if not resolved.get("vcf") and resolved.get("source"):
        resolved["vcf"] = resolved["source"]
    if resolved.get("vcf") and not resolved.get("active_genome_index_path"):
        resolved["active_genome_index_path"] = str(default_active_genome_index_path(Path(str(resolved["vcf"]))))
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Provide a genome source or select an Active Genome Index before running PRS tools.",
        action,
        source_keys=("source", "vcf"),
    )
    return resolved
