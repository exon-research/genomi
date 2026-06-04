from __future__ import annotations

import gzip
import re
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import Any

from ..runtime.external import (
    check_returncode,
    check_tool,
    file_metadata,
    matching_manifest,
    run_command,
    utc_now,
    write_manifest,
)
from ..runtime.paths import bwa_mem2_binary_path, minimap2_binary_path

JsonObject = dict[str, Any]

# Short-read aligners (bwa-mem2) outperform splice-aware aligners on Illumina-
# style reads up to roughly this length; above this we switch to minimap2 which
# handles long reads (PacBio HiFi, ONT) with much better gap modelling.
_SHORT_READ_LENGTH_CEILING = 200
_READ_LENGTH_SNIFF_COUNT = 200

_FASTQ_PAIR_TOKEN = re.compile(
    r"^(?P<stem>.+?)(?P<sep>[_.])(?P<marker>R?[12])(?P<suffix>(?:[_.][^/]*)?\.(?:fastq|fq)(?:\.gz|\.bgz)?)$",
    re.IGNORECASE,
)


def resolve_aligner_binary(name: str) -> str | None:
    """Return the absolute path to a Genomi-installed aligner, or PATH fallback.

    Looks first under ``<GENOMI_HOME>/tools/aligners/<name>/<name>`` so an
    install_for_agents-managed binary is preferred over whatever the host
    happens to have on PATH; falls back to PATH so users with a system install
    (e.g. ``brew install minimap2``) can still use the FASTQ pipeline.
    """

    if name == "minimap2":
        managed = minimap2_binary_path()
    elif name == "bwa-mem2":
        managed = bwa_mem2_binary_path()
    else:
        return shutil.which(name)
    if managed.is_file() and managed.stat().st_mode & 0o111:
        return str(managed)
    return shutil.which(name)


def sniff_fastq_read_length(fastq_path: Path, *, sample: int = _READ_LENGTH_SNIFF_COUNT) -> int | None:
    """Read up to *sample* sequences from a (possibly gzipped) FASTQ and return the median length."""

    opener = gzip.open if fastq_path.name.lower().endswith((".gz", ".bgz")) else open
    lengths: list[int] = []
    try:
        with opener(fastq_path, "rt", encoding="utf-8", errors="replace") as handle:
            while len(lengths) < sample:
                header = handle.readline()
                if not header:
                    break
                seq = handle.readline()
                plus = handle.readline()
                qual = handle.readline()
                if not seq or not plus or not qual:
                    break
                lengths.append(len(seq.rstrip("\r\n")))
    except OSError:
        return None
    if not lengths:
        return None
    return int(statistics.median(lengths))


def pick_aligner_for_reads(median_read_length: int | None) -> str:
    if median_read_length is None or median_read_length > _SHORT_READ_LENGTH_CEILING:
        return "minimap2"
    return "bwa-mem2"


def detect_paired_fastq(source_path: Path) -> tuple[Path, Path] | None:
    """Resolve a FASTQ R1 path to its (R1, R2) pair using the standard suffix convention.

    Accepts both the Illumina-style ``<sample>_R1_<lane>.fastq.gz`` and the
    plainer ``<sample>_1.fastq.gz`` naming. The R2 sibling must already exist
    next to the R1 input.
    """

    r2_name = paired_fastq_r2_name(source_path.name)
    if r2_name is None:
        return None
    r2_path = source_path.with_name(r2_name)
    if r2_path.exists():
        return (source_path, r2_path)
    return None


def paired_fastq_r2_name(r1_name: str) -> str | None:
    return _paired_fastq_name(r1_name, expected_marker={"R1", "1"}, target_marker="R2")


def paired_fastq_r1_name(r2_name: str) -> str | None:
    return _paired_fastq_name(r2_name, expected_marker={"R2", "2"}, target_marker="R1")


def _paired_fastq_name(name: str, *, expected_marker: set[str], target_marker: str) -> str | None:
    match = _FASTQ_PAIR_TOKEN.match(Path(name).name)
    if not match:
        return None
    marker = match.group("marker")
    marker_upper = marker.upper()
    if marker_upper not in expected_marker:
        return None
    if marker_upper in {"R1", "R2"}:
        replacement = target_marker
    else:
        replacement = target_marker[-1]
    return f"{match.group('stem')}{match.group('sep')}{replacement}{match.group('suffix')}"


def align_fastq_to_bam(
    r1: str | Path,
    r2: str | Path,
    reference_fasta: str | Path,
    output_bam: str | Path,
    *,
    aligner: str = "auto",
    threads: int = 4,
    force: bool = False,
) -> JsonObject:
    """Align a paired-end FASTQ to a sorted+indexed BAM using minimap2 or bwa-mem2.

    The chosen aligner depends on the median read length in *r1* unless
    ``aligner`` is set explicitly to ``"minimap2"`` or ``"bwa-mem2"``.
    Subprocess output (SAM on stdout) is piped to ``samtools sort`` for the
    final BAM. The function leaves a sidecar manifest at ``<output_bam>.genomi-manifest.json``
    so a re-run with the same inputs is cached.
    """

    r1_path = Path(r1)
    r2_path = Path(r2)
    reference_path = Path(reference_fasta)
    output_path = Path(output_bam)
    for required in (r1_path, r2_path, reference_path):
        if not required.exists():
            raise FileNotFoundError(required)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_suffix(output_path.suffix + ".genomi-manifest.json")

    median_read_length = sniff_fastq_read_length(r1_path)
    chosen = aligner if aligner != "auto" else pick_aligner_for_reads(median_read_length)
    if chosen not in {"minimap2", "bwa-mem2"}:
        raise ValueError(f"unsupported aligner: {chosen}")

    aligner_path = resolve_aligner_binary(chosen)
    samtools_path = shutil.which("samtools")
    missing: list[str] = []
    if aligner_path is None:
        missing.append(chosen)
    if samtools_path is None:
        missing.append("samtools")
    if missing:
        return {
            "status": "requires_library_install",
            "missing_libraries": [
                {
                    "binary": name,
                    "install_library": f"{name}-binary" if name in {"minimap2", "bwa-mem2"} else name,
                }
                for name in missing
            ],
            "message": (
                "FASTQ alignment requires "
                + ", ".join(missing)
                + ". Install the matching aligner library "
                "(wgs-alignment purpose) or place the binary on PATH."
            ),
        }

    expected = {
        "aligner": chosen,
        "median_read_length": median_read_length,
        "r1": file_metadata(r1_path),
        "r2": file_metadata(r2_path),
        "reference_fasta": file_metadata(reference_path),
        "output": str(output_path),
    }
    cached = matching_manifest(manifest_path, expected, required_paths=[output_path])
    if cached is not None and not force:
        return {
            "status": "cached",
            "aligner": chosen,
            "output": str(output_path),
            "manifest_path": str(manifest_path),
            "file": file_metadata(output_path),
        }

    if chosen == "minimap2":
        # ``-ax sr`` short-read preset; minimap2 picks the right scoring for
        # paired-end Illumina at <=200bp and also handles long-read input when
        # the dispatcher chooses minimap2 for >200bp medians.
        preset = "sr" if (median_read_length or 0) <= _SHORT_READ_LENGTH_CEILING else "map-ont"
        align_command = [
            aligner_path,
            "-ax",
            preset,
            "-t",
            str(threads),
            str(reference_path),
            str(r1_path),
            str(r2_path),
        ]
    else:  # bwa-mem2
        # Requires a prebuilt index. We accept either an existing index next
        # to the reference (`.bwt.2bit.64` sibling files) or build one in-place
        # before the first alignment. The build is deterministic and idempotent.
        _ensure_bwa_mem2_index(aligner_path, reference_path, threads=threads)
        align_command = [
            aligner_path,
            "mem",
            "-t",
            str(threads),
            str(reference_path),
            str(r1_path),
            str(r2_path),
        ]

    sort_command = [samtools_path, "sort", "-@", str(threads), "-o", str(output_path), "-"]
    aligner_proc = subprocess.Popen(align_command, stdout=subprocess.PIPE)
    try:
        assert aligner_proc.stdout is not None
        sorted_proc = subprocess.run(sort_command, stdin=aligner_proc.stdout, check=False)
        aligner_proc.stdout.close()
        align_returncode = aligner_proc.wait()
        if align_returncode != 0:
            raise RuntimeError(f"{chosen} failed with exit code {align_returncode}")
        if sorted_proc.returncode != 0:
            raise RuntimeError(f"samtools sort failed with exit code {sorted_proc.returncode}")
    finally:
        if aligner_proc.poll() is None:
            aligner_proc.kill()

    index_result = ensure_bam_index(output_path)
    payload = {
        **expected,
        "status": "completed",
        "created_at_utc": utc_now(),
        "aligner_path": aligner_path,
        "samtools_path": samtools_path,
        "align_command": align_command,
        "sort_command": sort_command,
        "bam_index": index_result,
        "file": file_metadata(output_path),
    }
    write_manifest(manifest_path, payload)
    return {
        "status": "completed",
        "aligner": chosen,
        "median_read_length": median_read_length,
        "output": str(output_path),
        "manifest_path": str(manifest_path),
        "bam_index": index_result,
        "file": payload["file"],
    }


def _ensure_bwa_mem2_index(bwa_mem2_path: str, reference_fasta: Path, *, threads: int) -> None:
    sentinel = reference_fasta.with_suffix(reference_fasta.suffix + ".bwt.2bit.64")
    if sentinel.exists():
        return
    result = run_command(
        [bwa_mem2_path, "index", "-t", str(threads), str(reference_fasta)],
        timeout=None,
    )
    check_returncode(result)


def build_bam_variant_call_commands(
    bam: str | Path,
    reference_fasta: str | Path,
    output_vcf: str | Path,
) -> list[list[str]]:
    """Return the deterministic bcftools commands used to derive variants from a BAM."""

    return [
        [
            "bcftools",
            "mpileup",
            "--fasta-ref",
            str(reference_fasta),
            "--output-type",
            "u",
            str(bam),
        ],
        [
            "bcftools",
            "call",
            "--multiallelic-caller",
            "--variants-only",
            "--output-type",
            "v",
            "--output",
            str(output_vcf),
        ],
    ]


def materialize_bam_variant_vcf(
    bam: str | Path,
    reference_fasta: str | Path,
    output_vcf: str | Path,
    *,
    force: bool = False,
) -> JsonObject:
    """Call observed variants from an alignment file into a VCF for Active Genome Index creation."""

    bam_path = Path(bam)
    reference_path = Path(reference_fasta)
    output_path = Path(output_vcf)
    if not bam_path.exists():
        raise FileNotFoundError(bam_path)
    if not reference_path.exists():
        raise FileNotFoundError(reference_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path.with_suffix(output_path.suffix + ".genomi-manifest.json")
    commands = build_bam_variant_call_commands(bam_path, reference_path, output_path)
    expected = {
        "dependency": "bam_derived_variant_vcf",
        "source_format": "bam",
        "bam": file_metadata(bam_path),
        "reference_fasta": file_metadata(reference_path),
        "output": str(output_path),
        "commands": commands,
    }
    cached = matching_manifest(manifest_path, expected, required_paths=[output_path])
    if cached is not None and not force:
        return {
            "status": "cached",
            "dependency": "bam_derived_variant_vcf",
            "source_format": "bam",
            "output": str(output_path),
            "manifest_path": str(manifest_path),
            "commands": commands,
            "file": file_metadata(output_path),
        }

    checks = [check_tool("samtools", ["--version"]), check_tool("bcftools", ["--version"])]
    missing = [check.name for check in checks if not check.available]
    if missing:
        return {
            "status": "requires_library_install",
            "dependency": "bam_derived_variant_vcf",
            "source_format": "bam",
            "missing_libraries": [
                {"binary": name, "install_library": name}
                for name in missing
            ],
            "message": (
                "BAM-derived variant calling requires "
                + ", ".join(missing)
                + ". Install the alignment/variant-calling tools or place the binaries on PATH."
            ),
            "tools": [check.to_dict() for check in checks],
        }
    quickcheck = run_command(["samtools", "quickcheck", "-v", str(bam_path)])
    check_returncode(quickcheck)
    index_result = ensure_bam_index(bam_path)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()
    mpileup_command, call_command = build_bam_variant_call_commands(bam_path, reference_path, temp_output)
    mpileup = subprocess.Popen(mpileup_command, stdout=subprocess.PIPE)
    try:
        assert mpileup.stdout is not None
        called = subprocess.run(call_command, stdin=mpileup.stdout, check=False)
        mpileup.stdout.close()
        mpileup_returncode = mpileup.wait()
        if mpileup_returncode != 0:
            raise RuntimeError(f"command failed with exit code {mpileup_returncode}: {' '.join(mpileup_command)}")
        if called.returncode != 0:
            raise RuntimeError(f"command failed with exit code {called.returncode}: {' '.join(call_command)}")
        temp_output.replace(output_path)
    finally:
        if mpileup.poll() is None:
            mpileup.kill()
        if temp_output.exists():
            temp_output.unlink()

    payload = {
        **expected,
        "status": "completed",
        "created_at_utc": utc_now(),
        "bam_index": index_result,
        "tools": [check.to_dict() for check in checks],
        "file": file_metadata(output_path),
    }
    write_manifest(manifest_path, payload)
    return {
        "status": "completed",
        "dependency": "bam_derived_variant_vcf",
        "source_format": "bam",
        "output": str(output_path),
        "manifest_path": str(manifest_path),
        "commands": commands,
        "bam_index": index_result,
        "file": payload["file"],
    }


def ensure_bam_index(bam: str | Path) -> JsonObject:
    bam_path = Path(bam)
    existing = _existing_bam_index(bam_path)
    if existing is not None:
        return {"status": "cached", "output": str(existing), "file": file_metadata(existing)}
    output = Path(f"{bam_path}.bai")
    result = run_command(["samtools", "index", str(bam_path), str(output)])
    check_returncode(result)
    return {"status": "completed", "output": str(output), "file": file_metadata(output), "command": result["command"]}


def infer_genome_build_from_bam(bam: str | Path) -> str | None:
    samtools = check_tool("samtools")
    if not samtools.available:
        return None
    try:
        completed = subprocess.run(
            [samtools.path or "samtools", "view", "-H", str(bam)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return infer_genome_build_from_bam_header(completed.stdout)


def infer_genome_build_from_bam_header(header_text: str) -> str | None:
    lowered = header_text.lower()
    if any(token in lowered for token in ("grch37", "hg19", "b37")):
        return "GRCh37"
    if any(token in lowered for token in ("grch38", "hg38", "b38")):
        return "GRCh38"
    if "sn:chr1" in lowered and "ln:248956422" in lowered:
        return "GRCh38"
    if "sn:1" in lowered and "ln:248956422" in lowered:
        return "GRCh38"
    if "sn:chr1" in lowered and "ln:249250621" in lowered:
        return "GRCh37"
    if "sn:1" in lowered and "ln:249250621" in lowered:
        return "GRCh37"
    return None


def normalize_alignment_genome_build(requested: str | None, inferred: str | None = None) -> str:
    value = (requested or "auto").strip()
    if value.lower() in {"", "auto"}:
        return inferred or "GRCh38"
    lowered = value.lower()
    if lowered in {"grch37", "hg19", "b37"}:
        return "GRCh37"
    if lowered in {"grch38", "hg38", "b38"}:
        return "GRCh38"
    raise ValueError(f"unsupported genome build: {requested}")


def _existing_bam_index(bam_path: Path) -> Path | None:
    candidates = [Path(f"{bam_path}.bai"), bam_path.with_suffix(".bai")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
