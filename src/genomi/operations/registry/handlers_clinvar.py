from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import default_active_genome_index_path
from ...capabilities.clinvar import static_annotation
from .coerce import (
    _bool,
    _optional_path,
    _path,
    _require_personal_artifact_context,
    _str,
    _with_context,
)
from .errors import JsonObject, OperationError


def _clinvar_match(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, vcf=True, db=True, active_genome_index_path=True, genome_build=True)
    _require_personal_artifact_context(
        params,
        resolved,
        "vcf",
        "Select or parse an Active Genome Index before ClinVar matching.",
        "reading parsed Active Genome Index artifacts",
    )
    # Personal-genome context comes only from the Active Genome Index, never a
    # raw VCF: resolve the index (deriving it from the source if context did not
    # supply it) and match against it. No source/canonical is reopened.
    agi_path = resolved.get("active_genome_index_path")
    if not agi_path and resolved.get("vcf"):
        agi_path = str(default_active_genome_index_path(_path(resolved, "vcf")))
    if not agi_path or not Path(str(agi_path)).exists():
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar matching.",
        )
    output = resolved.get("output")
    if not output:
        output = str(Path(str(agi_path)).with_name("clinvar.matches.jsonl"))
    return static_annotation.match_static_clinvar_from_active_genome_index(
        Path(str(agi_path)),
        evidence_db=_path(resolved, "db"),
        output=Path(str(output)),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _clinvar_scan(params: JsonObject) -> JsonObject:
    resolved = _with_context(params, db=True, active_genome_index_path=True, matches=True, comparable_vcf=True, genome_build=True)
    matches_path = Path(str(resolved["matches"])) if resolved.get("matches") else None
    if matches_path is not None and matches_path.exists():
        _require_personal_artifact_context(
            params,
            resolved,
            "matches",
            "Provide matches or select an Active Genome Index with ClinVar matches before scanning candidates.",
            "reading parsed Active Genome Index artifacts",
            source_keys=(),
        )
    else:
        materialization_key = "active_genome_index_path" if resolved.get("active_genome_index_path") else "vcf"
        _require_personal_artifact_context(
            params,
            resolved,
            materialization_key,
            "Provide/select an Active Genome Index before ClinVar candidate scanning.",
            "reading parsed Active Genome Index artifacts",
        )
        materialized = _materialize_clinvar_matches_for_scan(resolved, matches_path)
        if isinstance(materialized, dict):
            return materialized
        matches_path = materialized
    return static_annotation.scan_static_candidates(
        matches_path,
        evidence_db=_optional_path(resolved, "db"),
        output=_optional_path(resolved, "output"),
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )


def _materialize_clinvar_matches_for_scan(resolved: JsonObject, matches_path: Path | None) -> Path | JsonObject:
    # Always prefer the Active Genome Index (pure-SQLite, queries only variant
    # sites). The raw VCF-iteration path streams EVERY record — catastrophic for
    # a gVCF (~128M reference-block records) and it reopens the source. So when
    # the context didn't surface an index path, derive it from the source and
    # use it whenever the index exists; only iterate a VCF when there is no AGI.
    agi_path = resolved.get("active_genome_index_path")
    if not agi_path and resolved.get("vcf"):
        agi_path = str(default_active_genome_index_path(_path(resolved, "vcf")))
    agi_exists = bool(agi_path) and Path(str(agi_path)).exists()

    if not agi_exists:
        raise OperationError(
            "needs_active_genome_index",
            "Select or parse an Active Genome Index before ClinVar candidate scanning.",
        )
    output_path = matches_path or Path(str(agi_path)).with_name("clinvar.matches.jsonl")
    materialized = static_annotation.match_static_clinvar_from_active_genome_index(
        Path(str(agi_path)),
        evidence_db=_path(resolved, "db"),
        output=output_path,
        genome_build=_str(resolved, "genome_build", "GRCh38"),
        force=_bool(resolved, "force"),
    )
    if materialized.get("status") == "requires_library_install":
        return materialized
    materialized_output = materialized.get("output")
    return Path(str(materialized_output)) if materialized_output else output_path
