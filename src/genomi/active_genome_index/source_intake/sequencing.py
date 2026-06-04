from __future__ import annotations

import shutil
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
)
from ...runtime.libraries import manager as library_manager
from ..alignment import (
    align_fastq_to_bam,
    detect_paired_fastq,
    infer_genome_build_from_bam,
    materialize_bam_variant_vcf,
    normalize_alignment_genome_build,
    paired_fastq_r1_name,
    paired_fastq_r2_name,
)
from .agi_store import JsonObject, _init_source_evidence_db
from .detection import SourceDetection
from .text_io import archive_member_names, open_archive_member_raw, open_genomic_binary
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
    genome_build: str = "auto",
    force: bool = False,
    max_records: int | None = None,
    parallel_workers: int | None = None,
) -> JsonObject:
    source_path = Path(source)
    detection = detection or SourceDetection(source_format="bam", source_kind="alignment_reads")
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
    bam_path = _materialize_bam_intake_if_needed(source_path, detection=detection, work_dir=work_dir, force=force)
    inferred_build = infer_genome_build_from_bam(bam_path)
    effective_build = normalize_alignment_genome_build(genome_build, inferred_build)

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
    if bam_path != source_path:
        steps.append(
            {
                "name": "materialize-bam-archive-member",
                "result": {
                    "status": "completed",
                    "source_member": detection.member_name,
                    "output": str(bam_path),
                },
                "reason": "Archive-backed BAM members are materialized to a local BAM path before header inspection and variant calling.",
            }
        )

    resolved_reference_fasta = Path(reference_fasta) if reference_fasta is not None else None
    if resolved_reference_fasta is None and auto_reference_fasta:
        dependency = library_manager.refresh(
            f"reference-{effective_build.lower()}", force=force
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
        bam_path,
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
    if materialized.get("status") == "requires_library_install":
        return {
            "workflow_area": "active-genome-index",
            "status": "requires_library_install",
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
            "reference_fasta": str(resolved_reference_fasta),
            "missing_libraries": materialized.get("missing_libraries", []),
            "message": materialized.get("message"),
            "steps": steps,
        }

    agi_result = _parse_vcf_active_genome_index(
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
            "result": agi_result,
            "reason": "The derived VCF is digitized into an Active Genome Index; public evidence tools materialize libraries later when needed.",
        }
    )
    outputs = dict(agi_result.get("outputs") or {})
    outputs["derived_vcf"] = str(derived_vcf)
    outputs["bam_variant_call_manifest"] = materialized.get("manifest_path")

    return {
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
        "derived_vcf": str(derived_vcf),
        "reference_fasta": str(resolved_reference_fasta),
        "outputs": outputs,
        "steps": steps,
    }


def _materialize_bam_intake_if_needed(
    source_path: Path,
    *,
    detection: SourceDetection,
    work_dir: Path,
    force: bool,
) -> Path:
    if detection.member_name is None:
        return source_path
    output = work_dir / "source" / "selected-archive-member.bam"
    return _materialize_archive_member(
        source_path,
        detection.member_name,
        output,
        force=force,
        preserve_container=True,
    )


def _resolve_fastq_pair(
    source_path: Path,
    *,
    detection: SourceDetection,
    work_dir: Path,
    force: bool,
) -> tuple[Path, Path]:
    if detection.member_name is None:
        pair = detect_paired_fastq(source_path)
        if pair is not None:
            return pair
        raise ValueError(
            f"FASTQ source must be a paired-end R1 file with an R2 sibling next to it: {source_path}. "
            "Name the inputs `<sample>_R1_*.fastq.gz` and `<sample>_R2_*.fastq.gz` (or `_1` / `_2`)."
        )

    r1_member = detection.member_name
    members = set(archive_member_names(source_path))
    r2_basename = paired_fastq_r2_name(r1_member)
    if r2_basename is None:
        r1_basename = paired_fastq_r1_name(r1_member)
        if r1_basename is None:
            raise ValueError(
                f"Archive FASTQ member must be an R1/R2 read with a recognized pair suffix: {detection.member_name}."
            )
        candidate_r1 = str(Path(r1_member).with_name(r1_basename))
        if candidate_r1 not in members:
            raise ValueError(
                f"FASTQ archive must contain an R1 member paired with {r1_member}; expected {candidate_r1}."
            )
        r2_member = r1_member
        r1_member = candidate_r1
    else:
        r2_member = str(Path(r1_member).with_name(r2_basename))
    if r2_member not in members:
        raise ValueError(
            f"FASTQ archive must contain an R2 member paired with {r1_member}; expected {r2_member}."
        )
    pair_dir = work_dir / "source" / "fastq-pair"
    r1_output = pair_dir / _decompressed_fastq_name(r1_member)
    r2_output = pair_dir / _decompressed_fastq_name(r2_member)
    return (
        _materialize_archive_member(source_path, r1_member, r1_output, force=force),
        _materialize_archive_member(source_path, r2_member, r2_output, force=force),
    )


def _materialize_archive_member(
    source_path: Path,
    member_name: str,
    output_path: Path,
    *,
    force: bool,
    preserve_container: bool = False,
) -> Path:
    if output_path.exists() and not force:
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    opener = open_archive_member_raw if preserve_container else open_genomic_binary
    with opener(source_path, member_name=member_name) as source, tmp.open("wb") as output:
        shutil.copyfileobj(source, output)
    tmp.replace(output_path)
    return output_path


def _decompressed_fastq_name(member_name: str) -> str:
    name = Path(member_name).name
    lowered = name.lower()
    for suffix in (".gz", ".bgz", ".bz2", ".xz"):
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if not name.lower().endswith((".fastq", ".fq")):
        name = f"{name}.fastq"
    return name


def parse_fastq_source(
    source: str | Path,
    *,
    detection: SourceDetection | None = None,
    evidence_db: str | Path | None = None,
    source_evidence_db: str | Path | None = None,
    shared_evidence_db: str | Path | None = None,
    reference_fasta: str | Path | None = None,
    auto_reference_fasta: bool = True,
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

    source_path = Path(source)
    detection = detection or SourceDetection(source_format="fastq", source_kind="paired_reads_input")

    effective_build = normalize_alignment_genome_build(genome_build, None)
    project_dir = run_project_dir_for_source(source_path, source_format="fastq")
    work_dir = run_work_dir_for_source(source_path, source_format="fastq")
    evidence_dir = run_evidence_dir_for_source(source_path, source_format="fastq")
    reference_dir = run_reference_dir_for_source(source_path, source_format="fastq")
    db_path = (
        Path(evidence_db)
        if evidence_db is not None
        else run_evidence_db_path_for_source(source_path, source_format="fastq")
    )
    shared_db = Path(shared_evidence_db) if shared_evidence_db is not None else shared_evidence_db_path()
    project_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    r1_path, r2_path = _resolve_fastq_pair(source_path, detection=detection, work_dir=work_dir, force=force)

    _init_source_evidence_db(
        db_path,
        source_path,
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
        dependency = library_manager.refresh(
            f"reference-{effective_build.lower()}", force=force
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

    derived_bam = run_output_path_for_source(source_path, "derived.aligned.bam", source_format="fastq")
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
            "workflow_area": "active-genome-index",
            "status": "requires_library_install",
            "source": str(source_path),
            "source_format": "fastq",
            "source_kind": detection.source_kind,
            "sample_slug": sample_slug_from_source(source_path, source_format="fastq"),
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
        "workflow_area": "active-genome-index",
        "status": "completed",
        "source": str(source_path),
        "source_format": "fastq",
        "source_kind": detection.source_kind,
        "sample_slug": sample_slug_from_source(source_path, source_format="fastq"),
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
        "derived_vcf": bam_parse.get("derived_vcf"),
        "reference_fasta": str(resolved_reference_fasta),
        "outputs": outputs,
        "steps": steps,
    }
