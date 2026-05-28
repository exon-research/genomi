from __future__ import annotations

import gzip
import io
import zipfile
from pathlib import Path
from typing import TextIO


def _open_text_source(source_path: Path, *, member_name: str | None = None):
    if source_path.suffix.lower() == ".zip":
        archive = zipfile.ZipFile(source_path)
        member = member_name or _first_zip_text_member(source_path)
        if member is None:
            archive.close()
            raise ValueError(f"zip archive has no text genotype member: {source_path}")
        binary = archive.open(member)
        text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")

        class _ZipTextContext:
            def __enter__(self) -> TextIO:
                return text

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                text.close()
                binary.close()
                archive.close()

        return _ZipTextContext()
    if source_path.name.lower().endswith((".gz", ".bgz")):
        try:
            from isal import igzip as _igzip
            return _igzip.open(source_path, "rt", encoding="utf-8", errors="replace", newline="")
        except ImportError:
            pass
        return gzip.open(source_path, "rt", encoding="utf-8", errors="replace", newline="")
    return source_path.open("rt", encoding="utf-8", errors="replace", newline="")


def _first_zip_text_member(source_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(source_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename.lower().endswith((".txt", ".tsv", ".csv")):
                    return info.filename
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a readable zip archive: {source_path}") from exc
    return None


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
