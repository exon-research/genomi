from __future__ import annotations

from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed, ActiveGenomeIndexReader
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
from .agi_access import open_agi
from .coerce import (
    _bool,
    _int,
    _optional_float,
    _optional_path,
    _optional_str,
    _str,
)
from .errors import JsonObject


def _private_build(reader: ActiveGenomeIndexReader, params: JsonObject) -> str:
    return str(params.get("genome_build") or reader.genome_build or "GRCh38")


def _ancestry_list_reference_panels(_: JsonObject) -> JsonObject:
    return ancestry_reference_panels.list_reference_panels()


def _ancestry_build_source_context(_: JsonObject) -> JsonObject:
    return ancestry_source_context.build_source_context()


def _ancestry_check_sample_overlap(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="checking sample overlap with an ancestry reference panel", params=params)
    genome_build = _private_build(reader, params)
    missing = _ancestry_missing_library(
        "ancestry.check_sample_overlap",
        "checking sample overlap with the 1000 Genomes ancestry PCA panel",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_overlap.check_sample_overlap(
        reader,
        genome_build=genome_build,
    )


def _ancestry_project_pca(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="projecting a sample into ancestry reference-panel PCA space", params=params)
    genome_build = _private_build(reader, params)
    missing = _ancestry_missing_library(
        "ancestry.project_pca",
        "projecting a sample into the 1000 Genomes ancestry PCA panel",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_pca.project_sample_pca(
        reader,
        genome_build=genome_build,
        nearest_reference_count=_int(params, "nearest_reference_count", 10),
    )


def _ancestry_estimate_population_context(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="estimating qualitative ancestry reference-panel similarity", params=params)
    genome_build = _private_build(reader, params)
    missing = _ancestry_missing_library(
        "ancestry.estimate_population_context",
        "estimating qualitative 1000 Genomes reference-panel similarity",
        genome_build,
    )
    if missing is not None:
        return missing
    return ancestry_pca.estimate_population_context(
        reader,
        genome_build=genome_build,
        nearest_reference_count=_int(params, "nearest_reference_count", 10),
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
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="checking sample overlap with a local polygenic-score file", params=params)
    return prs_scorer.check_score_overlap(
        reader,
        pgs_id=_optional_str(params, "pgs_id"),
        score_dir=_optional_path(params, "score_dir"),
        genome_build=_private_build(reader, params),
        skip_ambiguous_palindromic=_bool(params, "skip_ambiguous_palindromic", True),
    )


def _prs_calculate_score(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.REFERENCE, action="calculating a polygenic score from local Active Genome Index artifacts", params=params)
    return prs_scorer.calculate_score(
        reader,
        pgs_id=_optional_str(params, "pgs_id"),
        score_dir=_optional_path(params, "score_dir"),
        genome_build=_private_build(reader, params),
        skip_ambiguous_palindromic=_bool(params, "skip_ambiguous_palindromic", True),
        score_mean=_optional_float(params, "score_mean"),
        score_sd=_optional_float(params, "score_sd"),
    )
