from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed, ActiveGenomeIndexReader
from ...capabilities.clinvar import static_annotation
from .agi_access import open_agi
from .coerce import (
    _bool,
    _optional_path,
    _path,
    _str,
    _with_context,
)
from .errors import JsonObject, OperationError


def _clinvar_match(params: JsonObject) -> JsonObject:
    # Auth-gated through open_agi (need=VARIANT: matching reads variant sites,
    # final at variants_ready). Personal-genome context comes only from the
    # Active Genome Index, never a raw VCF.
    reader = open_agi(need=ActiveGenomeIndexNeed.VARIANT, action="reading parsed Active Genome Index artifacts", params=params)
    resolved = _with_context(params, db=True, genome_build=True)
    agi_path = reader.agi_path
    if not agi_path.exists():
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar matching.",
        )
    output = resolved.get("output") or str(agi_path.with_name("clinvar.matches.jsonl"))
    return static_annotation.match_static_clinvar_from_active_genome_index(
        reader,
        evidence_db=_path(resolved, "db"),
        output=Path(str(output)),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _clinvar_scan(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.VARIANT, action="reading parsed Active Genome Index artifacts", params=params)
    resolved = _with_context(params, db=True, genome_build=True)
    materialized = _materialize_clinvar_matches_for_scan(reader, resolved)
    if isinstance(materialized, dict):
        return materialized
    return static_annotation.scan_static_candidates(
        materialized,
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(params, "output"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _materialize_clinvar_matches_for_scan(
    reader: ActiveGenomeIndexReader, resolved: JsonObject
) -> Path | JsonObject:
    agi_path = reader.agi_path
    if not agi_path.exists():
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar candidate scanning.",
        )
    output_path = agi_path.with_name("clinvar.matches.jsonl")
    materialized = static_annotation.match_static_clinvar_from_active_genome_index(
        reader,
        evidence_db=_path(resolved, "db"),
        output=output_path,
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )
    if materialized.get("status") == "requires_library_install":
        return materialized
    materialized_output = materialized.get("output")
    return Path(str(materialized_output)) if materialized_output else output_path
