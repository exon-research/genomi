from __future__ import annotations

from pathlib import Path

from ...runtime.paths import (
    run_evidence_db_path_for_source,
    run_evidence_dir_for_source,
    run_output_path_for_source,
    run_project_dir_for_source,
    run_reference_dir_for_source,
    run_work_dir_for_source,
    sample_slug_from_source,
    shared_evidence_db_path,
    shared_reference_dir,
)
from ...runtime.static_dependencies import ensure_reference_fasta
from ..alignment import (
    align_fastq_to_bam,
    detect_paired_fastq,
    normalize_alignment_genome_build,
)
from .agi_store import SOURCE_PARSE_SCHEMA, JsonObject, _init_source_evidence_db
from .detection import SourceDetection
from .vcf import _parse_vcf_active_genome_index


def parse_bam_source(
    source: str | Path,
    *,
    detection: SourceDetection | None = None,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    auto_reference_fasta: bool = True,
    reference_root: str | Path | None = None,
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
    parallel_workers: int | None = None,
) -> JsonObject:
    # Resolve the BAM helpers through the package namespace so test patches on
    # ``genomi.active_genome_index.source_intake.<name>`` apply at the call site.
    from . import infer_genome_build_from_bam, materialize_bam_variant_vcf

    source_path = Path(source)
    detection = detection or SourceDetection(source_format="bam", source_kind="alignment_reads")
    inferred_build = infer_genome_build_from_bam(source_path)
    effective_build = normalize_alignment_genome_build(genome_build, inferred_build)
    project_dir = run_project_dir_for_source(source_path, source_format="bam")
    work_dir = run_work_dir_for_source(source_path, source_format="bam")
    evidence_dir = run_evidence_dir_for_source(source_path, source_format="bam")
    reference_dir = run_reference_dir_for_source(source_path, source_format="bam")
    db_path = Path(evidence_db) if evidence_db is not None else run_evidence_db_path_for_source(source_path, source_format="bam")
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    _init_source_evidence_db(
        db_path,
        source_path,
        source_format="bam",
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )

    steps: list[JsonObject] = [
        {
            "name": "init-source",
            "result": {
                "status": "completed",
                "project_dir": str(project_dir),
                "work_dir": str(work_dir),
                "evidence_db": str(db_path),
                "shared_evidence_db": str(shared_db),
            },
            "reason": "The BAM run layout and evidence DB are ready before deriving a variant callset.",
        }
    ]

    resolved_reference_fasta = Path(reference_fasta) if reference_fasta is not None else None
    if resolved_reference_fasta is None and auto_reference_fasta:
        dependency = ensure_reference_fasta(
            genome_build=effective_build,
            root=reference_root or shared_reference_dir(),
            force=force,
        )
        steps.append(
            {
                "name": "ensure-reference-fasta",
                "result": dependency,
                "reason": "BAM variant calling needs the matching reference FASTA.",
            }
        )
        resolved_reference_fasta = Path(dependency["output"])
    if resolved_reference_fasta is None:
        raise ValueError("BAM source parsing requires reference_fasta or auto_reference_fasta=true.")

    derived_vcf = run_output_path_for_source(source_path, "derived.variants.vcf", source_format="bam")
    materialized = materialize_bam_variant_vcf(
        source_path,
        resolved_reference_fasta,
        derived_vcf,
        force=force,
    )
    steps.append(
        {
            "name": "materialize-variants-from-bam",
            "result": materialized,
            "reason": "The read alignment is transformed into a local variant callset before Genomi builds Active Genome Index sample evidence.",
        }
    )

    active_genome_index_result = _parse_vcf_active_genome_index(
        derived_vcf,
        detection=SourceDetection(source_format="vcf", source_kind="derived_variant_callset"),
        evidence_db=db_path,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
        parallel_workers=parallel_workers,
    )
    steps.append(
        {
            "name": "build-active-genome-index-from-derived-vcf",
            "result": active_genome_index_result,
            "reason": "The derived VCF is digitized into an Active Genome Index; public evidence tools materialize libraries later when needed.",
        }
    )
    outputs = dict(active_genome_index_result.get("outputs") or {})
    outputs["derived_vcf"] = str(derived_vcf)
    outputs["bam_variant_call_manifest"] = materialized.get("manifest_path")

    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": "bam",
        "source_kind": detection.source_kind,
        "sample_slug": sample_slug_from_source(source_path, source_format="bam"),
        "genome_build": effective_build,
        "bam_header_genome_build": inferred_build,
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "vcf": str(derived_vcf),
        "derived_vcf": str(derived_vcf),
        "reference_fasta": str(resolved_reference_fasta),
        "outputs": outputs,
        "steps": steps,
        "semantics": [
            "BAM is an aligned-read source, not a preinterpreted variant report.",
            "Genomi derives a local VCF from reads with a matching reference FASTA, then builds an Active Genome Index for normal sample-specific tools.",
            "The original BAM stays private intake after digitization; future inquiries should use the Active Genome Index.",
            "Derived variant calls depend on alignment quality, reference build, and the variant caller settings recorded in the manifest.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ],
    }


def parse_fastq_source(
    source: str | Path,
    *,
    detection: SourceDetection | None = None,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    auto_reference_fasta: bool = True,
    reference_root: str | Path | None = None,
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
    parallel_workers: int | None = None,
) -> JsonObject:
    """Align a paired-end FASTQ deliverable, then digitize the derived BAM.

    Accepts the R1 path; the R2 sibling is resolved with the standard
    ``_R1_`` / ``_R2_`` (or ``_1`` / ``_2``) suffix convention. The chosen
    aligner is decided at runtime from the median read length sniffed from
    R1: ≤200 bp picks bwa-mem2 (short-read), >200 bp picks minimap2.
    """

    r1_path = Path(source)
    detection = detection or SourceDetection(source_format="fastq", source_kind="paired_reads_input")
    pair = detect_paired_fastq(r1_path)
    if pair is None:
        raise ValueError(
            f"FASTQ source must be a paired-end R1 file with an R2 sibling next to it: {r1_path}. "
            "Name the inputs `<sample>_R1_*.fastq.gz` and `<sample>_R2_*.fastq.gz` (or `_1` / `_2`)."
        )
    r1_path, r2_path = pair

    effective_build = normalize_alignment_genome_build(genome_build, None)
    project_dir = run_project_dir_for_source(r1_path, source_format="fastq")
    work_dir = run_work_dir_for_source(r1_path, source_format="fastq")
    evidence_dir = run_evidence_dir_for_source(r1_path, source_format="fastq")
    reference_dir = run_reference_dir_for_source(r1_path, source_format="fastq")
    db_path = (
        Path(evidence_db)
        if evidence_db is not None
        else run_evidence_db_path_for_source(r1_path, source_format="fastq")
    )
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    _init_source_evidence_db(
        db_path,
        r1_path,
        source_format="fastq",
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
    )

    resolved_reference_fasta = Path(reference_fasta) if reference_fasta is not None else None
    steps: list[JsonObject] = [
        {
            "name": "init-source",
            "result": {
                "status": "completed",
                "project_dir": str(project_dir),
                "work_dir": str(work_dir),
                "evidence_db": str(db_path),
                "shared_evidence_db": str(shared_db),
                "r1": str(r1_path),
                "r2": str(r2_path),
            },
            "reason": "The FASTQ run layout, evidence DB, and paired-end R2 sibling are resolved before alignment.",
        }
    ]
    if resolved_reference_fasta is None and auto_reference_fasta:
        dependency = ensure_reference_fasta(
            genome_build=effective_build,
            root=reference_root or shared_reference_dir(),
            force=force,
        )
        steps.append(
            {
                "name": "ensure-reference-fasta",
                "result": dependency,
                "reason": "FASTQ alignment needs the matching reference FASTA before reads can be placed.",
            }
        )
        resolved_reference_fasta = Path(dependency["output"])
    if resolved_reference_fasta is None:
        raise ValueError(
            "FASTQ source parsing requires reference_fasta or auto_reference_fasta=true."
        )

    derived_bam = run_output_path_for_source(r1_path, "derived.aligned.bam", source_format="fastq")
    alignment_result = align_fastq_to_bam(
        r1_path,
        r2_path,
        resolved_reference_fasta,
        derived_bam,
        force=force,
    )
    steps.append(
        {
            "name": "align-fastq-to-bam",
            "result": alignment_result,
            "reason": "Paired-end reads are aligned to the reference and sorted into a BAM before BAM-style variant calling.",
        }
    )
    if alignment_result.get("status") == "requires_library_install":
        return {
            "schema": SOURCE_PARSE_SCHEMA,
            "workflow_area": "active-genome-index",
            "status": "requires_library_install",
            "source": str(r1_path),
            "source_format": "fastq",
            "source_kind": detection.source_kind,
            "sample_slug": sample_slug_from_source(r1_path, source_format="fastq"),
            "genome_build": effective_build,
            "evidence_db": str(db_path),
            "shared_evidence_db": str(shared_db),
            "project_dir": str(project_dir),
            "work_dir": str(work_dir),
            "evidence_dir": str(evidence_dir),
            "reference_dir": str(reference_dir),
            "reference_fasta": str(resolved_reference_fasta),
            "fastq": {"r1": str(r1_path), "r2": str(r2_path)},
            "missing_libraries": alignment_result.get("missing_libraries", []),
            "message": alignment_result.get("message"),
            "steps": steps,
        }

    # Hand the sorted BAM off to the existing BAM → derived VCF → Active Genome Index path so
    # FASTQ deliverables produce the same Active Genome Index artifacts as a
    # user-uploaded BAM.
    bam_parse = parse_bam_source(
        derived_bam,
        detection=SourceDetection(
            source_format="bam",
            source_kind="alignment_reads",
            reference_build=effective_build,
        ),
        evidence_db=db_path,
        source_evidence_db=source_evidence_db,
        shared_evidence_db=shared_db,
        reference_fasta=resolved_reference_fasta,
        auto_reference_fasta=False,
        reference_root=reference_root,
        genome_build=effective_build,
        force=force,
        max_records=max_records,
        parallel_workers=parallel_workers,
    )
    steps.append(
        {
            "name": "digitize-derived-bam",
            "result": bam_parse,
            "reason": "The aligned BAM is digitized via the existing BAM path so downstream tools see the same Active Genome Index.",
        }
    )

    outputs = dict(bam_parse.get("outputs") or {})
    outputs["aligned_bam"] = str(derived_bam)
    outputs["fastq_alignment_manifest"] = alignment_result.get("manifest_path")

    return {
        "schema": SOURCE_PARSE_SCHEMA,
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(r1_path),
        "source_format": "fastq",
        "source_kind": detection.source_kind,
        "sample_slug": sample_slug_from_source(r1_path, source_format="fastq"),
        "genome_build": effective_build,
        "aligner": alignment_result.get("aligner"),
        "median_read_length": alignment_result.get("median_read_length"),
        "evidence_db": str(db_path),
        "shared_evidence_db": str(shared_db),
        "project_dir": str(project_dir),
        "work_dir": str(work_dir),
        "evidence_dir": str(evidence_dir),
        "reference_dir": str(reference_dir),
        "fastq": {"r1": str(r1_path), "r2": str(r2_path)},
        "vcf": bam_parse.get("vcf"),
        "derived_vcf": bam_parse.get("derived_vcf"),
        "reference_fasta": str(resolved_reference_fasta),
        "outputs": outputs,
        "steps": steps,
        "semantics": [
            "FASTQ is a raw read source; Genomi aligns it to a matching reference FASTA before any sample-specific lookup.",
            "The chosen aligner (minimap2 vs bwa-mem2) is recorded alongside the median sniffed read length so the call is auditable.",
            "The intermediate BAM follows the same `aligned_reads` semantics as a user-uploaded BAM.",
            "Derived variant calls depend on aligner choice, reference build, and variant-caller defaults; all are recorded in the manifest.",
            "Public evidence libraries are materialized lazily by focused tools after Active Genome Index creation.",
        ],
    }
