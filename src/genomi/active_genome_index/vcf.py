from __future__ import annotations

import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

VCF_COLUMNS = [
    "#CHROM",
    "POS",
    "ID",
    "REF",
    "ALT",
    "QUAL",
    "FILTER",
    "INFO",
    "FORMAT",
]

# INFO keys whose value is a direct gene symbol (or symbol list). Hoisted to a
# module constant so the per-record parse hot path (millions of records on a
# WGS gVCF) does not reallocate this set on every call.
SIMPLE_GENE_KEYS = frozenset(
    {
        "GENE",
        "Gene",
        "GENES",
        "GeneName",
        "SYMBOL",
        "Gene.refGene",
        "Gene.knownGene",
        "SNPEFF_GENE_NAME",
    }
)


@dataclass(frozen=True)
class VcfHeader:
    meta: list[str]
    columns: list[str]

    @property
    def samples(self) -> list[str]:
        return self.columns[9:]

    def first_meta_value(self, key: str) -> str | None:
        prefix = f"##{key}="
        for line in self.meta:
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None

    def contigs(self) -> list[str]:
        contig_prefix = "##contig=<ID="
        names: list[str] = []
        for line in self.meta:
            if not line.startswith(contig_prefix):
                continue
            value = line[len(contig_prefix) :]
            names.append(value.split(",", 1)[0].rstrip(">"))
        return names

    def to_dict(self) -> dict[str, Any]:
        return {
            "fileformat": self.first_meta_value("fileformat"),
            "fileDate": self.first_meta_value("fileDate"),
            "source": self.first_meta_value("source"),
            "dataSourceType": self.first_meta_value("dataSourceType"),
            "dataAnalysisProvider": self.first_meta_value("dataAnalysisProvider"),
            "reference": self.first_meta_value("reference"),
            "referenceInfo": self.first_meta_value("referenceInfo"),
            "pipelineVersion": self.first_meta_value("PipelineVersion"),
            "samples": self.samples,
            "contig_count": len(self.contigs()),
            "contigs": self.contigs()[:32],
        }


@dataclass(frozen=True)
class VcfRecord:
    chrom: str
    pos: int
    record_id: str
    ref: str
    alt: str
    qual: str
    filter: str
    info: str
    format: str
    sample: str
    sample_name: str | None = None
    sample_index: int = 0
    offset: int | None = None
    line_length: int | None = None
    line_number: int | None = None

    @property
    def end(self) -> int:
        info = parse_info(self.info)
        if "END" in info:
            try:
                return int(str(info["END"]))
            except ValueError:
                pass
        return self.pos + max(len(self.ref), 1) - 1

    @property
    def is_variant(self) -> bool:
        if self.alt in ("", "."):
            return False
        alts = self.alts
        genotype = self.genotype
        if genotype:
            for token in genotype.replace("|", "/").split("/"):
                if token in {"", ".", "0"}:
                    continue
                try:
                    alt = alts[int(token) - 1]
                except (IndexError, ValueError):
                    continue
                if not _is_symbolic_non_ref_alt(alt):
                    return True
            return False
        return any(not _is_symbolic_non_ref_alt(alt) for alt in alts)

    @property
    def genotype(self) -> str | None:
        return parse_sample(self.format, self.sample).get("GT")

    @property
    def depth(self) -> int | None:
        return sample_metrics(self.format, self.sample, self.info)[1]

    @property
    def genotype_quality(self) -> int | None:
        return sample_metrics(self.format, self.sample, self.info)[2]

    @property
    def alts(self) -> list[str]:
        if self.alt in ("", "."):
            return []
        return self.alt.split(",")

    @property
    def info_genes(self) -> list[str]:
        return extract_info_genes(self.info)

    def variant_key(self) -> str:
        return f"{self.chrom}:{self.pos}:{self.ref}:{self.alt}"

    def to_dict(self, include_raw_fields: bool = True) -> dict[str, Any]:
        sample_values = parse_sample(self.format, self.sample)
        genotype, depth, genotype_quality = sample_metrics(self.format, self.sample, self.info)
        payload: dict[str, Any] = {
            "chrom": self.chrom,
            "pos": self.pos,
            "end": self.end,
            "id": None if self.record_id == "." else self.record_id,
            "ref": self.ref,
            "alt": None if self.alt == "." else self.alt,
            "alts": self.alts,
            "qual": None if self.qual == "." else self.qual,
            "filter": self.filter,
            "is_variant": self.is_variant,
            "sample_name": self.sample_name,
            "sample_index": self.sample_index,
            "genotype": genotype,
            "depth": depth,
            "genotype_quality": genotype_quality,
            "sample": sample_values,
            "info_genes": self.info_genes,
            "variant_key": self.variant_key(),
        }
        if include_raw_fields:
            payload["info"] = parse_info(self.info)
            payload["format"] = self.format.split(":") if self.format else []
            payload["offset"] = self.offset
            payload["line_length"] = self.line_length
            payload["line_number"] = self.line_number
        return payload


def parse_info(info: str) -> dict[str, str | bool]:
    if not info or info == ".":
        return {}
    parsed: dict[str, str | bool] = {}
    for item in info.split(";"):
        if not item:
            continue
        if "=" not in item:
            parsed[item] = True
            continue
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def extract_info_genes(info: str | dict[str, str | bool]) -> list[str]:
    if isinstance(info, str):
        return _extract_info_genes_from_text(info)
    parsed = info
    genes: list[str] = []
    for key in (
        "GENE",
        "Gene",
        "GENES",
        "GeneName",
        "SYMBOL",
        "Gene.refGene",
        "Gene.knownGene",
        "SNPEFF_GENE_NAME",
    ):
        value = parsed.get(key)
        if isinstance(value, str):
            genes.extend(_split_gene_values(value))
    ann = parsed.get("ANN")
    if isinstance(ann, str):
        for annotation in ann.split(","):
            fields = annotation.split("|")
            if len(fields) > 3:
                genes.extend(_split_gene_values(fields[3]))
    csq = parsed.get("CSQ")
    if isinstance(csq, str):
        for annotation in csq.split(","):
            fields = annotation.split("|")
            for index in (3, 4):
                if len(fields) > index:
                    genes.extend(_split_gene_values(fields[index]))
    eff = parsed.get("EFF")
    if isinstance(eff, str):
        for annotation in eff.split(","):
            if "(" not in annotation or ")" not in annotation:
                continue
            fields = annotation.split("(", 1)[1].split(")", 1)[0].split("|")
            if len(fields) > 5:
                genes.extend(_split_gene_values(fields[5]))
    return _unique_gene_values(genes)


def _extract_info_genes_from_text(info: str) -> list[str]:
    if not info or info == ".":
        return []
    genes: list[str] = []
    for item in info.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key in SIMPLE_GENE_KEYS:
            genes.extend(_split_gene_values(value))
            continue
        if key == "ANN":
            for annotation in value.split(","):
                fields = annotation.split("|")
                if len(fields) > 3:
                    genes.extend(_split_gene_values(fields[3]))
            continue
        if key == "CSQ":
            for annotation in value.split(","):
                fields = annotation.split("|")
                for index in (3, 4):
                    if len(fields) > index:
                        genes.extend(_split_gene_values(fields[index]))
            continue
        if key == "EFF":
            for annotation in value.split(","):
                if "(" not in annotation or ")" not in annotation:
                    continue
                fields = annotation.split("(", 1)[1].split(")", 1)[0].split("|")
                if len(fields) > 5:
                    genes.extend(_split_gene_values(fields[5]))
    return _unique_gene_values(genes)


def _split_gene_values(value: str) -> list[str]:
    return [
        item.strip()
        for item in value.replace("&", ",").replace("+", ",").split(",")
        if item.strip() and item.strip() not in {".", "-"}
    ]


def _unique_gene_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output = []
    for value in values:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def parse_sample(format_field: str, sample_field: str) -> dict[str, str]:
    if not format_field or not sample_field:
        return {}
    keys = format_field.split(":")
    values = sample_field.split(":")
    return {key: values[i] if i < len(values) else "" for i, key in enumerate(keys)}


def sample_metrics(
    format_field: str,
    sample_field: str,
    info_field: str | dict[str, str | bool] | None = None,
) -> tuple[str | None, int | None, int | None]:
    if not format_field or not sample_field:
        return None, None, None
    genotype = depth = genotype_quality = None
    allele_depths = phred_likelihoods = None
    keys = format_field.split(":")
    values = sample_field.split(":")
    for index, key in enumerate(keys):
        if index >= len(values):
            break
        value = values[index]
        if key == "GT":
            genotype = value
        elif key == "DP":
            depth = _optional_int(value)
        elif key == "GQ":
            genotype_quality = _optional_int(value)
        elif key == "AD":
            allele_depths = value
        elif key == "PL":
            phred_likelihoods = value
    if depth is None:
        depth = _depth_from_allele_depths(allele_depths)
    if depth is None:
        depth = _depth_from_info(info_field)
    if genotype_quality is None:
        genotype_quality = _genotype_quality_from_likelihoods(genotype, phred_likelihoods)
    return genotype, depth, genotype_quality


def read_header(path: str | Path) -> VcfHeader:
    # Bgzipped + indexed → delegate to the bgzf-aware reader so capability
    # tools and the parse path can share a single header-reading helper.
    if Path(str(path) + ".gzi").exists():
        return read_header_bgzf(path)
    meta: list[str] = []
    with open_vcf_binary(path) as handle:
        while True:
            line = handle.readline()
            if not line:
                raise ValueError("VCF header line beginning with #CHROM was not found")
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text.startswith("##"):
                meta.append(text)
                continue
            if text.startswith("#CHROM"):
                columns = text.split("\t")
                _validate_columns(columns)
                return VcfHeader(meta=meta, columns=columns)
            raise ValueError(f"Unexpected line before VCF header: {text[:80]}")


def read_header_lines(path: str | Path) -> list[str]:
    lines: list[str] = []
    with open_vcf_binary(path) as handle:
        while True:
            line = handle.readline()
            if not line:
                raise ValueError("VCF header line beginning with #CHROM was not found")
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(text)
            if text.startswith("#CHROM"):
                _validate_columns(text.split("\t"))
                return lines
            if not text.startswith("#"):
                raise ValueError(f"Unexpected line before VCF header: {text[:80]}")




def iter_records(path: str | Path, limit: int | None = None) -> Iterator[VcfRecord]:
    header = read_header(path)
    emitted = 0
    line_number = 0
    with open_vcf_binary(path) as handle:
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                return
            line_number += 1
            if raw.startswith(b"#"):
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            yield parse_record_line(
                text,
                sample_names=header.samples,
                offset=offset,
                line_length=len(raw),
                line_number=line_number,
            )
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def iter_sample_records(path: str | Path, limit: int | None = None) -> Iterator[VcfRecord]:
    # Bgzipped + indexed (a `.gzi` sibling exists) → capture BGZF virtual
    # offsets so capability tools can seek into the canonical without
    # reopening the intake. Plain or unindexed gzip falls through to the
    # legacy byte-offset path.
    path_obj = Path(path)
    if Path(str(path_obj) + ".gzi").exists():
        yield from iter_sample_records_bgzf(path_obj, limit=limit)
        return
    header = read_header(path)
    emitted = 0
    line_number = 0
    with open_vcf_binary(path) as handle:
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                return
            line_number += 1
            if raw.startswith(b"#"):
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            parts = text.split("\t")
            sample_count = sample_count_from_parts(parts, header.samples)
            for sample_index in range(sample_count):
                yield parse_record_fields(
                    parts,
                    sample_names=header.samples,
                    sample_index=sample_index,
                    offset=offset,
                    line_length=len(raw),
                    line_number=line_number,
                )
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def read_header_bgzf(bgzf_path: str | Path) -> VcfHeader:
    """Read a VcfHeader from a bgzip-compressed VCF.

    Used by capability tools that read the Active Genome Index's canonical
    bgzip file via pysam — never the user's intake source.
    """

    from pysam.libcbgzf import BGZFile  # heavy import; keep local

    meta: list[str] = []
    with BGZFile(str(bgzf_path), "rb") as handle:
        while True:
            line = handle.readline()
            if not line:
                raise ValueError("VCF header line beginning with #CHROM was not found")
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text.startswith("##"):
                meta.append(text)
                continue
            if text.startswith("#CHROM"):
                columns = text.split("\t")
                _validate_columns(columns)
                return VcfHeader(meta=meta, columns=columns)
            raise ValueError(f"Unexpected line before VCF header: {text[:80]}")


def iter_sample_records_bgzf(bgzf_path: str | Path, limit: int | None = None) -> Iterator[VcfRecord]:
    """Yield `VcfRecord`s from a bgzip-compressed VCF, capturing each
    record's BGZF virtual offset (block_address << 16 | within-block).

    The virtual offset becomes the value stored in `records.offset` in
    the Active Genome Index sqlite — capability tools later use it with
    `pysam.libcbgzf.BGZFile.seek(offset)` for O(log block) random access
    to the canonical, with zero reads of the user's intake source.
    """

    from pysam.libcbgzf import BGZFile  # heavy import; keep local

    header = read_header_bgzf(bgzf_path)
    emitted = 0
    line_number = 0
    with BGZFile(str(bgzf_path), "rb") as handle:
        while True:
            virtual_offset = handle.tell()
            raw = handle.readline()
            if not raw:
                return
            line_number += 1
            if raw.startswith(b"#"):
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not text:
                continue
            parts = text.split("\t")
            sample_count = sample_count_from_parts(parts, header.samples)
            for sample_index in range(sample_count):
                yield parse_record_fields(
                    parts,
                    sample_names=header.samples,
                    sample_index=sample_index,
                    offset=virtual_offset,
                    line_length=len(raw),
                    line_number=line_number,
                )
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def sample_count_from_parts(parts: list[str], sample_names: list[str] | None) -> int:
    observed = max(0, len(parts) - 9)
    if sample_names:
        return min(len(sample_names), observed)
    return observed or 1


def sample_field_count(line: str, sample_names: list[str]) -> int:
    return sample_count_from_parts(line.rstrip("\r\n").split("\t"), sample_names)


def parse_record_fields(
    parts: list[str],
    *,
    sample_name: str | None = None,
    sample_names: list[str] | None = None,
    sample_index: int = 0,
    offset: int | None = None,
    line_length: int | None = None,
    line_number: int | None = None,
) -> VcfRecord:
    """Build a VcfRecord from a pre-split tab-field list.

    The parse hot path splits each line on tabs exactly once and reuses the
    field list across every sample column, so the per-record loop (millions
    of records on a WGS gVCF) avoids re-splitting the same line per sample.
    """
    if len(parts) < 8:
        raise ValueError(f"VCF record has fewer than 8 fields: {parts[:8]}")
    chrom, pos_raw, record_id, ref, alt, qual, filt, info = parts[:8]
    format_field = parts[8] if len(parts) > 8 else ""
    sample_field_index = 9 + sample_index
    sample_field = parts[sample_field_index] if len(parts) > sample_field_index else ""
    if sample_names is not None:
        sample_name = sample_names[sample_index] if sample_index < len(sample_names) else None
    try:
        pos = int(pos_raw)
    except ValueError as exc:
        raise ValueError(f"Invalid VCF position {pos_raw!r}") from exc
    return VcfRecord(
        chrom=chrom,
        pos=pos,
        record_id=record_id,
        ref=ref,
        alt=alt,
        qual=qual,
        filter=filt,
        info=info,
        format=format_field,
        sample=sample_field,
        sample_name=sample_name,
        sample_index=sample_index,
        offset=offset,
        line_length=line_length,
        line_number=line_number,
    )


def parse_record_line(
    line: str,
    *,
    sample_name: str | None = None,
    sample_names: list[str] | None = None,
    sample_index: int = 0,
    offset: int | None = None,
    line_length: int | None = None,
    line_number: int | None = None,
) -> VcfRecord:
    return parse_record_fields(
        line.rstrip("\r\n").split("\t"),
        sample_name=sample_name,
        sample_names=sample_names,
        sample_index=sample_index,
        offset=offset,
        line_length=line_length,
        line_number=line_number,
    )


def parse_region(region: str) -> tuple[str, int, int]:
    if ":" not in region:
        raise ValueError("Region must use CHROM:START-END syntax")
    chrom, span = region.split(":", 1)
    if "-" in span:
        start_raw, end_raw = span.split("-", 1)
    else:
        start_raw = end_raw = span
    start = int(start_raw.replace(",", ""))
    end = int(end_raw.replace(",", ""))
    if start < 1 or end < start:
        raise ValueError("Region coordinates must be 1-based and end >= start")
    return chrom, start, end


def load_record_at_offset(
    path: str | Path,
    offset: int,
    *,
    sample_name: str | None = None,
    sample_names: list[str] | None = None,
    sample_index: int = 0,
) -> VcfRecord:
    # Bgzipped + indexed → treat `offset` as a BGZF virtual offset; use
    # pysam BGZFile so the seek lands inside the right block. Plain VCF
    # falls through to byte-offset seek.
    if Path(str(path) + ".gzi").exists():
        from pysam.libcbgzf import BGZFile  # local: heavy import

        with BGZFile(str(path), "rb") as handle:
            handle.seek(int(offset))
            raw = handle.readline()
    else:
        with open_vcf_binary(path) as handle:
            handle.seek(offset)
            raw = handle.readline()
    return parse_record_line(
        raw.decode("utf-8", errors="replace").rstrip("\r\n"),
        sample_name=sample_name,
        sample_names=sample_names,
        sample_index=sample_index,
        offset=offset,
        line_length=len(raw),
    )


def open_vcf_binary(path: str | Path) -> BinaryIO:
    resolved = Path(path)
    with resolved.open("rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        try:
            from isal import igzip as _igzip
            return cast(BinaryIO, _igzip.open(resolved, "rb"))
        except ImportError:
            pass
        return cast(BinaryIO, gzip.open(resolved, "rb"))
    return resolved.open("rb")


def _validate_columns(columns: list[str]) -> None:
    if columns[: len(VCF_COLUMNS)] != VCF_COLUMNS:
        raise ValueError(f"Unsupported VCF columns: expected {VCF_COLUMNS}, got {columns[:len(VCF_COLUMNS)]}")


def _optional_int(value: str | None) -> int | None:
    if value in (None, "", "."):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _depth_from_allele_depths(value: str | None) -> int | None:
    if value in (None, "", "."):
        return None
    total = 0
    observed = False
    for token in str(value).split(","):
        depth = _optional_int(token)
        if depth is None:
            continue
        total += depth
        observed = True
    return total if observed else None


def _depth_from_info(value: str | dict[str, str | bool] | None) -> int | None:
    if value in (None, "", "."):
        return None
    info = parse_info(value) if isinstance(value, str) else value
    if not isinstance(info, dict):
        return None
    depth = _optional_int(str(info.get("DP") or ""))
    if depth is not None:
        return depth
    dp4 = info.get("DP4")
    if not isinstance(dp4, str):
        return None
    return _depth_from_allele_depths(dp4)


def _genotype_quality_from_likelihoods(genotype: str | None, value: str | None) -> int | None:
    called_index = _genotype_likelihood_index(genotype)
    if called_index is None or value in (None, "", "."):
        return None
    likelihoods: list[int] = []
    for token in str(value).split(","):
        likelihood = _optional_int(token)
        if likelihood is None:
            return None
        likelihoods.append(likelihood)
    if called_index >= len(likelihoods) or len(likelihoods) < 2:
        return None
    called = likelihoods[called_index]
    next_best = min(
        likelihood
        for index, likelihood in enumerate(likelihoods)
        if index != called_index
    )
    return max(0, next_best - called)


def _genotype_likelihood_index(genotype: str | None) -> int | None:
    if not genotype:
        return None
    alleles: list[int] = []
    for token in genotype.replace("|", "/").split("/"):
        value = _optional_int(token)
        if value is None:
            return None
        alleles.append(value)
    if len(alleles) == 1:
        return alleles[0]
    if len(alleles) == 2:
        first, second = sorted(alleles)
        return second * (second + 1) // 2 + first
    return None


def _is_symbolic_non_ref_alt(value: str) -> bool:
    return value.strip().upper() in {"<NON_REF>", "<*>"}


def alt_is_reference_only(alt: str) -> bool:
    """True when the ALT column carries no real alternate allele.

    An ALT of ``""``/``"."`` or only symbolic non-ref tokens (``<NON_REF>``,
    ``<*>``) means the record is a reference/gVCF block — ``is_variant`` is
    False for it regardless of genotype (a real allele can never be referenced
    by GT because none exists). The two-phase variant pass uses this as a cheap
    pre-filter to skip the expensive full parse + row build on the ~96% of a
    gVCF that is reference blocks; only real-ALT lines (which *might* be a
    hom-ref call) are fully parsed and classified by ``VcfRecord.is_variant``.
    """
    alt = alt.strip()
    if alt in ("", "."):
        return True
    return all(_is_symbolic_non_ref_alt(token) for token in alt.split(","))
