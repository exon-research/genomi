from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import ActiveGenomeIndexNeed
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
    agi_path = reader.active_genome_index_path
    if not agi_path.exists():
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar matching.",
        )
    output = resolved.get("output") or str(agi_path.with_name("clinvar.matches.jsonl"))
    return static_annotation.match_static_clinvar_from_active_genome_index(
        agi_path,
        evidence_db=_path(resolved, "db"),
        output=Path(str(output)),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _clinvar_scan(params: JsonObject) -> JsonObject:
    reader = open_agi(need=ActiveGenomeIndexNeed.VARIANT, action="reading parsed Active Genome Index artifacts", params=params)
    resolved = _with_context(params, db=True, genome_build=True)
    matches_path = _optional_path(params, "matches")
    if matches_path is None or not matches_path.exists():
        # No prebuilt matches file: materialize one from the Active Genome Index
        # (pure-SQLite, variant sites only — never an iteration of the raw VCF).
        materialized = _materialize_clinvar_matches_for_scan(reader.active_genome_index_path, resolved, matches_path)
        if isinstance(materialized, dict):
            return materialized
        matches_path = materialized
    return static_annotation.scan_static_candidates(
        matches_path,
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(params, "output"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _materialize_clinvar_matches_for_scan(
    agi_path: Path, resolved: JsonObject, matches_path: Path | None
) -> Path | JsonObject:
    if not agi_path.exists():
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar candidate scanning.",
        )
    output_path = matches_path or agi_path.with_name("clinvar.matches.jsonl")
    materialized = static_annotation.match_static_clinvar_from_active_genome_index(
        agi_path,
        evidence_db=_path(resolved, "db"),
        output=output_path,
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )
    if materialized.get("status") == "requires_library_install":
        return materialized
    materialized_output = materialized.get("output")
    return Path(str(materialized_output)) if materialized_output else output_path
