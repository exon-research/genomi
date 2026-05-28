from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SEQUENCE_SCHEMA_VERSION = "genomi-sequence-utility-v1"

CODON_TABLE = {
    "TTT": "F",
    "TTC": "F",
    "TTA": "L",
    "TTG": "L",
    "TCT": "S",
    "TCC": "S",
    "TCA": "S",
    "TCG": "S",
    "TAT": "Y",
    "TAC": "Y",
    "TAA": "*",
    "TAG": "*",
    "TGT": "C",
    "TGC": "C",
    "TGA": "*",
    "TGG": "W",
    "CTT": "L",
    "CTC": "L",
    "CTA": "L",
    "CTG": "L",
    "CCT": "P",
    "CCC": "P",
    "CCA": "P",
    "CCG": "P",
    "CAT": "H",
    "CAC": "H",
    "CAA": "Q",
    "CAG": "Q",
    "CGT": "R",
    "CGC": "R",
    "CGA": "R",
    "CGG": "R",
    "ATT": "I",
    "ATC": "I",
    "ATA": "I",
    "ATG": "M",
    "ACT": "T",
    "ACC": "T",
    "ACA": "T",
    "ACG": "T",
    "AAT": "N",
    "AAC": "N",
    "AAA": "K",
    "AAG": "K",
    "AGT": "S",
    "AGC": "S",
    "AGA": "R",
    "AGG": "R",
    "GTT": "V",
    "GTC": "V",
    "GTA": "V",
    "GTG": "V",
    "GCT": "A",
    "GCC": "A",
    "GCA": "A",
    "GCG": "A",
    "GAT": "D",
    "GAC": "D",
    "GAA": "E",
    "GAG": "E",
    "GGT": "G",
    "GGC": "G",
    "GGA": "G",
    "GGG": "G",
}

COMMON_ENZYMES = {
    "ECORI": "GAATTC",
    "BAMHI": "GGATCC",
    "HINDIII": "AAGCTT",
    "NOTI": "GCGGCCGC",
    "XHOI": "CTCGAG",
    "PSTI": "CTGCAG",
    "SMAI": "CCCGGG",
    "SALI": "GTCGAC",
    "KPNI": "GGTACC",
    "NCOI": "CCATGG",
    "NDEI": "CATATG",
    "SACI": "GAGCTC",
    "SPEI": "ACTAGT",
    "XBAI": "TCTAGA",
}

IUPAC = {
    "A": "A",
    "C": "C",
    "G": "G",
    "T": "T",
    "U": "T",
    "R": "[AG]",
    "Y": "[CT]",
    "S": "[GC]",
    "W": "[AT]",
    "K": "[GT]",
    "M": "[AC]",
    "B": "[CGT]",
    "D": "[AGT]",
    "H": "[ACT]",
    "V": "[ACG]",
    "N": "[ACGT]",
}


def translate_sequence(sequence: str, *, frame: int = 1, strand: str = "forward") -> dict[str, Any]:
    dna = _normalize_sequence(sequence)
    frame = _normalize_frame(frame)
    strand = _normalize_strand(strand)
    translated_dna = _strand_sequence(dna, strand)
    offset = frame - 1
    codons = [translated_dna[index : index + 3] for index in range(offset, len(translated_dna) - 2, 3)]
    amino_acids = "".join(CODON_TABLE.get(codon, "X") for codon in codons)
    return {
        "schema": SEQUENCE_SCHEMA_VERSION,
        "operation": "translate",
        "status": "completed",
        "query": {"frame": frame, "strand": strand, "sequence_length": len(dna)},
        "translation": {
            "amino_acids": amino_acids,
            "codon_count": len(codons),
            "codons": codons,
            "trailing_bases": len(translated_dna[offset:]) % 3,
        },
        "notes": ["Uses the standard nuclear genetic code."],
    }


def find_orfs(sequence: str, *, min_aa: int = 30, strand: str = "both") -> dict[str, Any]:
    dna = _normalize_sequence(sequence)
    strand = _normalize_strand(strand, allow_both=True)
    min_aa = max(0, int(min_aa or 0))
    strands = ["forward", "reverse"] if strand == "both" else [strand]
    orfs = []
    for strand_name in strands:
        seq = _strand_sequence(dna, strand_name)
        for frame in (1, 2, 3):
            orfs.extend(_orfs_in_frame(seq, original_length=len(dna), frame=frame, strand=strand_name, min_aa=min_aa))
    orfs.sort(key=lambda item: (-item["aa_length"], item["strand"], item["frame"], item["start"]))
    return {
        "schema": SEQUENCE_SCHEMA_VERSION,
        "operation": "find_orfs",
        "status": "completed",
        "query": {"sequence_length": len(dna), "min_aa": min_aa, "strand": strand},
        "orfs": orfs,
        "summary": {"orf_count": len(orfs), "longest_aa": orfs[0]["aa_length"] if orfs else 0},
    }


def find_restriction_sites(
    sequence: str,
    *,
    enzymes: list[str] | None = None,
    motifs: list[str] | None = None,
) -> dict[str, Any]:
    dna = _normalize_sequence(sequence)
    requested: dict[str, str] = {}
    for enzyme in enzymes or []:
        key = str(enzyme or "").strip().upper().replace("-", "")
        if key in COMMON_ENZYMES:
            requested[key] = COMMON_ENZYMES[key]
    for motif in motifs or []:
        motif_text = _normalize_sequence(motif, allow_ambiguous=True)
        if motif_text:
            requested[f"MOTIF_{motif_text}"] = motif_text
    if not requested:
        requested = dict(COMMON_ENZYMES)
    results = []
    for name, motif in requested.items():
        pattern = _iupac_regex(motif)
        matches = [
            {
                "start": match.start() + 1,
                "end": match.end(),
                "matched_sequence": dna[match.start() : match.end()],
            }
            for match in re.finditer(f"(?=({pattern}))", dna)
        ]
        results.append({"name": name, "motif": motif, "site_count": len(matches), "sites": matches})
    return {
        "schema": SEQUENCE_SCHEMA_VERSION,
        "operation": "restriction_sites",
        "status": "completed",
        "query": {"sequence_length": len(dna), "enzyme_count": len(requested)},
        "enzymes": results,
        "summary": {"total_sites": sum(item["site_count"] for item in results)},
    }


def kozak_context(sequence: str, *, start_pos: int | None = None) -> dict[str, Any]:
    dna = _normalize_sequence(sequence)
    starts = [start_pos - 1] if start_pos is not None else [match.start() for match in re.finditer("ATG", dna)]
    contexts = []
    for index in starts:
        if index < 0 or index + 3 > len(dna) or dna[index : index + 3] != "ATG":
            continue
        minus3 = dna[index - 3] if index >= 3 else None
        plus4 = dna[index + 3] if index + 3 < len(dna) else None
        strength = _kozak_strength(minus3, plus4)
        contexts.append(
            {
                "start": index + 1,
                "context": dna[max(0, index - 6) : min(len(dna), index + 7)],
                "minus3": minus3,
                "plus4": plus4,
                "strength": strength,
                "rule": "strong if -3 is A/G and +4 is G; moderate if one of the two positions matches",
            }
        )
    return {
        "schema": SEQUENCE_SCHEMA_VERSION,
        "operation": "kozak_context",
        "status": "completed",
        "query": {"sequence_length": len(dna), "start_pos": start_pos},
        "starts": contexts,
        "summary": {"start_count": len(contexts), "strong_count": sum(1 for item in contexts if item["strength"] == "strong")},
    }


def check_primers(
    *,
    forward_primer: str,
    reverse_primer: str | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    forward = _normalize_sequence(forward_primer, allow_ambiguous=True)
    reverse = _normalize_sequence(reverse_primer or "", allow_ambiguous=True)
    template_dna = _normalize_sequence(template or "", allow_ambiguous=True) if template else ""
    primer_rows = [_primer_row("forward", forward)]
    if reverse:
        primer_rows.append(_primer_row("reverse", reverse))
    amplicons: list[dict[str, Any]] = []
    if template_dna and forward and reverse:
        forward_hits = [match.start() for match in re.finditer(f"(?=({re.escape(forward)}))", template_dna)]
        reverse_binding = reverse_complement(reverse)
        reverse_hits = [match.start() for match in re.finditer(f"(?=({re.escape(reverse_binding)}))", template_dna)]
        for f_hit in forward_hits:
            for r_hit in reverse_hits:
                if r_hit <= f_hit:
                    continue
                amplicons.append(
                    {
                        "forward_start": f_hit + 1,
                        "reverse_binding_start": r_hit + 1,
                        "product_size": r_hit + len(reverse_binding) - f_hit,
                    }
                )
    return {
        "schema": SEQUENCE_SCHEMA_VERSION,
        "operation": "check_primers",
        "status": "completed",
        "primers": primer_rows,
        "template": {"provided": bool(template), "length": len(template_dna) if template_dna else None},
        "amplicons": amplicons,
        "summary": {
            "primer_count": len(primer_rows),
            "amplicon_count": len(amplicons),
            "warnings": _primer_warnings(primer_rows, amplicons, template_provided=bool(template)),
        },
    }


def match_reference_records(
    sequence: str,
    reference_fasta: str | Path,
    *,
    max_matches: int = 10,
) -> dict[str, Any]:
    query = _normalize_sequence(sequence, allow_ambiguous=True)
    reference_path = Path(reference_fasta).expanduser()
    if not reference_path.exists():
        raise FileNotFoundError(str(reference_path))
    records = _read_fasta_records(reference_path)
    matches = []
    for record in records:
        matches.extend(_reference_matches(query, record))
    matches.sort(key=lambda item: (-float(item["query_coverage"]), item["record_id"], item["strand"], item["start"]))
    emitted = matches[: max(0, int(max_matches or 0))]
    return {
        "schema": "genomi-sequence-reference-match-v1",
        "operation": "match_reference_records",
        "status": "matched" if emitted else "no_reference_match",
        "query": {
            "sequence_length": len(query),
            "reference_fasta": str(reference_path),
            "reference_record_count": len(records),
            "max_matches": max_matches,
        },
        "identity_chain": {
            "input_sequence": {"length": len(query), "type": "dna"},
            "reference_matches": emitted,
            "matched_record_ids": [match["record_id"] for match in emitted],
            "unresolved_components": [] if emitted else ["reference_record_match"],
        },
        "reference_matches": emitted,
        "notes": [
            "Matches are exact substring/exact-record matches against the supplied local FASTA only.",
            "The host agent decides whether a matched reference record answers the user question.",
        ],
    }


def reverse_complement(sequence: str) -> str:
    dna = _normalize_sequence(sequence, allow_ambiguous=True)
    table = str.maketrans("ACGTRYKMSWBDHVN", "TGCAYRMKSWVHDBN")
    return dna.translate(table)[::-1]


def _read_fasta_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    header: str | None = None
    chunks: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    records.append(_fasta_record(header, chunks))
                header = line[1:].strip()
                chunks = []
            else:
                chunks.append(line)
    if header is not None:
        records.append(_fasta_record(header, chunks))
    return records


def _fasta_record(header: str, chunks: list[str]) -> dict[str, Any]:
    parts = header.split(None, 1)
    record_id = parts[0] if parts else "record"
    description = parts[1] if len(parts) > 1 else ""
    return {
        "record_id": record_id,
        "description": description,
        "annotations": _header_annotations(description),
        "sequence": _normalize_sequence("".join(chunks), allow_ambiguous=True),
    }


def _reference_matches(query: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for strand, target in (("forward", query), ("reverse", reverse_complement(query))):
        output.extend(_record_match_rows(target, record, strand=strand))
    return output


def _record_match_rows(query: str, record: dict[str, Any], *, strand: str) -> list[dict[str, Any]]:
    ref = record["sequence"]
    if not query or not ref:
        return []
    rows = []
    if query == ref:
        rows.append(_reference_match_row(record, strand=strand, match_type="exact_record", start=1, end=len(ref), query_length=len(query)))
    elif query in ref:
        start = ref.index(query) + 1
        rows.append(_reference_match_row(record, strand=strand, match_type="query_subsequence_of_record", start=start, end=start + len(query) - 1, query_length=len(query)))
    elif ref in query:
        rows.append(_reference_match_row(record, strand=strand, match_type="record_subsequence_of_query", start=1, end=len(ref), query_length=len(query)))
    return rows


def _reference_match_row(
    record: dict[str, Any],
    *,
    strand: str,
    match_type: str,
    start: int,
    end: int,
    query_length: int,
) -> dict[str, Any]:
    matched_length = abs(end - start) + 1
    record_length = len(record["sequence"])
    return {
        "record_id": record["record_id"],
        "description": record["description"],
        "annotations": record["annotations"],
        "match_type": match_type,
        "strand": strand,
        "start": start,
        "end": end,
        "matched_length": matched_length,
        "query_coverage": round(matched_length / query_length, 4) if query_length else 0,
        "record_coverage": round(matched_length / record_length, 4) if record_length else 0,
    }


def _header_annotations(description: str) -> dict[str, str]:
    annotations = {}
    for token in re.split(r"\s+", description):
        if "=" in token:
            key, value = token.split("=", 1)
        elif ":" in token:
            key, value = token.split(":", 1)
        else:
            continue
        key = key.strip().strip(";,.").lower()
        value = value.strip().strip(";,.")
        if key and value:
            annotations[key] = value
    return annotations


def _orfs_in_frame(seq: str, *, original_length: int, frame: int, strand: str, min_aa: int) -> list[dict[str, Any]]:
    output = []
    offset = frame - 1
    active_start: int | None = None
    for index in range(offset, len(seq) - 2, 3):
        codon = seq[index : index + 3]
        if codon == "ATG" and active_start is None:
            active_start = index
        if codon in {"TAA", "TAG", "TGA"} and active_start is not None:
            aa_seq = "".join(CODON_TABLE.get(seq[pos : pos + 3], "X") for pos in range(active_start, index + 3, 3))
            aa_length = max(0, len(aa_seq) - 1)
            if aa_length >= min_aa:
                start, end = _original_coordinates(active_start, index + 3, original_length=original_length, strand=strand)
                output.append(
                    {
                        "strand": strand,
                        "frame": frame,
                        "start": start,
                        "end": end,
                        "nt_length": abs(end - start) + 1,
                        "aa_length": aa_length,
                        "stop_codon": codon,
                        "translation": aa_seq,
                    }
                )
            active_start = None
    return output


def _original_coordinates(start0: int, end0_exclusive: int, *, original_length: int, strand: str) -> tuple[int, int]:
    if strand == "forward":
        return start0 + 1, end0_exclusive
    return original_length - end0_exclusive + 1, original_length - start0


def _primer_row(name: str, sequence: str) -> dict[str, Any]:
    gc = _gc_fraction(sequence)
    return {
        "name": name,
        "sequence": sequence,
        "length": len(sequence),
        "gc_percent": round(gc * 100, 1) if sequence else 0,
        "tm_wallace_c": _wallace_tm(sequence),
        "self_complementarity_3prime": _three_prime_self_complementarity(sequence),
    }


def _primer_warnings(primer_rows: list[dict[str, Any]], amplicons: list[dict[str, Any]], *, template_provided: bool) -> list[str]:
    warnings = []
    for row in primer_rows:
        if row["length"] < 18 or row["length"] > 30:
            warnings.append(f"{row['name']}_length_outside_common_range")
        if row["gc_percent"] < 35 or row["gc_percent"] > 65:
            warnings.append(f"{row['name']}_gc_outside_common_range")
        if row["self_complementarity_3prime"] >= 4:
            warnings.append(f"{row['name']}_3prime_self_complementarity")
    if template_provided and not amplicons:
        warnings.append("no_forward_reverse_amplicon_found")
    if len(amplicons) > 1:
        warnings.append("multiple_amplicons_found")
    return warnings


def _three_prime_self_complementarity(sequence: str) -> int:
    tail = sequence[-8:]
    rc = reverse_complement(sequence)
    best = 0
    for size in range(1, min(len(tail), len(rc)) + 1):
        if tail[-size:] in rc:
            best = size
    return best


def _wallace_tm(sequence: str) -> int:
    counts = {base: sequence.count(base) for base in "ACGT"}
    return 2 * (counts["A"] + counts["T"]) + 4 * (counts["G"] + counts["C"])


def _gc_fraction(sequence: str) -> float:
    if not sequence:
        return 0.0
    return (sequence.count("G") + sequence.count("C")) / len(sequence)


def _kozak_strength(minus3: str | None, plus4: str | None) -> str:
    minus3_ok = minus3 in {"A", "G"}
    plus4_ok = plus4 == "G"
    if minus3_ok and plus4_ok:
        return "strong"
    if minus3_ok or plus4_ok:
        return "moderate"
    return "weak"


def _iupac_regex(motif: str) -> str:
    return "".join(IUPAC.get(base, re.escape(base)) for base in motif.upper())


def _normalize_sequence(sequence: str, *, allow_ambiguous: bool = False) -> str:
    allowed = set(IUPAC) if allow_ambiguous else {"A", "C", "G", "T", "U"}
    normalized = "".join(base for base in str(sequence or "").upper() if not base.isspace())
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError("sequence contains unsupported bases: " + ", ".join(invalid))
    return normalized.replace("U", "T")


def _normalize_frame(frame: int) -> int:
    value = int(frame)
    if value not in {1, 2, 3}:
        raise ValueError("frame must be 1, 2, or 3")
    return value


def _normalize_strand(strand: str, *, allow_both: bool = False) -> str:
    value = str(strand or "forward").strip().lower()
    aliases = {"+": "forward", "fwd": "forward", "-": "reverse", "rev": "reverse"}
    value = aliases.get(value, value)
    allowed = {"forward", "reverse", "both"} if allow_both else {"forward", "reverse"}
    if value not in allowed:
        raise ValueError("strand must be forward, reverse" + (", or both" if allow_both else ""))
    return value


def _strand_sequence(dna: str, strand: str) -> str:
    return reverse_complement(dna) if strand == "reverse" else dna
