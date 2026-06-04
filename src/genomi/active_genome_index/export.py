from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..runtime.external import file_metadata, matching_manifest, utc_now, write_manifest
from ..runtime.handoff import evidence_context
from .active_genome_index import (
    connect,
    read_header_from_active_genome_index,
)

PRIMARY_CONTIGS_GRCH38 = tuple([str(number) for number in range(1, 23)] + ["X", "Y", "MT"])
PRIMARY_CONTIGS_GRCH38_WITH_ALIASES = tuple(
    [str(number) for number in range(1, 23)]
    + ["X", "Y", "MT"]
    + [f"chr{number}" for number in range(1, 23)]
    + ["chrX", "chrY", "chrM", "chrMT"]
)


def export_variants(
    agi_path: str | Path,
    output_path: str | Path,
    *,
    pass_only: bool = True,
    primary_contigs_only: bool = False,
    contigs: list[str] | None = None,
    chrom_style: str = "input",
    max_records: int | None = None,
    progress_every: int | None = None,
    progress: Callable[[int], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    agi_path = Path(agi_path)
    output_path = Path(output_path)
    if output_path.suffix == ".gz":
        raise ValueError("export writes plain VCF; use .vcf output, then normalize through genomi call genomi.parse_source")
    if chrom_style not in {"input", "no-chr", "chr"}:
        raise ValueError("chrom_style must be one of: input, no-chr, chr")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected_contigs = _selected_contigs(primary_contigs_only=primary_contigs_only, contigs=contigs)
    where, params = _where_clause(pass_only=pass_only, contigs=selected_contigs)
    # Synthesize VCF records from the structured index columns — no reopening
    # of the canonical bgzip. Multi-sample lines are reconstructed by grouping
    # the per-(offset, sample_index) rows back together in column order.
    #
    # `where` qualifies a line through any variant *sample row* (is_variant is a
    # per-sample property). A multi-sample line where only one sample carries the
    # ALT therefore qualifies on that row alone, but the line must still emit a
    # column for every declared sample or the row is narrower than the #CHROM
    # header and strict parsers (PharmCAT) reject it. So select the qualifying
    # offsets first, then pull back *all* sample rows at those offsets — the
    # line-level filters (PASS, contig) hold for every sample row of a line.
    if max_records is not None:
        selected_offsets_sql = f"""
            select offset from records where {where}
            group by offset order by min(chrom_sort), min(pos), offset limit ?
        """
    else:
        selected_offsets_sql = f"select distinct offset from records where {where}"
    select_sql = f"""
        select offset, chrom, chrom_sort, pos, rsid, ref, alt, qual, filter, info,
               format, sample, sample_index
        from records
        where offset in ({selected_offsets_sql})
        order by chrom_sort, pos, offset, sample_index
    """
    count_sql = f"select count(distinct offset) as records from records where {where}"
    select_params: list[Any] = list(params)
    if max_records is not None:
        select_params.append(max_records)
    filters = {
        "variants_only": True,
        "pass_only": pass_only,
        "primary_contigs_only": primary_contigs_only,
        "contigs": selected_contigs,
        "chrom_style": chrom_style,
        "max_records": max_records,
    }
    manifest_path = f"{output_path}.genomi-manifest.json"
    cache_expected = {
        "step": "export-variants",
        "agi_path": file_metadata(agi_path),
        "filters": filters,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            return {
                "status": "cached",
                "agi_path": str(agi_path),
                "output": str(output_path),
                "manifest_path": manifest_path,
                "candidate_records": cached.get("candidate_records"),
                "exported_records": cached.get("exported_records"),
                "filters": cached.get("filters"),
                "evidence_context": evidence_context(
                    "static",
                    reason="Exported VCF records can be normalized or matched against static evidence sources.",
                    commands=[
                        "genomi call genomi.parse_source --params '{\"source\":\"<exported.vcf>\",\"reference_fasta\":\"<GRCh38.fa>\"}'",
                        "genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'",
                    ],
                ),
            }

    with connect(agi_path) as connection:
        candidate_records = int(connection.execute(count_sql, params).fetchone()["records"])
        exported_records = _write_variant_vcf(
            connection,
            select_sql,
            select_params,
            output_path,
            pass_only=pass_only,
            selected_contigs=selected_contigs,
            chrom_style=chrom_style,
            progress_every=progress_every,
            progress=progress,
        )

    manifest = {
        "step": "export-variants",
        "created_at_utc": utc_now(),
        "agi_path": file_metadata(agi_path),
        "output": file_metadata(output_path),
        "filters": filters,
        "candidate_records": candidate_records,
        "exported_records": exported_records,
    }
    write_manifest(manifest_path, manifest)
    return {
        "status": "completed",
        "agi_path": str(agi_path),
        "output": str(output_path),
        "manifest_path": manifest_path,
        "candidate_records": candidate_records,
        "exported_records": exported_records,
        "filters": manifest["filters"],
        "evidence_context": evidence_context(
            "static",
            reason="Exported VCF records can be normalized or matched against static evidence sources.",
            commands=[
                "genomi call genomi.parse_source --params '{\"source\":\"<exported.vcf>\",\"reference_fasta\":\"<GRCh38.fa>\"}'",
                "genomi call clinvar.match_variants --params '{\"agi_path\":\"<agi.sqlite>\"}'",
            ],
        ),
    }


def _selected_contigs(*, primary_contigs_only: bool, contigs: list[str] | None) -> list[str] | None:
    selected: list[str] | None = None
    if primary_contigs_only:
        selected = list(PRIMARY_CONTIGS_GRCH38_WITH_ALIASES)
    if contigs:
        explicit = [contig for item in contigs for contig in item.split(",") if contig]
        selected = explicit if selected is None else [contig for contig in selected if contig in set(explicit)]
    return selected


def _where_clause(*, pass_only: bool, contigs: list[str] | None) -> tuple[str, tuple[Any, ...]]:
    clauses = ["is_variant = 1"]
    params: list[Any] = []
    if pass_only:
        clauses.append("filter = 'PASS'")
    if contigs:
        placeholders = ", ".join("?" for _ in contigs)
        clauses.append(f"chrom in ({placeholders})")
        params.extend(contigs)
    return " and ".join(clauses), tuple(params)


def _write_variant_vcf(
    connection: sqlite3.Connection,
    sql: str,
    params: list[Any],
    output_path: Path,
    *,
    pass_only: bool,
    selected_contigs: list[str] | None,
    chrom_style: str,
    progress_every: int | None,
    progress: Callable[[int], None] | None,
) -> int:
    # Synthesize each VCF record from the index's structured columns — no
    # reopening of the canonical bgzip. Rows are ordered by (chrom_sort, pos,
    # offset, sample_index); consecutive rows sharing an offset are one source
    # record (multi-sample), recombined in sample-index order.
    exported = 0
    header = read_header_from_active_genome_index(connection)
    # #CHROM POS ID REF ALT QUAL FILTER INFO [FORMAT sample...] — 8 fixed columns,
    # then FORMAT at index 8 and one column per declared sample from index 9 on.
    sample_count = max(0, len(header.columns) - 9)
    with output_path.open("w", encoding="utf-8") as output:
        _write_header(header, output, pass_only=pass_only, selected_contigs=selected_contigs, chrom_style=chrom_style)
        current_offset: object = object()
        group: list[sqlite3.Row] = []

        def flush() -> int:
            if not group:
                return 0
            output.write(_synthesize_record_line(group, chrom_style, sample_count) + "\n")
            return 1

        for row in connection.execute(sql, params):
            if row["offset"] != current_offset and group:
                exported += flush()
                if progress is not None and progress_every is not None and exported % progress_every == 0:
                    progress(exported)
                group = []
            current_offset = row["offset"]
            group.append(row)
        exported += flush()
    return exported


def _synthesize_record_line(group: list[sqlite3.Row], chrom_style: str, sample_count: int) -> str:
    first = group[0]
    chrom = _transform_chrom(str(first["chrom"]), chrom_style)
    rsid = first["rsid"] if first["rsid"] not in (None, "") else "."
    alt = first["alt"] if first["alt"] not in (None, "", ".") else "."
    qual = first["qual"] if first["qual"] not in (None, "") else "."
    info = first["info"] if first["info"] not in (None, "") else "."
    fmt = first["format"] if first["format"] not in (None, "") else None
    fields = [
        chrom,
        str(first["pos"]),
        str(rsid),
        str(first["ref"]),
        str(alt),
        str(qual),
        str(first["filter"]),
        str(info),
    ]
    # When the header declares samples, every data line must carry FORMAT plus
    # exactly one column per declared sample. Place each stored sample row by its
    # sample_index and fill any sample that is absent at this offset — e.g. a
    # reference call coalesced into a gVCF block elsewhere — with the VCF
    # missing-value token so the row width always matches the #CHROM header.
    if sample_count > 0:
        fields.append(str(fmt) if fmt is not None else "GT")
        by_index = {
            int(row["sample_index"]): str(row["sample"])
            for row in group
            if row["sample"] not in (None, "")
        }
        fields.extend(by_index.get(index, ".") for index in range(sample_count))
    elif fmt is not None:
        # Header declares FORMAT but no sample columns (rare); preserve FORMAT and
        # any per-row sample values in stored order without padding.
        fields.append(str(fmt))
        fields.extend(str(row["sample"]) for row in group if row["sample"] not in (None, ""))
    return "\t".join(fields)


def _write_header(
    header: Any,
    output: Any,
    *,
    pass_only: bool,
    selected_contigs: list[str] | None,
    chrom_style: str,
) -> None:
    # Emit the header reconstructed from the structured index
    # (source_header_lines), never the canonical/source.
    header_lines = [*list(header.meta), "\t".join(header.columns)]
    emitted_contigs: set[str] = set()
    for line in header_lines:
        if line.startswith("##contig=<ID="):
            line = _transform_contig_header_line(line, chrom_style)
            contig = _contig_id_from_header_line(line)
            if contig is not None:
                if contig in emitted_contigs:
                    continue
                emitted_contigs.add(contig)
        if line.startswith("#CHROM"):
            output.write("##genomiExport=variants\n")
            output.write(f"##genomiExportPassOnly={json.dumps(pass_only)}\n")
            output.write(f"##genomiExportContigs={json.dumps(selected_contigs)}\n")
            output.write(f"##genomiExportChromStyle={json.dumps(chrom_style)}\n")
        output.write(line + "\n")


def _transform_record_line(line: str, chrom_style: str) -> str:
    if chrom_style == "input":
        return line
    chrom, separator, rest = line.partition("\t")
    if not separator:
        return line
    return f"{_transform_chrom(chrom, chrom_style)}{separator}{rest}"


def _transform_contig_header_line(line: str, chrom_style: str) -> str:
    if chrom_style == "input":
        return line
    prefix = "##contig=<ID="
    if not line.startswith(prefix):
        return line
    rest = line[len(prefix) :]
    contig, separator, suffix = rest.partition(",")
    if not separator:
        contig = rest.rstrip(">")
        suffix = ">"
    return f"{prefix}{_transform_chrom(contig, chrom_style)}{separator}{suffix}"


def _contig_id_from_header_line(line: str) -> str | None:
    prefix = "##contig=<ID="
    if not line.startswith(prefix):
        return None
    rest = line[len(prefix) :]
    return rest.split(",", 1)[0].rstrip(">")


def _transform_chrom(chrom: str, chrom_style: str) -> str:
    if chrom_style == "input":
        return chrom
    if chrom_style == "no-chr":
        if chrom.startswith("chr"):
            stripped = chrom[3:]
            return "MT" if stripped == "M" else stripped
        return chrom
    if chrom.startswith("chr"):
        return chrom
    if chrom == "MT":
        return "chrM"
    return f"chr{chrom}"
