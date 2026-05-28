from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ....active_genome_index.active_genome_index import (
    default_active_genome_index_path,
)
from ....evidence import (
    _ensure_schema,
    build_clinvar_gene_index,
    build_clinvar_rsid_index,
    connect_evidence,
    evidence_summary,
    import_clinvar_vcf,
    init_evidence_db,
)
from ....runtime.handoff import attach_evidence_context, evidence_context
from ....runtime.library_status import (
    library_install_request,
    library_name_for_clinvar,
    library_status,
)
from ....runtime.paths import (
    default_export_variants_path,
    enclosing_work_dir,
    run_evidence_db_path,
    run_evidence_dir,
    run_output_path,
    run_project_dir,
    run_reference_dir,
    run_work_dir,
    sample_slug_from_vcf,
    shared_evidence_db_path,
)

WORKFLOW_AREA_ID = "static"
WORKFLOW_AREA_NAME = "Active Genome Indexing and library-scoped evidence materialization"
LONG_RUNNING_STATIC_REASON = (
    "Skipped by the bulk static profile because this step materializes or imports broad "
    "whole-callset/public artifacts. Use the focused evidence tool for the library or target that is "
    "actually needed."
)


def workflow_contract() -> dict[str, Any]:
    return {
        "id": WORKFLOW_AREA_ID,
        "name": WORKFLOW_AREA_NAME,
        "purpose": (
            "Keep selected genome sources queryable through an Active Genome Index, then materialize "
            "deterministic evidence artifacts only when a focused library or target-specific tool needs "
            "them. This workflow area uses local parsing, database import, and deterministic evidence "
            "checks without requiring a whole-callset static pass during intake."
        ),
        "primary_outputs": [
            "run project layout",
            "Active Genome Index",
            "source-format metadata",
            "sequencing-derived sample QC and genotype/callability support rows",
            "consumer-array rsID/locus observations when supplied",
            "library-scoped ClinVar exact-match JSONL when ClinVar matching is requested",
            "target-scoped candidate inventory when requested",
            "canonical shared evidence DB for reusable static rows",
            "per-run user evidence DB for sample-specific context",
            "SQLite evidence rows for lazily materialized public sources",
        ],
        "hands_off_to": "research",
        "database_boundary": {
            "shared": str(shared_evidence_db_path()),
            "user_private": "$GENOMI_HOME/<sample_slug>/evidence/evidence.sqlite",
            "private_rule": "research_scope='private' stays in the user/run DB",
            "sample_specific_tables": ["sample_qc", "genotype_support", "region_callability"],
        },
    }


def init_static_run(
    vcf: str | Path,
    *,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    vcf_path = Path(vcf)
    project_dir = run_project_dir(vcf_path)
    work_dir = run_work_dir(vcf_path)
    evidence_dir = run_evidence_dir(vcf_path)
    reference_dir = run_reference_dir(vcf_path)
    evidence_db = run_evidence_db_path(vcf_path)
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    clone_source_db = Path(source_evidence_db) if source_evidence_db is not None else shared_db if shared_db.exists() else None
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    evidence_status = "existing"
    if clone_source_db is not None:
        if not clone_source_db.exists():
            raise FileNotFoundError(clone_source_db)
        if force and evidence_db.exists():
            _unlink_sqlite_db(evidence_db)
        if evidence_db.exists():
            evidence_status = "existing_linked_shared_static"
        else:
            init_evidence_db(evidence_db)
            evidence_status = "linked_shared_static"
    elif evidence_db.exists() and not force:
        evidence_status = "existing"
    else:
        if evidence_db.exists():
            evidence_db.unlink()
        init_evidence_db(evidence_db)
        evidence_status = "initialized"

    _record_run_metadata(
        evidence_db,
        vcf_path,
        source_evidence_db=clone_source_db,
        shared_evidence_db=shared_db,
    )
    return {
        "workflow_area": WORKFLOW_AREA_ID,
        "status": "completed",
        "sample_slug": sample_slug_from_vcf(vcf_path),
        "vcf": str(vcf_path),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "evidence_db": str(evidence_db),
        "shared_evidence_db": str(shared_db),
        "source_evidence_db": str(clone_source_db) if clone_source_db is not None else None,
        "evidence_status": evidence_status,
        "default_outputs": default_static_outputs(vcf_path),
        "evidence_context": evidence_context(
            "static",
            reason="Prepare the run evidence store; focused tools materialize deterministic library artifacts when those facts are needed.",
            commands=[
                "genomi call genomi.parse_source --params '{\"source\":\"<vcf>\"}'",
                "genomi call clinvar.match_variants --params '{\"vcf\":\"<vcf>\"}'",
                "genomi call clinvar.scan_candidates --params '{\"matches\":\"<clinvar.matches.jsonl>\"}'",
            ],
        ),
    }


def _unlink_sqlite_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def default_static_outputs(vcf: str | Path) -> dict[str, str]:
    vcf_path = Path(vcf)
    return {
        "active_genome_index_path": str(default_active_genome_index_path(vcf_path)),
        "exported_variants": str(default_export_variants_path(vcf_path, pass_only=True)),
        "exported_primary_variants": str(
            default_export_variants_path(vcf_path, pass_only=True, primary_contigs_only=True)
        ),
        "exported_primary_nochr_variants": str(
            default_export_variants_path(
                vcf_path,
                pass_only=True,
                primary_contigs_only=True,
                chrom_style="no-chr",
            )
        ),
        "clinvar_matches": str(run_output_path(vcf_path, "clinvar.matches.jsonl")),
        "clinvar_annotations": str(run_output_path(vcf_path, "clinvar.annotations.json")),
        "clinvar_rsid_annotations": str(run_output_path(vcf_path, "clinvar.rsid-annotations.json")),
        "clinvar_scan": str(run_output_path(vcf_path, "clinvar.candidates.json")),
        "sample_qc": str(run_output_path(vcf_path, "sample-qc.json")),
    }


def _shared_static_write_db(run_db: Path, *, shared_evidence_db: str | Path | None) -> Path:
    if shared_evidence_db is not None:
        return Path(shared_evidence_db)
    linked = _linked_shared_static_db(run_db)
    return linked if linked is not None else shared_evidence_db_path()


def _linked_shared_static_db(run_db: Path) -> Path | None:
    if not run_db.exists():
        return None
    try:
        with connect_evidence(run_db, attach_shared=False) as connection:
            rows = connection.execute(
                """
                select key, value from metadata
                where key in ('source_evidence_db', 'shared_evidence_db')
                """
            ).fetchall()
    except sqlite3.Error:
        return None
    metadata = {str(key): json.loads(value) for key, value in rows}
    for key in ("source_evidence_db", "shared_evidence_db"):
        value = metadata.get(key)
        if not value:
            continue
        path = Path(str(value))
        return path if path.is_absolute() else Path.cwd() / path
    return None


def _link_run_db_to_shared_static(run_db: Path, shared_db: Path) -> None:
    if run_db.resolve() == shared_db.resolve():
        init_evidence_db(shared_db)
        return
    init_evidence_db(run_db)
    shared_value = str(shared_db)
    with connect_evidence(run_db, attach_shared=False) as connection:
        _ensure_schema(connection)
        for key in ("source_evidence_db", "shared_evidence_db"):
            connection.execute(
                """
                insert into main.metadata(key, value) values(?, ?)
                on conflict(key) do update set value = excluded.value
                """,
                (key, json.dumps(shared_value, sort_keys=True)),
            )
        connection.commit()


def _evidence_from_matches(matches: str | Path) -> Path | None:
    matches_path = Path(matches)
    if enclosing_work_dir(matches_path) is not None:
        return run_evidence_db_path(matches_path)
    return None


def sync_static_evidence_to_shared(
    evidence_db: str | Path,
    shared_evidence_db: str | Path | None = None,
) -> dict[str, Any]:
    source_db = Path(evidence_db)
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    if source_db.resolve() == shared_db.resolve():
        init_evidence_db(shared_db)
        return {
            "status": "same_db",
            "shared_evidence_db": str(shared_db),
            "inserted": {"clinvar_variants": 0, "population_frequencies": 0},
            "evidence_context": evidence_context(
                "research",
                reason="The shared static evidence store is already the active DB; continue with intent research.",
                commands=["genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
            ),
        }
    if not source_db.exists():
        raise FileNotFoundError(source_db)
    init_evidence_db(source_db)
    init_evidence_db(shared_db)
    with connect_evidence(source_db, attach_shared=False) as source, connect_evidence(shared_db, attach_shared=False) as target:
        inserted_clinvar = _copy_unique_rows(
            source,
            target,
            "clinvar_variants",
            [
                "chrom",
                "pos",
                "ref",
                "alt",
                "genome_build",
                "clinvar_id",
                "allele_id",
                "clinical_significance",
                "review_status",
                "conditions",
                "gene_info",
                "hgvs",
                "raw_info_json",
                "source_path",
                "source_version",
                "imported_at",
            ],
            ["chrom", "pos", "ref", "alt", "genome_build", "clinvar_id", "allele_id", "source_version"],
        )
        inserted_population = _copy_unique_rows(
            source,
            target,
            "population_frequencies",
            [
                "chrom",
                "pos",
                "ref",
                "alt",
                "genome_build",
                "source",
                "source_version",
                "population",
                "allele_count",
                "allele_number",
                "allele_frequency",
                "homozygote_count",
                "raw_info_json",
                "source_path",
                "imported_at",
            ],
            ["chrom", "pos", "ref", "alt", "genome_build", "source", "source_version", "population"],
        )
        _copy_shared_metadata(source, target)
        target.commit()
    if inserted_clinvar:
        build_clinvar_gene_index(shared_db, force=True)
    return {
        "status": "completed",
        "source_evidence_db": str(source_db),
        "shared_evidence_db": str(shared_db),
        "inserted": {
            "clinvar_variants": inserted_clinvar,
            "population_frequencies": inserted_population,
        },
        "evidence_context": evidence_context(
            "research",
            reason="Reusable static rows are synced to shared evidence; continue with target-scoped research.",
            commands=["genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"gene\",\"gene\":\"<gene>\"}'"],
        ),
    }


def _has_clinvar_evidence(evidence_db: Path, genome_build: str) -> bool:
    if not evidence_db.exists():
        return False
    with connect_evidence(evidence_db) as connection:
        try:
            _ensure_schema(connection)
            row = connection.execute(
                "select count(*) from clinvar_variants where genome_build = ?",
                (genome_build,),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    return bool(row and row[0])


def _other_build(genome_build: str) -> str:
    return "GRCh37" if genome_build == "GRCh38" else "GRCh38"


def _ensure_clinvar_cache_imported(
    db_path: Path,
    library_vcf: Path,
    genome_build: str,
    *,
    force: bool,
) -> None:
    """Make the evidence DB's ClinVar cache for a build match the installed
    library. Idempotent when it already matches; rebuilds when forced or when a
    stale/mismatched cache (different source) is present, then refreshes the
    gene/rsID indexes over the imported rows."""
    rebuilt = force
    try:
        import_clinvar_vcf(library_vcf, db_path, genome_build=genome_build, force=force)
    except RuntimeError as exc:
        if "different source" not in str(exc):
            raise
        import_clinvar_vcf(library_vcf, db_path, genome_build=genome_build, force=True)
        rebuilt = True
    build_clinvar_gene_index(db_path, force=rebuilt)
    build_clinvar_rsid_index(db_path, force=rebuilt)


def _resolve_clinvar_cache_build(
    db_path: Path,
    sample_build: str,
    *,
    force: bool,
    operation: str,
    intent: str,
) -> tuple[str, dict[str, Any] | None]:
    """Pick which ClinVar cache to query.

    Preference order:
    1. The matching-build cache (already in the DB or library installed).
    2. The other-build cache + liftover-chains library, so the runtime can
       lift sample positions to that build at query time.
    3. Otherwise return the matching-build install prompt — installing the
       directly-matching ClinVar library is still the simplest user path.
    """

    init_evidence_db(db_path)
    matching_library = library_name_for_clinvar(sample_build)
    matching_status = library_status(matching_library)
    if matching_status["installed"]:
        # Reconcile the evidence DB against the INSTALLED library cache rather
        # than trusting "some clinvar rows exist" — a stale, partial, or wrong
        # prior import (e.g. a 3-record fixture) must not pin scans to the wrong
        # data. Import is idempotent when the cache already matches the library;
        # a mismatched cache is rebuilt automatically.
        _ensure_clinvar_cache_imported(
            db_path,
            Path(matching_status["required_paths"][0]),
            sample_build,
            force=force,
        )
        return sample_build, None

    # Matching-build library is not installed: reuse whatever ClinVar evidence
    # was already imported for this build (cannot re-import without a library).
    if _has_clinvar_evidence(db_path, sample_build):
        return sample_build, None

    other_build = _other_build(sample_build)
    liftover_status = library_status("liftover-chains")
    if liftover_status["installed"]:
        if _has_clinvar_evidence(db_path, other_build):
            return other_build, None
        other_library_status = library_status(library_name_for_clinvar(other_build))
        if other_library_status["installed"]:
            import_clinvar_vcf(
                Path(other_library_status["required_paths"][0]),
                db_path,
                genome_build=other_build,
                force=force,
            )
            build_clinvar_gene_index(db_path, force=force)
            build_clinvar_rsid_index(db_path, force=force)
            return other_build, None

    request = library_install_request(
        matching_library,
        intent=intent,
        operation=operation,
        genome_build=sample_build,
    )
    return sample_build, attach_evidence_context(
        request,
        "static",
        reason="ClinVar matching cannot run until either the matching ClinVar library is installed, or liftover-chains plus the other-build ClinVar library are installed.",
        commands=[request["missing_library"]["install_command"]],
    )


def _ensure_clinvar_evidence(
    db_path: Path,
    genome_build: str,
    *,
    force: bool,
    operation: str,
    intent: str,
) -> dict[str, Any] | None:
    init_evidence_db(db_path)
    if _has_clinvar_evidence(db_path, genome_build):
        return None
    clinvar_library = library_name_for_clinvar(genome_build)
    clinvar_status = library_status(clinvar_library)
    if not clinvar_status["installed"]:
        request = library_install_request(
            clinvar_library,
            intent=intent,
            operation=operation,
            genome_build=genome_build,
        )
        return attach_evidence_context(
            request,
            "static",
            reason="ClinVar matching cannot run until the matching ClinVar public library is installed.",
            commands=[request["missing_library"]["install_command"]],
        )
    import_clinvar_vcf(
        Path(clinvar_status["required_paths"][0]),
        db_path,
        genome_build=genome_build,
        force=force,
    )
    build_clinvar_gene_index(db_path, force=force)
    build_clinvar_rsid_index(db_path, force=force)
    return None


def _reusable_static_db_with_clinvar(
    run_db: Path,
    shared_db: Path,
    genome_build: str,
    *,
    preferred_db: Path | None = None,
) -> Path:
    if preferred_db is not None and _has_clinvar_evidence(preferred_db, genome_build):
        return preferred_db
    if shared_db.exists() and _has_clinvar_evidence(shared_db, genome_build):
        return shared_db
    return run_db


def _copy_unique_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    columns: list[str],
    unique_columns: list[str],
) -> int:
    inserted = 0
    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _column in columns)
    unique_where = " and ".join(f"{column} is ?" for column in unique_columns)
    insert_sql = f"insert into {table}({column_sql}) values ({placeholders})"
    exists_sql = f"select 1 from {table} where {unique_where} limit 1"
    for row in source.execute(f"select {column_sql} from {table}"):
        values = [row[column] for column in columns]
        unique_values = [row[column] for column in unique_columns]
        if target.execute(exists_sql, unique_values).fetchone() is not None:
            continue
        target.execute(insert_sql, values)
        inserted += 1
    return inserted


def _copy_shared_metadata(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    for row in source.execute(
        """
        select key, value from metadata
        where key like 'clinvar_%'
           or key like 'population_%'
           or key like 'gnomad_%'
           or key = 'schema_version'
        """
    ):
        target.execute(
            """
            insert into metadata(key, value) values(?, ?)
            on conflict(key) do update set value = excluded.value
            """,
            (row["key"], row["value"]),
        )


def _record_run_metadata(
    evidence_db: Path,
    vcf_path: Path,
    *,
    source_evidence_db: str | Path | None,
    shared_evidence_db: str | Path | None,
) -> None:
    init_evidence_db(evidence_db)
    metadata = {
        "workflow_model": "static-research-report",
        "run_sample_slug": sample_slug_from_vcf(vcf_path),
        "run_vcf_path": str(vcf_path),
        "run_project_dir": str(run_project_dir(vcf_path)),
        "run_work_dir": str(run_work_dir(vcf_path)),
        "run_evidence_dir": str(run_evidence_dir(vcf_path)),
        "run_reference_dir": str(run_reference_dir(vcf_path)),
        "source_evidence_db": str(source_evidence_db) if source_evidence_db is not None else None,
        "shared_evidence_db": str(shared_evidence_db) if shared_evidence_db is not None else None,
    }
    with connect_evidence(evidence_db, attach_shared=False) as connection:
        for key, value in metadata.items():
            if key == "source_evidence_db" and value is None:
                existing = connection.execute("select 1 from metadata where key = ?", (key,)).fetchone()
                if existing is not None:
                    continue
            connection.execute(
                """
                insert into main.metadata(key, value) values(?, ?)
                on conflict(key) do update set value = excluded.value
                """,
                (key, json.dumps(value, sort_keys=True)),
            )
        connection.commit()
