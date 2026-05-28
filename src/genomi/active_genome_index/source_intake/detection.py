from __future__ import annotations

import csv
import gzip
import re
from dataclasses import dataclass
from pathlib import Path

from .text_io import _first_zip_text_member, _open_text_source

_VCF_EXTENSIONS = (".vcf", ".vcf.gz", ".g.vcf.gz", ".gvcf.gz")
_BAM_EXTENSIONS = (".bam",)
_FASTQ_EXTENSIONS = (".fastq", ".fq", ".fastq.gz", ".fq.gz", ".fastq.bgz")


@dataclass(frozen=True)
class SourceDetection:
    source_format: str
    source_kind: str
    reference_build: str | None = None
    member_name: str | None = None
    provider: str | None = None


# Provider tags surfaced for VCF deliverables from named sequencing services.
# Detected from VCF header substrings; informational only — the canonical
# parsing path is still the generic VCF Active Genome Index builder.
_VCF_PROVIDER_SIGNATURES: tuple[tuple[str, str, str], ...] = (
    ("##source=Sequencing.com", "sequencingdotcom", "GRCh38"),
    ("##dataAnalysisProvider=Sequencing.com", "sequencingdotcom", "GRCh38"),
    ("##DRAGENCommandLine=<ID=dragen", "dantelabs", "GRCh37"),
    ("##reference=file:///references/grch37/reference.bin", "dantelabs", "GRCh37"),
    ("MegaBOLT_scheduler", "nebula", "GRCh38"),
)
_NEBULA_SAMPLE_PATTERN = re.compile(r"^NG1[A-Z0-9]+$")


def detect_source(source: str | Path) -> SourceDetection:
    """Detect the genome source format from a file path.

    Inspects the file's extension, magic bytes, and content to classify it as
    one of VCF, gVCF, BAM, 23andMe raw genotype text/zip, or AncestryDNA raw
    genotype text/zip. Callers do not supply the format; if you already know
    the format, you do not need this function.
    """
    source_path = Path(source)
    if _looks_like_vcf(source_path):
        provider, reference_build = _detect_vcf_provider(source_path)
        return SourceDetection(
            source_format="gvcf" if "gvcf" in source_path.name.lower() else "vcf",
            source_kind="variant_callset",
            reference_build=reference_build,
            provider=provider,
        )
    if _looks_like_bam(source_path):
        return SourceDetection(source_format="bam", source_kind="alignment_reads")
    if _looks_like_fastq(source_path):
        # Paired-end deliverables from Nebula / Dante / Sequencing.com are the
        # primary use case. We accept the R1 path and let `parse_fastq_source`
        # resolve the R2 sibling at parse time so the SourceDetection layer
        # stays cheap.
        return SourceDetection(
            source_format="fastq",
            source_kind="paired_reads_input",
            reference_build=None,
        )
    for detector in (
        _detect_23andme,
        _detect_ancestrydna,
        _detect_myheritage,
        _detect_livingdna,
        _detect_ftdna,
    ):
        try:
            return detector(source_path)
        except ValueError:
            continue
    raise ValueError(
        "Could not detect the genome source type. Supported sources: VCF/gVCF, BAM, "
        "paired-end FASTQ, and raw genotype exports from 23andMe, AncestryDNA, "
        "MyHeritage, FamilyTreeDNA (Family Finder), and Living DNA."
    )


def _detect_23andme(source_path: Path) -> SourceDetection:
    member_name = _first_zip_text_member(source_path) if source_path.suffix.lower() == ".zip" else None
    comments: list[str] = []
    header_found = False
    reference_build = None
    with _open_text_source(source_path, member_name=member_name) as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            lowered = text.lower()
            if text.startswith("#"):
                comments.append(text)
                if "assembly build 37" in lowered or "build 37" in lowered or "annotation release 104" in lowered:
                    reference_build = "GRCh37"
                continue
            columns = text.split("\t")
            header_found = len(columns) >= 4 and columns[:4] == ["rsid", "chromosome", "position", "genotype"]
            break
    if not header_found and not any(line.lower().startswith("# rsid\tchromosome\tposition\tgenotype") for line in comments):
        raise ValueError(f"not a recognized 23andMe raw genotype export: {source_path}")
    if not any("23andme" in line.lower() for line in comments):
        raise ValueError(f"not a recognized 23andMe raw genotype export: {source_path}")
    return SourceDetection(
        source_format="23andme",
        source_kind="consumer_genotype_array",
        reference_build=reference_build or "GRCh37",
        member_name=member_name,
    )


def _looks_like_vcf(source_path: Path) -> bool:
    lowered = source_path.name.lower()
    if any(lowered.endswith(extension) for extension in _VCF_EXTENSIONS):
        return True
    try:
        with source_path.open("rt", encoding="utf-8", errors="replace") as handle:
            first = handle.readline()
    except OSError:
        return False
    return first.startswith("##fileformat=VCF")


def _looks_like_bam(source_path: Path) -> bool:
    return source_path.name.lower().endswith(_BAM_EXTENSIONS)


def _looks_like_fastq(source_path: Path) -> bool:
    name = source_path.name.lower()
    return any(name.endswith(ext) for ext in _FASTQ_EXTENSIONS)


def _detect_ancestrydna(source_path: Path) -> SourceDetection:
    member_name = _first_zip_text_member(source_path) if source_path.suffix.lower() == ".zip" else None
    comments: list[str] = []
    header_found = False
    reference_build = None
    with _open_text_source(source_path, member_name=member_name) as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            lowered = text.lower()
            if text.startswith("#"):
                comments.append(text)
                if "build 37" in lowered or "build 37.1" in lowered or "reference build 37" in lowered:
                    reference_build = "GRCh37"
                continue
            columns = text.split("\t")
            header_found = len(columns) >= 5 and columns[:5] == ["rsid", "chromosome", "position", "allele1", "allele2"]
            break
    if not header_found:
        raise ValueError(f"not a recognized AncestryDNA raw genotype export: {source_path}")
    if not any("ancestrydna" in line.lower() or "ancestry.com" in line.lower() for line in comments):
        raise ValueError(f"not a recognized AncestryDNA raw genotype export: {source_path}")
    return SourceDetection(
        source_format="ancestrydna",
        source_kind="consumer_genotype_array",
        reference_build=reference_build or "GRCh37",
        member_name=member_name,
    )


def _detect_myheritage(source_path: Path) -> SourceDetection:
    member_name = _first_zip_text_member(source_path) if source_path.suffix.lower() == ".zip" else None
    comments: list[str] = []
    header_found = False
    reference_build = None
    with _open_text_source(source_path, member_name=member_name) as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            lowered = text.lower()
            if text.startswith("#"):
                comments.append(text)
                if "build 37" in lowered or "grch37" in lowered:
                    reference_build = "GRCh37"
                continue
            columns = next(csv.reader([text])) if text else []
            header_found = columns[:4] == ["RSID", "CHROMOSOME", "POSITION", "RESULT"]
            break
    if not header_found:
        raise ValueError(f"not a recognized MyHeritage raw genotype export: {source_path}")
    if not any("myheritage" in line.lower() for line in comments):
        raise ValueError(f"not a recognized MyHeritage raw genotype export: {source_path}")
    return SourceDetection(
        source_format="myheritage",
        source_kind="consumer_genotype_array",
        reference_build=reference_build or "GRCh37",
        member_name=member_name,
        provider="myheritage",
    )


def _detect_ftdna(source_path: Path) -> SourceDetection:
    member_name = _first_zip_text_member(source_path) if source_path.suffix.lower() == ".zip" else None
    header_found = False
    with _open_text_source(source_path, member_name=member_name) as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            if not text:
                continue
            if text.startswith("#"):
                # FamilyTreeDNA Family Finder exports have no comment block.
                # The presence of '#' lines means this is a different provider
                # (MyHeritage adds them; AncestryDNA/23andMe use a different
                # comma layout). Reject so the next detector can claim it.
                raise ValueError(f"not a recognized FamilyTreeDNA raw genotype export: {source_path}")
            columns = next(csv.reader([text])) if text else []
            header_found = columns[:4] == ["RSID", "CHROMOSOME", "POSITION", "RESULT"]
            break
    if not header_found:
        raise ValueError(f"not a recognized FamilyTreeDNA raw genotype export: {source_path}")
    return SourceDetection(
        source_format="ftdna",
        source_kind="consumer_genotype_array",
        # FamilyTreeDNA encodes the build in the filename (e.g. `_o37_`); the
        # body has no header line, so we assume GRCh37 as the documented
        # default for Family Finder exports.
        reference_build="GRCh37",
        member_name=member_name,
        provider="ftdna",
    )


def _detect_livingdna(source_path: Path) -> SourceDetection:
    member_name = _first_zip_text_member(source_path) if source_path.suffix.lower() == ".zip" else None
    comments: list[str] = []
    header_found = False
    reference_build = None
    with _open_text_source(source_path, member_name=member_name) as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            lowered = text.lower()
            if text.startswith("#"):
                comments.append(text)
                if "grch37" in lowered or "build 37" in lowered:
                    reference_build = "GRCh37"
                # Living DNA places the column header inside the comment block.
                if text.lstrip("# ").startswith("rsid\tchromosome\tposition\tgenotype"):
                    header_found = True
                continue
            # First non-comment line should be a data row, tab-separated.
            columns = text.split("\t")
            if not header_found:
                # Some exports may omit the in-comment header line; accept
                # tab-separated data that starts with an rsID as confirmation.
                header_found = len(columns) >= 4 and columns[0].lower().startswith("rs")
            break
    if not header_found:
        raise ValueError(f"not a recognized Living DNA raw genotype export: {source_path}")
    if not any("living dna" in line.lower() for line in comments):
        raise ValueError(f"not a recognized Living DNA raw genotype export: {source_path}")
    return SourceDetection(
        source_format="livingdna",
        source_kind="consumer_genotype_array",
        reference_build=reference_build or "GRCh37",
        member_name=member_name,
        provider="livingdna",
    )


def _detect_vcf_provider(source_path: Path) -> tuple[str | None, str | None]:
    """Sniff a VCF header for a known sequencing-service provider tag.

    Returns ``(provider, reference_build)`` when a signature matches, otherwise
    ``(None, None)``. The generic VCF parser is still used; this is purely a
    metadata enrichment so users see "Nebula" / "Dante" / "Sequencing.com"
    instead of a bare "vcf".
    """

    name = source_path.name.lower()
    try:
        if name.endswith((".gz", ".bgz")):
            handle = gzip.open(source_path, "rt", encoding="utf-8", errors="replace")
        else:
            handle = source_path.open("rt", encoding="utf-8", errors="replace")
    except OSError:
        return (None, None)
    try:
        with handle as fh:
            for _ in range(500):  # header lines only
                line = fh.readline()
                if not line:
                    break
                if not line.startswith("#"):
                    break
                for signature, provider, reference_build in _VCF_PROVIDER_SIGNATURES:
                    if signature in line:
                        return (provider, reference_build)
                if line.startswith("#CHROM"):
                    # Sample column can be the only Nebula tell when MegaBOLT
                    # path is absent. NG1<kit> sample IDs are Nebula-issued.
                    sample = line.rstrip("\n").split("\t")
                    if len(sample) > 9 and _NEBULA_SAMPLE_PATTERN.match(sample[9]):
                        return ("nebula", "GRCh38")
                    break
    except OSError:
        return (None, None)
    return (None, None)
