from __future__ import annotations

import gzip
import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

GENOMI_HOME_ENV = "GENOMI_HOME"
GENOMI_SHARED_EVIDENCE_DB_ENV = "GENOMI_SHARED_EVIDENCE_DB"
DEFAULT_GENOMI_HOME = Path.home() / ".genomi"
GENOMI_DATA_ROOT = DEFAULT_GENOMI_HOME
WORKSPACE_DATA_ROOT_NAME = ".genomi-data"
WORK_DIR_NAME = "work"
EVIDENCE_DIR_NAME = "evidence"
REFERENCE_DIR_NAME = "reference"
EVIDENCE_DB_NAME = "evidence.sqlite"
SHARED_EVIDENCE_DB_NAME = "shared-evidence.sqlite"
VCF_CONTENT_HASH_PREFIX = "vcf-sha256"
SOURCE_CONTENT_HASH_PREFIX = "source-sha256"
HASH_CHUNK_SIZE = 8 * 1024 * 1024

_VCF_EXTENSIONS = (".vcf.gz", ".g.vcf.gz", ".gvcf.gz", ".vcf")
_SOURCE_EXTENSIONS = (*_VCF_EXTENSIONS, ".bam", ".txt", ".zip", ".csv", ".tsv")
_PIPELINE_SUFFIXES = {
    "filtered",
    "hard-filtered",
    "hard_filtered",
    "g",
    "gvcf",
    "nochr",
    "norm",
    "normalized",
    "pass",
    "primary",
    "variant",
    "variants",
}
_GENERIC_FILE_SLUGS = {
    "g",
    "gvcf",
    "hard-filtered",
    "sample",
    "sample1",
    "variants",
    "vcf",
}


def genomi_data_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    configured = os.environ.get(GENOMI_HOME_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_GENOMI_HOME


def genomi_tools_dir(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "tools"


def pharmcat_install_dir(root: str | Path | None = None) -> Path:
    return genomi_tools_dir(root) / "pharmcat"


def pharmcat_jar_path(root: str | Path | None = None) -> Path:
    return pharmcat_install_dir(root) / "pharmcat.jar"


def pharmcat_manifest_path(root: str | Path | None = None) -> Path:
    return pharmcat_install_dir(root) / "manifest.json"


def aligner_install_dir(root: str | Path | None = None) -> Path:
    """Directory that holds Genomi-managed read-alignment binaries.

    Each aligner (minimap2, bwa-mem2) lives in its own subdirectory and is
    pinned to a single release version recorded in `manifest.json`.
    """

    return genomi_tools_dir(root) / "aligners"


def minimap2_install_dir(root: str | Path | None = None) -> Path:
    return aligner_install_dir(root) / "minimap2"


def minimap2_binary_path(root: str | Path | None = None) -> Path:
    return minimap2_install_dir(root) / "minimap2"


def bwa_mem2_install_dir(root: str | Path | None = None) -> Path:
    return aligner_install_dir(root) / "bwa-mem2"


def bwa_mem2_binary_path(root: str | Path | None = None) -> Path:
    return bwa_mem2_install_dir(root) / "bwa-mem2"


def sample_slug_from_vcf(vcf_path: str | Path) -> str:
    """Return the stable Genomi project slug for a VCF-derived run.

    Real VCF/gVCF intake files are keyed by exact file content so repeated
    repeated agent sessions reuse the same digitized artifact directory
    regardless of the task run directory or source filename.
    """

    path = Path(vcf_path)
    existing_project_dir = enclosing_project_dir(path)
    if existing_project_dir is not None:
        return existing_project_dir.name

    content_hash = vcf_content_hash(path)
    if content_hash:
        return f"{VCF_CONTENT_HASH_PREFIX}-{content_hash}"

    header_sample = _first_sample_from_header(path)
    sample_slug = _slugify(header_sample) if header_sample else ""
    if sample_slug and sample_slug not in _GENERIC_FILE_SLUGS:
        return sample_slug

    file_slug = _slug_from_filename(path)
    if file_slug and file_slug not in _GENERIC_FILE_SLUGS:
        return file_slug
    if sample_slug:
        return sample_slug
    if file_slug:
        return file_slug
    return "sample"


def sample_slug_from_source(source_path: str | Path, *, source_format: str | None = None) -> str:
    """Return the stable Genomi project slug for any supported genome source."""

    if source_format in {"vcf", "gvcf"} or _looks_like_vcf_name(Path(source_path).name):
        return sample_slug_from_vcf(source_path)

    path = Path(source_path)
    existing_project_dir = enclosing_project_dir(path)
    if existing_project_dir is not None:
        return existing_project_dir.name

    content_hash = vcf_content_hash(path)
    if content_hash:
        prefix = _slugify(source_format) if source_format else SOURCE_CONTENT_HASH_PREFIX
        if not prefix.endswith("sha256"):
            prefix = f"{prefix}-sha256"
        return f"{prefix}-{content_hash}"

    file_slug = _source_slug_from_filename(path)
    return file_slug or "sample"


def vcf_content_hash(vcf_path: str | Path) -> str | None:
    path = Path(vcf_path).expanduser()
    if not path.is_file():
        return None
    resolved = path.resolve(strict=False)
    try:
        stat = resolved.stat()
    except OSError:
        return None
    return _cached_file_sha256(str(resolved), stat.st_size, stat.st_mtime_ns)


def run_work_dir(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_project_dir(vcf_path, root=root) / WORK_DIR_NAME


def run_work_dir_for_source(source_path: str | Path, *, source_format: str | None = None, root: str | Path | None = None) -> Path:
    return run_project_dir_for_source(source_path, source_format=source_format, root=root) / WORK_DIR_NAME


def run_project_dir(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    existing_project_dir = enclosing_project_dir(vcf_path, root=root)
    if existing_project_dir is not None:
        return existing_project_dir
    return genomi_data_root(root) / sample_slug_from_vcf(vcf_path)


def run_project_dir_for_source(source_path: str | Path, *, source_format: str | None = None, root: str | Path | None = None) -> Path:
    existing_project_dir = enclosing_project_dir(source_path, root=root)
    if existing_project_dir is not None:
        return existing_project_dir
    return genomi_data_root(root) / sample_slug_from_source(source_path, source_format=source_format)


def run_evidence_dir(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_project_dir(vcf_path, root=root) / EVIDENCE_DIR_NAME


def run_evidence_dir_for_source(source_path: str | Path, *, source_format: str | None = None, root: str | Path | None = None) -> Path:
    return run_project_dir_for_source(source_path, source_format=source_format, root=root) / EVIDENCE_DIR_NAME


def run_reference_dir(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_project_dir(vcf_path, root=root) / REFERENCE_DIR_NAME


def run_reference_dir_for_source(source_path: str | Path, *, source_format: str | None = None, root: str | Path | None = None) -> Path:
    return run_project_dir_for_source(source_path, source_format=source_format, root=root) / REFERENCE_DIR_NAME


def run_evidence_db_path(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    return run_evidence_dir(vcf_path, root=root) / EVIDENCE_DB_NAME


def run_evidence_db_path_for_source(source_path: str | Path, *, source_format: str | None = None, root: str | Path | None = None) -> Path:
    return run_evidence_dir_for_source(source_path, source_format=source_format, root=root) / EVIDENCE_DB_NAME


def shared_evidence_db_path(root: str | Path | None = None) -> Path:
    if root is None:
        configured = os.environ.get(GENOMI_SHARED_EVIDENCE_DB_ENV)
        if configured:
            return Path(configured).expanduser()
    return genomi_data_root(root) / SHARED_EVIDENCE_DB_NAME


def shared_reference_dir(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / REFERENCE_DIR_NAME


def shared_ancestry_reference_dir(root: str | Path | None = None) -> Path:
    return shared_reference_dir(root) / "ancestry"


def ancestry_reference_panel_dir(panel_id: str = "1000g_30x_grch38", root: str | Path | None = None) -> Path:
    return shared_ancestry_reference_dir(root) / panel_id


def shared_prs_reference_dir(root: str | Path | None = None) -> Path:
    return shared_reference_dir(root) / "prs"


def prs_score_dir(score_id: str, genome_build: str = "GRCh38", root: str | Path | None = None) -> Path:
    clean_score = _slugify(score_id) or "custom"
    clean_build = _slugify(genome_build) or "grch38"
    return shared_prs_reference_dir(root) / clean_score.upper() / clean_build.upper()


def run_output_path(vcf_path: str | Path, filename: str, root: str | Path | None = None) -> Path:
    return run_work_dir(vcf_path, root=root) / filename


def run_output_path_for_source(
    source_path: str | Path,
    filename: str,
    *,
    source_format: str | None = None,
    root: str | Path | None = None,
) -> Path:
    return run_work_dir_for_source(source_path, source_format=source_format, root=root) / filename


def enclosing_work_dir(path: str | Path, root: str | Path | None = None) -> Path | None:
    project_dir = enclosing_project_dir(path, root=root)
    if project_dir is None:
        return None
    return project_dir / WORK_DIR_NAME


def enclosing_project_dir(path: str | Path, root: str | Path | None = None) -> Path | None:
    path_obj = Path(path).expanduser()
    resolved_path = path_obj.resolve(strict=False)
    root = genomi_data_root(root).resolve(strict=False)
    try:
        parts = resolved_path.relative_to(root).parts
    except ValueError:
        pass
    else:
        if len(parts) >= 3 and parts[1] in {WORK_DIR_NAME, EVIDENCE_DIR_NAME, REFERENCE_DIR_NAME}:
            return root / parts[0]

    parts = path_obj.parts
    for index, part in enumerate(parts[:-2]):
        if part not in {DEFAULT_GENOMI_HOME.name, WORKSPACE_DATA_ROOT_NAME}:
            continue
        subdir_index = index + 2
        if parts[subdir_index] in {WORK_DIR_NAME, EVIDENCE_DIR_NAME, REFERENCE_DIR_NAME}:
            return Path(*parts[: subdir_index])
    return None


def default_export_variants_path(
    vcf_path: str | Path,
    *,
    pass_only: bool = True,
    primary_contigs_only: bool = False,
    chrom_style: str = "input",
    root: str | Path | None = None,
) -> Path:
    pieces: list[str] = []
    if pass_only:
        pieces.append("pass")
    if primary_contigs_only:
        pieces.append("primary")
    if chrom_style in {"no-chr", "chr"}:
        pieces.append("nochr" if chrom_style == "no-chr" else "chr")
    pieces.append("variants")
    return run_output_path(vcf_path, ".".join(pieces) + ".vcf", root=root)


def default_normalized_path_for_vcf(vcf_path: str | Path, root: str | Path | None = None) -> Path:
    path = Path(vcf_path)
    work_dir = run_work_dir(path, root=root)
    stem = _normalized_output_stem(path)
    return work_dir / f"{stem}.normalized.vcf.gz"


def _normalized_output_stem(path: Path) -> str:
    name = path.name
    for extension in _VCF_EXTENSIONS:
        if name.lower().endswith(extension):
            name = name[: -len(extension)]
            break
    pieces = [piece for piece in re.split(r"[._]+", name) if piece]
    normalized_suffixes = {"filtered", "g", "gvcf", "hard-filtered", "hard_filtered", "variant", "variants"}
    while len(pieces) > 1 and _slugify(pieces[-1]) in normalized_suffixes:
        pieces.pop()
    stem = ".".join(slug for piece in pieces if (slug := _slugify(piece)))
    return stem or sample_slug_from_vcf(path)


def _slug_from_filename(path: Path) -> str:
    name = path.name
    lowered = name.lower()
    for extension in _VCF_EXTENSIONS:
        if lowered.endswith(extension):
            name = name[: -len(extension)]
            break
    pieces = [piece for piece in name.split(".") if piece]
    while pieces and _slugify(pieces[-1]) in _PIPELINE_SUFFIXES:
        pieces.pop()
    return _slugify(".".join(pieces))


def _source_slug_from_filename(path: Path) -> str:
    name = path.name
    lowered = name.lower()
    for extension in _SOURCE_EXTENSIONS:
        if lowered.endswith(extension):
            name = name[: -len(extension)]
            break
    return _slugify(name)


def _looks_like_vcf_name(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(extension) for extension in _VCF_EXTENSIONS)


def _first_sample_from_header(path: Path) -> str | None:
    if not path.exists():
        return None
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("#CHROM"):
                    columns = line.rstrip("\r\n").split("\t")
                    return columns[9] if len(columns) > 9 else None
                if not line.startswith("#"):
                    return None
    except OSError:
        return None
    return None


@lru_cache(maxsize=256)
def _cached_file_sha256(path: str, size: int, mtime_ns: int) -> str | None:
    del size, mtime_ns
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _slugify(value: str | None) -> str:
    if value is None:
        return ""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug
