"""Bounded, private staging for the portal's VCF/gVCF intake lane."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from ..runtime.private_storage import ensure_private_directory
from .service_errors import LabError

DEFAULT_UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024
SUPPORTED_UPLOAD_SUFFIXES = (".g.vcf", ".gvcf", ".vcf")
_SAFE_UPLOAD_NAME = re.compile(r"^[^/\\\x00]+$")


def stage_vcf_upload(
    *,
    intake_root: Path,
    private_root: Path,
    profile_id: str,
    filename: str,
    stream: BinaryIO,
    content_length: int,
    upload_limit_bytes: int,
) -> tuple[Path, str]:
    suffix = _validated_upload_suffix(filename)
    if content_length <= 0:
        raise LabError("empty_upload", "Choose a non-empty VCF or gVCF file.")
    if content_length > upload_limit_bytes:
        raise LabError(
            "upload_too_large",
            "This developer preview accepts files up to "
            f"{upload_limit_bytes // (1024 * 1024)} MiB.",
            http_status=413,
        )
    staged_name = f"{uuid.uuid4().hex}{suffix}"
    profile_root = ensure_private_directory(
        intake_root / profile_id, private_root=private_root
    )
    final_path = profile_root / staged_name
    partial_path = profile_root / f".{staged_name}.part"
    descriptor = os.open(
        partial_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    remaining = content_length
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise LabError(
                        "incomplete_upload",
                        "The upload ended before its declared size.",
                    )
                output.write(chunk)
                remaining -= len(chunk)
            output.flush()
            os.fsync(output.fileno())
        _validate_vcf_header(partial_path)
        os.replace(partial_path, final_path)
        final_path.chmod(0o600)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            partial_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return final_path, staged_name


def _validated_upload_suffix(filename: str) -> str:
    if not isinstance(filename, str) or not _SAFE_UPLOAD_NAME.fullmatch(filename):
        raise LabError("invalid_filename", "The selected file name is not valid.")
    lower = filename.lower()
    for suffix in SUPPORTED_UPLOAD_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    if lower.endswith((".gz", ".zip")):
        raise LabError(
            "compressed_upload_not_supported",
            "Use an uncompressed VCF or gVCF in this developer preview.",
        )
    raise LabError(
        "unsupported_genome_file", "Choose a .vcf, .g.vcf, or .gvcf file."
    )


def _validate_vcf_header(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(256 * 1024)
    except OSError as exc:
        raise LabError("upload_unreadable", "The uploaded file could not be read.") from exc
    if prefix.startswith(b"\x1f\x8b"):
        raise LabError(
            "compressed_upload_not_supported",
            "Use an uncompressed VCF or gVCF in this developer preview.",
        )
    if not prefix.startswith(b"##fileformat=VCF") or b"#CHROM" not in prefix:
        raise LabError("invalid_vcf", "The file does not have a valid VCF header.")
