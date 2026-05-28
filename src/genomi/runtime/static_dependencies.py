from __future__ import annotations

import contextlib
import gzip
import os
import shutil
import time
import urllib.request
from pathlib import Path
from typing import Any

from ..active_genome_index.vcf import read_header
from .external import file_metadata, read_manifest, utc_now, write_manifest
from .paths import genomi_data_root, run_reference_dir, shared_reference_dir

CLINVAR_DOWNLOAD_URLS = {
    "GRCh37": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh37/clinvar.vcf.gz",
    "GRCh38": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz",
}

REFERENCE_FASTA_DOWNLOAD_URLS = {
    "GRCh37": "https://hgdownload.soe.ucsc.edu/goldenPath/hg19/bigZips/latest/hg19.fa.gz",
    "GRCh38": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/latest/hg38.fa.gz",
}

REFERENCE_FASTA_FILENAMES = {
    "GRCh37": "hg19.fa",
    "GRCh38": "hg38.fa",
}


def resolve_genome_build(vcf: str | Path, requested: str | None) -> str:
    requested_normalized = (requested or "auto").strip()
    if requested_normalized.lower() not in {"", "auto"}:
        return _normalize_genome_build(requested_normalized)
    return infer_genome_build_from_vcf(vcf) or "GRCh38"


def infer_genome_build_from_vcf(vcf: str | Path) -> str | None:
    try:
        header = read_header(vcf)
    except Exception:
        return None
    text = " ".join(
        value or ""
        for value in [
            header.first_meta_value("reference"),
            header.first_meta_value("referenceInfo"),
            header.first_meta_value("assembly"),
        ]
    ).lower()
    if any(token in text for token in ["grch37", "hg19", "g1k.37", "b37"]):
        return "GRCh37"
    if any(token in text for token in ["grch38", "hg38", "grch38.p", "b38"]):
        return "GRCh38"
    contigs = header.contigs()
    if contigs and any(contig.startswith("chr") for contig in contigs[:24]):
        return "GRCh38"
    return None


def ensure_clinvar_vcf(
    vcf: str | Path,
    *,
    genome_build: str,
    force: bool = False,
    source_url: str | None = None,
) -> dict[str, Any]:
    build = _normalize_genome_build(genome_build)
    url = source_url or CLINVAR_DOWNLOAD_URLS[build]
    if not force:
        cached_shared = _cached_clinvar_payload(
            output=shared_clinvar_vcf_path(build),
            manifest_path=shared_clinvar_vcf_manifest_path(build),
            source_url=url,
            build=build,
        )
        if cached_shared is not None:
            return cached_shared
    output_dir = run_reference_dir(vcf) / f"clinvar_{build}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "clinvar.vcf.gz"
    manifest_path = output.with_suffix(output.suffix + ".genomi-manifest.json")
    expected = {
        "dependency": "clinvar_vcf",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
    }
    manifest = read_manifest(manifest_path)
    if (
        not force
        and output.exists()
        and manifest is not None
        and all(manifest.get(key) == value for key, value in expected.items())
    ):
        return {
            "status": "cached",
            "dependency": "clinvar_vcf",
            "genome_build": build,
            "source_url": url,
            "output": str(output),
            "manifest_path": str(manifest_path),
            "file": file_metadata(output),
        }

    temp_output = output.with_suffix(output.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp_output.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temp_output.replace(output)
    finally:
        if temp_output.exists():
            temp_output.unlink()

    payload = {
        **expected,
        "status": "completed",
        "downloaded_at_utc": utc_now(),
        "file": file_metadata(output),
    }
    write_manifest(manifest_path, payload)
    return {
        "status": "completed",
        "dependency": "clinvar_vcf",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
        "manifest_path": str(manifest_path),
        "file": payload["file"],
    }


def ensure_shared_clinvar_vcf(
    *,
    genome_build: str,
    force: bool = False,
    source_url: str | None = None,
) -> dict[str, Any]:
    build = _normalize_genome_build(genome_build)
    url = source_url or CLINVAR_DOWNLOAD_URLS[build]
    output = shared_clinvar_vcf_path(build)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = shared_clinvar_vcf_manifest_path(build)
    cached = (
        None
        if force
        else _cached_clinvar_payload(
            output=output,
            manifest_path=manifest_path,
            source_url=url,
            build=build,
        )
    )
    if cached is not None:
        return cached

    temp_output = output.with_suffix(output.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp_output.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temp_output.replace(output)
    finally:
        if temp_output.exists():
            temp_output.unlink()

    payload = {
        "dependency": "clinvar_vcf",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
        "status": "completed",
        "downloaded_at_utc": utc_now(),
        "file": file_metadata(output),
    }
    write_manifest(manifest_path, payload)
    return {
        "status": "completed",
        "dependency": "clinvar_vcf",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
        "manifest_path": str(manifest_path),
        "file": payload["file"],
    }


def shared_clinvar_vcf_path(genome_build: str) -> Path:
    build = _normalize_genome_build(genome_build)
    return genomi_data_root() / "resources" / "clinvar" / build / "clinvar.vcf.gz"


def shared_clinvar_vcf_manifest_path(genome_build: str) -> Path:
    output = shared_clinvar_vcf_path(genome_build)
    return output.with_suffix(output.suffix + ".genomi-manifest.json")


def _cached_clinvar_payload(
    *,
    output: Path,
    manifest_path: Path,
    source_url: str,
    build: str,
) -> dict[str, Any] | None:
    expected = {
        "dependency": "clinvar_vcf",
        "genome_build": build,
        "source_url": source_url,
        "output": str(output),
    }
    manifest = read_manifest(manifest_path)
    if (
        output.exists()
        and manifest is not None
        and all(manifest.get(key) == value for key, value in expected.items())
    ):
        return {
            "status": "cached",
            "dependency": "clinvar_vcf",
            "genome_build": build,
            "source_url": source_url,
            "output": str(output),
            "manifest_path": str(manifest_path),
            "file": file_metadata(output),
        }
    return None


def ensure_reference_fasta(
    *,
    genome_build: str,
    root: str | Path | None = None,
    force: bool = False,
    source_url: str | None = None,
) -> dict[str, Any]:
    build = _normalize_genome_build(genome_build)
    url = source_url or REFERENCE_FASTA_DOWNLOAD_URLS[build]
    output_dir = (Path(root).expanduser() if root is not None else shared_reference_dir()) / build
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / REFERENCE_FASTA_FILENAMES[build]
    fai = Path(f"{output}.fai")
    manifest_path = output.with_suffix(output.suffix + ".genomi-manifest.json")
    expected = {
        "dependency": "reference_fasta",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
    }
    manifest = read_manifest(manifest_path)
    cached = _cached_reference_fasta_payload(
        output=output,
        fai=fai,
        manifest_path=manifest_path,
        manifest=manifest,
        expected=expected,
        source_url=url,
        build=build,
    )
    # Reference FASTAs are immutable dependencies. A run-level --force should
    # rerun sample artifacts, not redownload a valid multi-GB FASTA.
    if cached is not None:
        return cached

    lock_path = output_dir / f"{REFERENCE_FASTA_FILENAMES[build]}.lock"
    with _file_lock(lock_path):
        manifest = read_manifest(manifest_path)
        cached = _cached_reference_fasta_payload(
            output=output,
            fai=fai,
            manifest_path=manifest_path,
            manifest=manifest,
            expected=expected,
            source_url=url,
            build=build,
        )
        if cached is not None:
            return cached

        token = f"{os.getpid()}.{int(time.time() * 1000)}"
        compressed = output.with_suffix(output.suffix + f".{token}.gz.tmp")
        temp_output = output.with_suffix(output.suffix + f".{token}.tmp")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, compressed.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            with gzip.open(compressed, "rb") as source, temp_output.open("wb") as target:
                shutil.copyfileobj(source, target)
            temp_output.replace(output)
            _write_fasta_index(output, fai)
        finally:
            if compressed.exists():
                compressed.unlink()
            if temp_output.exists():
                temp_output.unlink()

    payload = {
        **expected,
        "status": "completed",
        "downloaded_at_utc": utc_now(),
        "fai": str(fai),
        "file": file_metadata(output),
    }
    write_manifest(manifest_path, payload)
    return {
        "status": "completed",
        "dependency": "reference_fasta",
        "genome_build": build,
        "source_url": url,
        "output": str(output),
        "fai": str(fai),
        "manifest_path": str(manifest_path),
        "file": payload["file"],
    }


def _cached_reference_fasta_payload(
    *,
    output: Path,
    fai: Path,
    manifest_path: Path,
    manifest: dict[str, Any] | None,
    expected: dict[str, Any],
    source_url: str,
    build: str,
) -> dict[str, Any] | None:
    if (
        output.exists()
        and fai.exists()
        and manifest is not None
        and all(manifest.get(key) == value for key, value in expected.items())
    ):
        return {
            "status": "cached",
            "dependency": "reference_fasta",
            "genome_build": build,
            "source_url": source_url,
            "output": str(output),
            "fai": str(fai),
            "manifest_path": str(manifest_path),
            "file": file_metadata(output),
        }
    return None


class _file_lock:
    def __init__(self, path: Path, *, timeout_seconds: int = 7200) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.fd: int | None = None

    def __enter__(self) -> _file_lock:
        started = time.monotonic()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError as exc:
                if time.monotonic() - started > self.timeout_seconds:
                    raise TimeoutError(f"timed out waiting for reference FASTA lock: {self.path}") from exc
                time.sleep(2)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def _write_fasta_index(fasta: Path, output: Path) -> None:
    rows: list[str] = []
    current_name: str | None = None
    current_length = 0
    current_offset = 0
    line_bases = 0
    line_width = 0

    def flush() -> None:
        nonlocal current_name, current_length, current_offset, line_bases, line_width
        if current_name is None:
            return
        rows.append(f"{current_name}\t{current_length}\t{current_offset}\t{line_bases}\t{line_width}\n")

    with fasta.open("rb") as handle:
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line:
                break
            if line.startswith(b">"):
                flush()
                current_name = line[1:].split(None, 1)[0].decode("ascii", errors="replace")
                current_length = 0
                current_offset = handle.tell()
                line_bases = 0
                line_width = 0
                continue
            bases = line.rstrip(b"\r\n")
            if current_name is None or not bases:
                continue
            if line_bases == 0:
                line_bases = len(bases)
                line_width = len(line)
            current_length += len(bases)
            if current_offset == 0:
                current_offset = offset
        flush()
    output.write_text("".join(rows), encoding="utf-8")


def _normalize_genome_build(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"grch37", "hg19", "37"}:
        return "GRCh37"
    if normalized in {"grch38", "hg38", "38"}:
        return "GRCh38"
    raise ValueError(f"unsupported genome build for static dependencies: {value}")
