"""Content-based stream resolution for genome intake.

Every genome source reaches us as *some bytes on disk*. Those bytes may be a
bare file, or wrapped in one or more layers: single-file compression (gzip /
bzip2 / xz) or an archive (zip / tar, themselves possibly compressed). The file
name is an unreliable witness — WGS deliverables are routinely renamed, and PGP
public uploads arrive as ``.txt``, ``.zip``, ``.tar.gz``, ``.tsv.bz2`` with no
consistent convention.

This module is the one place that peels those layers. It decides the wrapping
from *content* (magic bytes for bare files, archive table-of-contents for
members) and hands callers a decompressed stream over the genomic payload —
binary for sniffing/parsers, or text for the line-oriented array/VCF readers.
Detection and the array parsers both go through here, so "look at the content,
not the name" is enforced in a single spot.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

# Magic-byte signatures for the single-file compressors we transparently peel.
_GZIP_MAGIC = b"\x1f\x8b"
_BZIP2_MAGIC = b"BZh"
_XZ_MAGIC = b"\xfd7zXZ\x00"

# Member names we never treat as the genomic payload of an archive: provider
# READMEs, manifests, web exports, and the macOS resource-fork sidecars zip
# tools love to add. Everything else competes on extension priority then size.
_ARCHIVE_JUNK_SUFFIXES = frozenset(
    {".pdf", ".html", ".htm", ".json", ".md", ".xml", ".log", ".png", ".jpg", ".jpeg", ".rtf", ".doc", ".docx"}
)
_ARCHIVE_JUNK_TOKENS = ("readme", "license", "licence", "manifest", "__macosx", "/._", "checksum", ".ds_store")

# Extension priority when an archive holds several files: a genomic payload wins
# over an incidental sidecar of the same size. Lower index = preferred.
_GENOMIC_MEMBER_SUFFIXES = (
    ".vcf",
    ".gvcf",
    ".var",
    ".mastervar",
    ".tsv",
    ".txt",
    ".csv",
    ".bam",
    ".cram",
    ".fastq",
    ".fq",
)


def _read_head(path: Path, size: int = 8) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _looks_like_zip(path: Path) -> bool:
    # is_zipfile reads the end-of-central-directory record, so an empty or
    # truncated file is correctly rejected.
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def _looks_like_tar(path: Path) -> bool:
    # is_tarfile transparently recognizes plain, gzip, bzip2, and xz tarballs.
    try:
        return tarfile.is_tarfile(path)
    except (OSError, tarfile.TarError):
        return False


def _compression_of(head: bytes) -> str | None:
    """Classify a *bare* file's single-file compression from its magic bytes."""
    if head.startswith(_GZIP_MAGIC):
        return "gzip"
    if head.startswith(_BZIP2_MAGIC):
        return "bzip2"
    if head.startswith(_XZ_MAGIC):
        return "xz"
    return None


def _is_archive(path: Path) -> bool:
    return _looks_like_zip(path) or _looks_like_tar(path)


def _member_is_junk(name: str) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in _ARCHIVE_JUNK_TOKENS):
        return True
    return any(lowered.endswith(suffix) for suffix in _ARCHIVE_JUNK_SUFFIXES)


def _member_priority(name: str) -> int:
    lowered = name.lower()
    # A member may itself be compressed (e.g. ``genome.txt.gz``); rank on the
    # name with any trailing compression suffix stripped.
    for compressed in (".gz", ".bgz", ".bz2", ".xz"):
        if lowered.endswith(compressed):
            lowered = lowered[: -len(compressed)]
            break
    for index, suffix in enumerate(_GENOMIC_MEMBER_SUFFIXES):
        if lowered.endswith(suffix):
            return index
    return len(_GENOMIC_MEMBER_SUFFIXES)


def _select_member(entries: list[tuple[str, int]]) -> str | None:
    """Pick the genomic payload from ``(name, size)`` archive entries.

    Prefer a recognized genomic extension, then the largest file — a real
    genotype/variant export dwarfs any incidental sidecar. Junk (READMEs,
    manifests, macOS forks) is excluded unless nothing else remains.
    """
    candidates = [(name, size) for name, size in entries if not _member_is_junk(name)]
    if not candidates:
        candidates = entries
    if not candidates:
        return None
    best = min(candidates, key=lambda item: (_member_priority(item[0]), -item[1]))
    return best[0]


def _archive_entries(path: Path) -> list[tuple[str, int]]:
    if _looks_like_zip(path):
        with zipfile.ZipFile(path) as archive:
            return [(info.filename, info.file_size) for info in archive.infolist() if not info.is_dir()]
    if _looks_like_tar(path):
        with tarfile.open(path) as archive:
            return [(member.name, member.size) for member in archive.getmembers() if member.isfile()]
    return []


def select_archive_member(path: Path) -> str | None:
    """Name of the genomic member inside ``path`` if it is an archive, else None."""
    if not _is_archive(path):
        return None
    return _select_member(_archive_entries(path))


def _wrap_member_compression(stream: BinaryIO, member_name: str) -> BinaryIO:
    """Peel a member's own compression, keyed on its (reliable, in-archive) name."""
    lowered = member_name.lower()
    if lowered.endswith((".gz", ".bgz")):
        return gzip.GzipFile(fileobj=stream)  # type: ignore[return-value]
    if lowered.endswith(".bz2"):
        return bz2.BZ2File(stream)  # type: ignore[return-value]
    if lowered.endswith(".xz"):
        return lzma.LZMAFile(stream)  # type: ignore[return-value]
    return stream


def _open_bare_compressed(path: Path, compression: str | None) -> BinaryIO:
    if compression == "gzip":
        try:
            from isal import igzip as _igzip

            return _igzip.open(path, "rb")  # type: ignore[return-value]
        except ImportError:
            return gzip.open(path, "rb")  # type: ignore[return-value]
    if compression == "bzip2":
        return bz2.open(path, "rb")  # type: ignore[return-value]
    if compression == "xz":
        return lzma.open(path, "rb")  # type: ignore[return-value]
    return path.open("rb")


@contextmanager
def open_genomic_binary(source_path: Path, *, member_name: str | None = None) -> Iterator[BinaryIO]:
    """Yield a decompressed binary stream over the genomic payload of ``source_path``.

    Peels, by content: zip / tar archives (selecting or honoring ``member_name``)
    and gzip / bzip2 / xz single-file compression. A bare, uncompressed file is
    streamed as-is. This is the single door through which both detection and the
    parsers reach raw bytes, so neither has to know how the file was packaged.
    """
    if _looks_like_zip(source_path):
        with zipfile.ZipFile(source_path) as archive:
            member = member_name or _select_member(
                [(i.filename, i.file_size) for i in archive.infolist() if not i.is_dir()]
            )
            if member is None:
                raise ValueError(f"zip archive has no genomic member: {source_path}")
            with archive.open(member) as raw:
                yield _wrap_member_compression(raw, member)  # type: ignore[arg-type]
        return
    if _looks_like_tar(source_path):
        with tarfile.open(source_path) as archive:
            member = member_name or _select_member(
                [(m.name, m.size) for m in archive.getmembers() if m.isfile()]
            )
            if member is None:
                raise ValueError(f"tar archive has no genomic member: {source_path}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"tar member is not a regular file: {member} in {source_path}")
            yield _wrap_member_compression(extracted, member)  # type: ignore[arg-type]
        return
    stream = _open_bare_compressed(source_path, _compression_of(_read_head(source_path)))
    try:
        yield stream
    finally:
        stream.close()


@contextmanager
def _open_text_source(source_path: Path, *, member_name: str | None = None) -> Iterator[TextIO]:
    """Yield a decoded text stream over the genomic payload (see ``open_genomic_binary``)."""
    with open_genomic_binary(source_path, member_name=member_name) as binary:
        text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")
        try:
            yield text
        finally:
            # Detach so the wrapper's own close does not re-close the stream the
            # binary context manager already owns.
            text.detach()

def _effective_array_build(requested: str, declared: str | None) -> str:
    normalized = (requested or "auto").strip()
    if normalized.lower() == "auto":
        return declared or "GRCh37"
    return normalized


def _clean_array_chrom(value: str) -> str:
    chrom = value.strip()
    if chrom in {"MT", "M"}:
        return "MT"
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    return chrom.upper() if chrom.upper() in {"X", "Y", "MT"} else chrom
