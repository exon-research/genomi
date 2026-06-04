"""Content-based genome source detection.

Detection never trusts the file name. A source arrives as bytes — possibly
gzip/bzip2/xz-compressed, possibly inside a zip or tar — and we decide what it
is by peeling those wrappers (see ``text_io``) and reading the *content*:

- binary magic for alignment files (BAM's ``BAM\\x01`` inside its BGZF gzip,
  CRAM's ``CRAM`` magic), then
- the first lines of the decompressed text for VCF/gVCF, FASTQ, and the
  consumer genotype-array exports (23andMe / AncestryDNA / MyHeritage /
  FamilyTreeDNA / Living DNA).

Getting VCF-vs-gVCF or the wrapper wrong silently mis-parses exactly the large
WGS deliverables that are renamed most often, so the file extension is treated
as a hint at best and is never required.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, replace
from pathlib import Path

from ..alignment import paired_fastq_r1_name, paired_fastq_r2_name
from .text_io import archive_member_names, open_genomic_binary, select_archive_member

# How much decompressed payload we decode to classify. Comfortably covers a WGS
# VCF header (contig + INFO/FORMAT lines) plus the first hundreds of records, so
# the gVCF reference-block signature and provider tags are always in range.
_PROBE_BYTES = 256 * 1024


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

# Decompressed magic bytes for the binary alignment formats.
_BAM_MAGIC = b"BAM\x01"
_CRAM_MAGIC = b"CRAM"


@dataclass(frozen=True)
class _Probe:
    """A peek at a source's decompressed genomic payload."""

    head: bytes
    lines: list[str]


def _probe(source_path: Path, member_name: str | None) -> _Probe:
    with open_genomic_binary(source_path, member_name=member_name) as binary:
        head = binary.read(_PROBE_BYTES)
    return _Probe(head=head, lines=head.decode("utf-8", "replace").splitlines())


def detect_source(source: str | Path) -> SourceDetection:
    """Detect the genome source format from its content.

    Transparently peels gzip/bzip2/xz compression and zip/tar archives, then
    classifies the payload as VCF, gVCF, BAM, paired-end FASTQ, or a raw
    consumer genotype array (23andMe, AncestryDNA, MyHeritage, FamilyTreeDNA,
    Living DNA). Callers do not supply the format; if you already know it, you
    do not need this function.
    """
    source_path = Path(source)
    member_name = select_archive_member(source_path)
    probe = _probe(source_path, member_name)

    if probe.head.startswith(_BAM_MAGIC):
        return SourceDetection(source_format="bam", source_kind="alignment_reads", member_name=member_name)
    if probe.head.startswith(_CRAM_MAGIC):
        raise ValueError(
            "CRAM alignment detected. Genomi does not ingest CRAM directly yet; "
            "convert it to BAM (`samtools view -b -T <ref>`) or call variants to a VCF first."
        )

    for classifier in (_classify_vcf, _classify_fastq, _classify_consumer_array):
        detection = classifier(probe)
        if detection is not None:
            if detection.source_format == "fastq" and member_name is not None:
                member_name = _validated_archive_fastq_r1_member(source_path, member_name)
            return replace(detection, member_name=member_name)

    if _looks_like_complete_genomics(probe.lines):
        raise ValueError(
            "Complete Genomics var/masterVar file detected. Genomi does not ingest "
            "this format directly yet; use Complete Genomics' cgatools to export a VCF first."
        )

    raise ValueError(
        "Could not detect the genome source type from its content. Supported sources: "
        "VCF/gVCF, BAM, paired-end FASTQ, and raw genotype exports from 23andMe, "
        "AncestryDNA, MyHeritage, FamilyTreeDNA (Family Finder), and Living DNA — "
        "compressed (gzip/bzip2/xz) or inside a zip/tar archive."
    )


# ---------------------------------------------------------------------------
# VCF / gVCF
# ---------------------------------------------------------------------------


def _classify_vcf(probe: _Probe) -> SourceDetection | None:
    first = next((line for line in probe.lines if line.strip()), "")
    if not first.startswith("##fileformat=VCF"):
        return None
    provider, reference_build = _detect_vcf_provider_lines(probe.lines)
    return SourceDetection(
        source_format="gvcf" if _looks_like_gvcf_lines(probe.lines) else "vcf",
        source_kind="variant_callset",
        reference_build=reference_build,
        provider=provider,
    )


def _looks_like_gvcf_lines(lines: list[str]) -> bool:
    """VCF vs gVCF by content: reference-confidence records, not just ``END=``.

    The only robust gVCF signal is a *data record* whose ALT carries the
    reference-confidence symbol ``<NON_REF>`` (GATK) or ``<*>`` — that is what a
    gVCF reference block is, and it triggers the variants-first two-phase parse.

    Two tempting signals are deliberately rejected as ambiguous:

    - A bare ``END=`` INFO key. CNV (``<DEL>``/``<DUP>``), SV (``<ITX>``), and
      even genotype-array-derived VCFs use ``END=`` for non-reference records.
    - A ``##ALT=<ID=NON_REF...>`` *header* declaration. DRAGEN emits it as
      boilerplate in plain SV callsets that contain no reference blocks at all.

    GATK's ``##GVCFBlock`` header lines remain a reliable gVCF-only signal.
    """
    data_records_seen = 0
    for line in lines:
        if line.startswith("#"):
            if "GVCFBLOCK" in line.upper():
                return True
            continue
        if data_records_seen >= 200:
            break
        fields = line.split("\t")
        if len(fields) >= 5:
            alts = fields[4].upper().split(",")
            if "<NON_REF>" in alts or "<*>" in alts:
                return True
        data_records_seen += 1
    return False


def _detect_vcf_provider_lines(lines: list[str]) -> tuple[str | None, str | None]:
    """Sniff VCF header lines for a known sequencing-service provider tag."""
    for line in lines:
        if not line.startswith("#"):
            break
        for signature, provider, reference_build in _VCF_PROVIDER_SIGNATURES:
            if signature in line:
                return (provider, reference_build)
        if line.startswith("#CHROM"):
            # The sample column can be the only Nebula tell when the MegaBOLT
            # path is absent: NG1<kit> sample IDs are Nebula-issued.
            sample = line.split("\t")
            if len(sample) > 9 and _NEBULA_SAMPLE_PATTERN.match(sample[9].strip()):
                return ("nebula", "GRCh38")
            break
    return (None, None)


# ---------------------------------------------------------------------------
# FASTQ
# ---------------------------------------------------------------------------

_NUCLEOTIDE_CHARS = frozenset("ACGTNUacgtnu.-")


def _classify_fastq(probe: _Probe) -> SourceDetection | None:
    records = [line for line in probe.lines if line != ""]
    if len(records) < 4:
        records = probe.lines
    if len(records) < 4:
        return None
    if not records[0].startswith("@"):
        return None
    sequence = records[1].strip()
    if not sequence or any(char not in _NUCLEOTIDE_CHARS for char in sequence):
        return None
    if not records[2].startswith("+"):
        return None
    # Paired-end deliverables are the primary case; bare files resolve the R2
    # sibling at parse time, while archive members are pair-validated before
    # detection advertises FASTQ support.
    return SourceDetection(source_format="fastq", source_kind="paired_reads_input")


def _validated_archive_fastq_r1_member(source_path: Path, member_name: str) -> str:
    members = set(archive_member_names(source_path))
    r2_basename = paired_fastq_r2_name(member_name)
    if r2_basename is not None:
        r2_member = str(Path(member_name).with_name(r2_basename))
        if r2_member in members:
            return member_name
        raise ValueError(
            f"FASTQ archive must contain an R2 member paired with {member_name}; expected {r2_member}."
        )
    r1_basename = paired_fastq_r1_name(member_name)
    if r1_basename is not None:
        r1_member = str(Path(member_name).with_name(r1_basename))
        if r1_member in members:
            return r1_member
        raise ValueError(
            f"FASTQ archive must contain an R1 member paired with {member_name}; expected {r1_member}."
        )
    raise ValueError(
        f"Archive FASTQ member must be an R1/R2 read with a recognized pair suffix: {member_name}."
    )


# ---------------------------------------------------------------------------
# Consumer genotype arrays (spec-driven, one matcher for all providers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ArraySignature:
    source_format: str
    provider: str | None
    delimiter: str
    header: tuple[str, ...]
    vendor_tokens: tuple[str, ...] = ()
    forbid_comments: bool = False
    header_in_comments: bool = False
    accept_rs_data_row: bool = False


# Order matters: providers that share a column header are disambiguated by a
# required vendor token in the comment block (or by its absence, for FTDNA).
_ARRAY_SIGNATURES: tuple[_ArraySignature, ...] = (
    _ArraySignature(
        "23andme", None, "\t", ("rsid", "chromosome", "position", "genotype"),
        vendor_tokens=("23andme",), header_in_comments=True,
    ),
    _ArraySignature(
        "ancestrydna", None, "\t", ("rsid", "chromosome", "position", "allele1", "allele2"),
        vendor_tokens=("ancestrydna", "ancestry.com"), header_in_comments=True,
    ),
    _ArraySignature(
        "livingdna", "livingdna", "\t", ("rsid", "chromosome", "position", "genotype"),
        vendor_tokens=("living dna",), header_in_comments=True, accept_rs_data_row=True,
    ),
    _ArraySignature(
        "myheritage", "myheritage", ",", ("RSID", "CHROMOSOME", "POSITION", "RESULT"),
        vendor_tokens=("myheritage",),
    ),
    # FamilyTreeDNA Family Finder shares MyHeritage's CSV header but ships no
    # comment block — the absence of comments is its distinguishing signal.
    _ArraySignature(
        "ftdna", "ftdna", ",", ("RSID", "CHROMOSOME", "POSITION", "RESULT"),
        forbid_comments=True,
    ),
)

_BUILD37_TOKENS = ("build 37", "build37", "grch37", "reference build 37", "annotation release 104")


def _split_columns(text: str, delimiter: str) -> list[str]:
    if delimiter == ",":
        try:
            return next(csv.reader([text]))
        except StopIteration:
            return []
    return text.split(delimiter)


def _scan_array(lines: list[str], delimiter: str) -> tuple[list[str], list[str] | None, list[str] | None]:
    """Return ``(comments, first_non_comment_row, second_non_comment_row)``.

    The first non-comment row is the column header for most providers, but the
    data row itself for Living DNA exports that carry the header in a comment.
    """
    comments: list[str] = []
    rows: list[list[str]] = []
    for raw in lines:
        text = raw.rstrip("\r\n")
        if not text:
            continue
        if text.startswith("#"):
            comments.append(text)
            continue
        rows.append(_split_columns(text, delimiter))
        if len(rows) >= 2:
            break
    header = rows[0] if rows else None
    first_data = rows[1] if len(rows) > 1 else None
    return comments, header, first_data


def _array_reference_build(comments: list[str]) -> str:
    joined = "\n".join(comments).lower()
    if any(token in joined for token in _BUILD37_TOKENS):
        return "GRCh37"
    return "GRCh37"  # consumer arrays are GRCh37 unless a future export says otherwise


def _match_array(probe: _Probe, sig: _ArraySignature) -> SourceDetection | None:
    comments, header, _first_data = _scan_array(probe.lines, sig.delimiter)
    if sig.forbid_comments and comments:
        return None
    if sig.vendor_tokens:
        joined = "\n".join(comments).lower()
        if not any(token in joined for token in sig.vendor_tokens):
            return None

    header_ok = header is not None and tuple(col.strip() for col in header[: len(sig.header)]) == sig.header
    if not header_ok and sig.header_in_comments:
        needle = sig.delimiter.join(sig.header).lower()
        header_ok = any(comment.lstrip("# ").lower().startswith(needle) for comment in comments)
    if not header_ok and sig.accept_rs_data_row and header is not None:
        header_ok = len(header) >= len(sig.header) and header[0].strip().lower().startswith("rs")
    if not header_ok:
        return None

    return SourceDetection(
        source_format=sig.source_format,
        source_kind="consumer_genotype_array",
        reference_build=_array_reference_build(comments),
        provider=sig.provider,
    )


def _classify_consumer_array(probe: _Probe) -> SourceDetection | None:
    for sig in _ARRAY_SIGNATURES:
        detection = _match_array(probe, sig)
        if detection is not None:
            return detection
    return None


# ---------------------------------------------------------------------------
# Recognized-but-not-yet-ingestible formats (clear error beats "unknown type")
# ---------------------------------------------------------------------------


def _looks_like_complete_genomics(lines: list[str]) -> bool:
    for raw in lines[:50]:
        text = raw.strip()
        if not text:
            continue
        lowered = text.lower()
        if "#assembly_id" in lowered or "#genome_reference" in lowered or "complete genomics" in lowered:
            return True
        if text.startswith(">") and "varType" in text and "chromosome" in text:
            return True
    return False
