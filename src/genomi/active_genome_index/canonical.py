"""Active Genome Index-owned canonical source files.

After `genomi.parse_source` runs, every Active Genome Index owns a
canonical bgzip-compressed copy of the intake VCF at
`<agi_work_dir>/source/canonical.vcf.gz` (with a sibling `.gzi` BGZF index).

This canonical is the **only** path downstream capability tools are allowed
to read after parse. The user's intake source file is not re-opened.

The canonical is a strict bgzip recompression of the intake — same record
bytes, same header lines, no reordering. Downstream reads use BGZF virtual
offsets (block_address << 16 | within-block-offset) for O(log block)
random access via `pysam.libcbgzf.BGZFile`.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _bgzip_threads() -> int:
    # bgzip compression/reindexing parallelizes across threads; leave one core
    # for the decompressor in the pigz|bgzip pipe and the rest of the parse.
    return max(1, min(8, (os.cpu_count() or 1) - 1))

CANONICAL_SOURCE_DIRNAME = "source"
CANONICAL_VCF_FILENAME = "canonical.vcf.gz"
CANONICAL_GZI_FILENAME = "canonical.vcf.gz.gzi"


def canonical_source_dir(agi_work_dir: Path | str) -> Path:
    return Path(agi_work_dir) / CANONICAL_SOURCE_DIRNAME


def canonical_vcf_path(agi_work_dir: Path | str) -> Path:
    return canonical_source_dir(agi_work_dir) / CANONICAL_VCF_FILENAME


def canonical_gzi_path(agi_work_dir: Path | str) -> Path:
    return canonical_source_dir(agi_work_dir) / CANONICAL_GZI_FILENAME


def canonical_paths_for_active_genome_index(active_genome_index_path: Path | str) -> tuple[Path, Path]:
    """Return (canonical_path, gzi_path) keyed to a specific Active Genome Index file.

    The canonical lives next to the Active Genome Index it backs, named after
    that Active Genome Index so distinct Active Genome Index files that happen
    to share a parent directory get
    distinct canonical files. Used when `create_active_genome_index` is called directly
    against a plain VCF (the parse_source orchestrator routes through the
    Active Genome Index work dir's `source/` subdirectory instead).
    """

    active_genome_index_path = Path(active_genome_index_path)
    base = active_genome_index_path.stem
    sources = canonical_source_dir(active_genome_index_path.parent)
    return sources / f"{base}.canonical.vcf.gz", sources / f"{base}.canonical.vcf.gz.gzi"


def build_canonical_bgzip(
    intake_path: Path | str,
    agi_work_dir: Path | str,
    *,
    force: bool = False,
    canonical_path: Path | str | None = None,
    gzi_path: Path | str | None = None,
) -> dict[str, Any]:
    """Materialize the Active Genome Index-owned canonical bgzip VCF.

    Returns a dict with `canonical_path`, `gzi_path`, `status`
    ("completed" or "cached"). Safe to call repeatedly — re-uses an
    existing canonical when both the bgzip and its `.gzi` index are
    present, unless `force=True`. Optional `canonical_path` /
    `gzi_path` overrides let callers route distinct Active Genome Index files that share
    a parent directory to distinct canonicals.
    """

    intake_path = Path(intake_path).resolve()
    if not intake_path.exists():
        raise FileNotFoundError(intake_path)

    canonical_path = Path(canonical_path) if canonical_path is not None else canonical_vcf_path(agi_work_dir)
    gzi_path = Path(gzi_path) if gzi_path is not None else canonical_gzi_path(agi_work_dir)
    canonical_path.parent.mkdir(parents=True, exist_ok=True)

    if not force and canonical_path.exists() and gzi_path.exists():
        return {
            "status": "cached",
            "canonical_path": str(canonical_path),
            "gzi_path": str(gzi_path),
        }

    # A plain gzip intake is NOT bgzip (no random-access block structure), so
    # it must be decompressed and re-compressed through bgzip. But a true bgzip
    # intake (the common gVCF case) is already block-structured: we byte-copy it
    # and just (re)build the `.gzi` index — skipping the multi-minute recompress
    # of a multi-GB file.
    bgzip_exe = shutil.which("bgzip")
    if bgzip_exe is None:
        raise RuntimeError(
            "bgzip CLI not found on PATH; install htslib to build the Active Genome Index canonical bgzip VCF."
        )

    # Stage to a temp path and rename so a crashed parse never leaves a
    # half-written canonical that the schema_version check would mistake
    # for a complete Active Genome Index.
    tmp_canonical = canonical_path.with_suffix(canonical_path.suffix + ".tmp")
    tmp_gzi = gzi_path.with_suffix(gzi_path.suffix + ".tmp")
    for stale in (tmp_canonical, tmp_gzi):
        if stale.exists():
            stale.unlink()

    threads = _bgzip_threads()

    if _is_bgzip(intake_path):
        # Fast path: already bgzip. Copy the bytes verbatim (no recompress) and
        # build the .gzi block index over the copy.
        shutil.copyfile(intake_path, tmp_canonical)
        proc = subprocess.run(
            [bgzip_exe, "-@", str(threads), "--reindex", "--index-name", str(tmp_gzi), str(tmp_canonical)],
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"bgzip --reindex exited with rc={proc.returncode}")
        tmp_canonical.replace(canonical_path)
        tmp_gzi.replace(gzi_path)
        return {
            "status": "completed",
            "canonical_path": str(canonical_path),
            "gzi_path": str(gzi_path),
        }

    bgzip_cmd = [bgzip_exe, "-@", str(threads), "-c", "-i", "-I", str(tmp_gzi)]
    if _looks_like_gzip(intake_path):
        # gzip-compressed intake: decompress → bgzip. Prefer an all-subprocess
        # pipe (pigz > gzip) so no Python sits in the data path; fall back to
        # isal or stdlib gzip if no decompressor binary is found.
        decomp_cmd = shutil.which("pigz") or shutil.which("gzip")
        if decomp_cmd is not None:
            with tmp_canonical.open("wb") as out:
                decomp = subprocess.Popen(
                    [decomp_cmd, "-dc", str(intake_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                proc = subprocess.Popen(bgzip_cmd, stdin=decomp.stdout, stdout=out)
                assert decomp.stdout is not None
                decomp.stdout.close()
                try:
                    rc = proc.wait()
                    if rc != 0:
                        raise RuntimeError(f"bgzip exited with rc={rc}")
                finally:
                    if decomp.poll() is None:
                        decomp.terminate()
                    decomp.wait()
        else:
            try:
                from isal import igzip as _igzip
                source_ctx = _igzip.open(intake_path, "rb")
            except ImportError:
                source_ctx = gzip.open(intake_path, "rb")
            with source_ctx as source, tmp_canonical.open("wb") as out:  # type: ignore[arg-type]
                proc = subprocess.Popen(bgzip_cmd, stdin=subprocess.PIPE, stdout=out)
                try:
                    assert proc.stdin is not None
                    shutil.copyfileobj(source, proc.stdin)  # type: ignore[arg-type]
                    proc.stdin.close()
                finally:
                    rc = proc.wait()
                    if rc != 0:
                        raise RuntimeError(f"bgzip exited with rc={rc}")
    else:
        # Plain VCF: bgzip < intake > canonical
        with intake_path.open("rb") as source, tmp_canonical.open("wb") as out:
            proc = subprocess.run(bgzip_cmd, stdin=source, stdout=out, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"bgzip exited with rc={proc.returncode}")

    tmp_canonical.replace(canonical_path)
    tmp_gzi.replace(gzi_path)

    return {
        "status": "completed",
        "canonical_path": str(canonical_path),
        "gzi_path": str(gzi_path),
    }


def _looks_like_gzip(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(2) == b"\x1f\x8b"


def _is_bgzip(path: Path) -> bool:
    """True for a true BGZF (bgzip) file, not just plain gzip.

    A BGZF block begins with the gzip magic + CM=8 + FLG=4 (FEXTRA) and carries
    a "BC" extra subfield (SI1='B', SI2='C') at bytes 12-13. Plain gzip lacks
    the BC subfield and cannot be block-seeked, so it still needs recompression.
    """
    with path.open("rb") as handle:
        head = handle.read(16)
    return len(head) >= 14 and head[0:4] == b"\x1f\x8b\x08\x04" and head[12:14] == b"BC"
