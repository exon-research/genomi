from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from ...runtime.paths import run_output_path_for_source

JsonObject = dict[str, Any]

OUTSIDE_CALL_SCHEMA = "genomi-pgx-outside-call-validation-v1"
OUTSIDE_CALL_PREPARE_SCHEMA = "genomi-pgx-outside-call-prepare-v1"
PHARMCAT_OUTSIDE_CALL_URL = "https://pharmcat.clinpgx.org/using/Outside-Call-Format/"
PHARMCAT_HLA_URL = "https://pharmcat.clinpgx.org/using/Calling-HLA/"
PHARMCAT_CYP2D6_URL = "https://pharmcat.clinpgx.org/using/Calling-CYP2D6/"

_HEADER_ALIASES = {
    "gene",
    "diplotype",
    "phenotype",
    "activityscore",
    "activity_score",
    "activity score",
}

CALLER_FORMATS = ("auto", "pharmcat_tsv", "generic_table", "optitype", "stellarpgx_summary")


def validate_outside_call_file(
    outside_call_file: str | Path | None,
    *,
    max_rows: int = 200,
) -> JsonObject:
    """Validate PharmCAT outside-call TSV shape without exposing the file path."""

    if outside_call_file is None or str(outside_call_file).strip() == "":
        return {
            "schema": OUTSIDE_CALL_SCHEMA,
            "ok": False,
            "status": "missing_outside_call_file",
            "input": {"hidden_intake_source": True},
            "traceability": _traceability(),
        }
    path = Path(outside_call_file).expanduser()
    if not path.exists():
        return {
            "schema": OUTSIDE_CALL_SCHEMA,
            "ok": False,
            "status": "missing_outside_call_file",
            "input": {"hidden_intake_source": True},
            "traceability": _traceability(),
        }
    if not path.is_file():
        return {
            "schema": OUTSIDE_CALL_SCHEMA,
            "ok": False,
            "status": "invalid_outside_call_file",
            "input": _input_descriptor(path),
            "invalid_rows": [{"line_number": None, "reason": "not_a_file"}],
            "traceability": _traceability(),
        }

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return {
            "schema": OUTSIDE_CALL_SCHEMA,
            "ok": False,
            "status": "encoding_error",
            "input": _input_descriptor(path),
            "message": f"Outside-call file must be UTF-8 encoded: {exc.reason}",
            "traceability": _traceability(),
        }
    except OSError as exc:
        return {
            "schema": OUTSIDE_CALL_SCHEMA,
            "ok": False,
            "status": "read_error",
            "input": _input_descriptor(path),
            "message": str(exc),
            "traceability": _traceability(),
        }

    records, invalid_rows, warnings = _parse_rows(text, max_rows=max_rows)
    genes = sorted({record["gene"] for record in records})
    duplicate_genes = sorted(_duplicates(record["gene"] for record in records))
    for gene in duplicate_genes:
        warnings.append(
            {
                "code": "duplicate_outside_call_gene",
                "gene": gene,
                "message": "Multiple outside-call rows for the same gene should be reviewed before PharmCAT execution.",
            }
        )

    status = "completed" if records and not invalid_rows else "invalid_outside_call_file"
    if not records and not invalid_rows:
        status = "empty_outside_call_file"
    return {
        "schema": OUTSIDE_CALL_SCHEMA,
        "ok": status == "completed",
        "status": status,
        "input": _input_descriptor(path),
        "format": {
            "encoding": "utf-8",
            "delimiter": "tab",
            "fields": ["gene", "diplotype", "phenotype", "activity_score"],
            "required": ["gene", "at_least_one_of_diplotype_phenotype_activity_score"],
        },
        "summary": {
            "row_count": len(records) + len(invalid_rows),
            "valid_row_count": len(records),
            "invalid_row_count": len(invalid_rows),
            "gene_count": len(genes),
            "genes": genes,
        },
        "rows": records,
        "invalid_rows": invalid_rows,
        "warnings": warnings,
        "traceability": _traceability(),
    }

def prepare_outside_call_file(
    caller_output_file: str | Path | None,
    *,
    caller_format: str = "auto",
    output_file: str | Path | None = None,
    sample: str | None = None,
    max_rows: int = 200,
) -> JsonObject:
    """Prepare a PharmCAT outside-call TSV from supported specialized caller output."""

    requested_format = _normalize_caller_format(caller_format)
    if requested_format not in CALLER_FORMATS:
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "unsupported_caller_format",
            "input": {"hidden_intake_source": True},
            "caller_format": requested_format,
            "supported_caller_formats": list(CALLER_FORMATS),
            "traceability": _traceability(),
        }
    if caller_output_file is None or str(caller_output_file).strip() == "":
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "missing_caller_output_file",
            "input": {"hidden_intake_source": True},
            "caller_format": requested_format,
            "traceability": _traceability(),
        }
    input_path = Path(caller_output_file).expanduser()
    if not input_path.exists():
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "missing_caller_output_file",
            "input": {"hidden_intake_source": True},
            "caller_format": requested_format,
            "traceability": _traceability(),
        }
    if not input_path.is_file():
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "invalid_caller_output_file",
            "input": _input_descriptor(input_path),
            "caller_format": requested_format,
            "invalid_rows": [{"line_number": None, "reason": "not_a_file"}],
            "traceability": _traceability(),
        }
    try:
        text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "encoding_error",
            "input": _input_descriptor(input_path),
            "caller_format": requested_format,
            "message": f"Caller output file must be UTF-8 encoded: {exc.reason}",
            "traceability": _traceability(),
        }
    except OSError as exc:
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": "read_error",
            "input": _input_descriptor(input_path),
            "caller_format": requested_format,
            "message": str(exc),
            "traceability": _traceability(),
        }

    detected_format = _detect_caller_format(text) if requested_format == "auto" else requested_format
    rows, invalid_rows, warnings = _prepare_rows(text, caller_format=detected_format, sample=sample, max_rows=max_rows)
    if invalid_rows or not rows:
        status = "empty_prepared_outside_call" if not rows and not invalid_rows else "invalid_caller_output_file"
        return {
            "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
            "ok": False,
            "status": status,
            "input": _input_descriptor(input_path),
            "caller_format": detected_format,
            "sample": sample,
            "summary": _prepared_summary(rows, invalid_rows),
            "rows": rows,
            "invalid_rows": invalid_rows,
            "warnings": warnings,
            "traceability": _traceability(),
        }

    output_path = Path(output_file).expanduser() if output_file else run_output_path_for_source(
        input_path,
        "pharmcat-outside-calls.tsv",
        source_format=f"pgx-{detected_format}",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_outside_call_tsv(output_path, rows)
    validation = validate_outside_call_file(output_path, max_rows=max_rows)
    return {
        "schema": OUTSIDE_CALL_PREPARE_SCHEMA,
        "ok": bool(validation.get("ok")),
        "status": "completed" if validation.get("ok") else "prepared_validation_failed",
        "input": _input_descriptor(input_path),
        "caller_format": detected_format,
        "sample": sample,
        "output": {
            "path": str(output_path.expanduser().resolve(strict=False)),
            "hidden_source_path": True,
            "size_bytes": _size(output_path),
            "content_sha256": _sha256(output_path),
        },
        "summary": _prepared_summary(rows, invalid_rows),
        "rows": rows,
        "invalid_rows": invalid_rows,
        "warnings": warnings,
        "validation": validation,
        "traceability": _traceability(),
        "prepared_artifact": {
            "artifact_type": "pharmcat_outside_call_tsv",
            "outside_call_file": str(output_path.expanduser().resolve(strict=False)),
            "validated": bool(validation.get("ok")),
            "selected_gene_count": len({str(row["gene"]) for row in rows if row.get("gene")}),
        },
    }


def _parse_rows(text: str, *, max_rows: int) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    records: list[JsonObject] = []
    invalid_rows: list[JsonObject] = []
    warnings: list[JsonObject] = []
    reader = csv.reader(text.splitlines(), delimiter="\t")
    seen_data = False
    for line_number, fields in enumerate(reader, start=1):
        if not fields or all(not field.strip() for field in fields):
            continue
        normalized_fields = [field.strip() for field in fields]
        if not seen_data and _looks_like_header(normalized_fields):
            seen_data = True
            continue
        seen_data = True
        if len(normalized_fields) > 4:
            invalid_rows.append(
                {
                    "line_number": line_number,
                    "reason": "too_many_fields",
                    "field_count": len(normalized_fields),
                }
            )
            continue
        padded = normalized_fields + [""] * (4 - len(normalized_fields))
        gene, diplotype, phenotype, activity_score = padded[:4]
        clean_gene = _normalize_gene(gene)
        present_evidence = [value for value in (diplotype, phenotype, activity_score) if value.strip()]
        if not clean_gene:
            invalid_rows.append({"line_number": line_number, "reason": "missing_gene"})
            continue
        if not present_evidence:
            invalid_rows.append(
                {
                    "line_number": line_number,
                    "gene": clean_gene,
                    "reason": "missing_diplotype_phenotype_or_activity_score",
                }
            )
            continue
        if activity_score and not _looks_numeric(activity_score):
            warnings.append(
                {
                    "code": "non_numeric_activity_score",
                    "line_number": line_number,
                    "gene": clean_gene,
                    "message": "Review activity score formatting before PharmCAT execution.",
                }
            )
        if len(records) < max_rows:
            records.append(
                {
                    "line_number": line_number,
                    "gene": clean_gene,
                    "diplotype": diplotype or None,
                    "phenotype": phenotype or None,
                    "activity_score": activity_score or None,
                    "evidence_fields": [
                        name
                        for name, value in (
                            ("diplotype", diplotype),
                            ("phenotype", phenotype),
                            ("activity_score", activity_score),
                        )
                        if value
                    ],
                }
            )
    return records, invalid_rows, warnings


def _normalize_caller_format(value: str | None) -> str:
    cleaned = "_".join(str(value or "auto").strip().lower().replace("-", "_").split())
    aliases = {
        "pharmcat": "pharmcat_tsv",
        "outside_call": "pharmcat_tsv",
        "outside_calls": "pharmcat_tsv",
        "tsv": "pharmcat_tsv",
        "generic": "generic_table",
        "table": "generic_table",
        "optitype_tsv": "optitype",
        "opti_type": "optitype",
        "stellarpgx": "stellarpgx_summary",
        "stellarpgx_summary_txt": "stellarpgx_summary",
        "stellar_pgx": "stellarpgx_summary",
    }
    return aliases.get(cleaned, cleaned or "auto")


def _detect_caller_format(text: str) -> str:
    first_fields = _first_data_fields(text)
    keys = {_header_key(field) for field in first_fields}
    if {"a1", "a2", "b1", "b2"} <= keys:
        return "optitype"
    if len(first_fields) >= 2 and _looks_like_stellarpgx_call(first_fields[1]):
        return "stellarpgx_summary"
    if first_fields and _looks_like_header(first_fields):
        return "generic_table"
    return "pharmcat_tsv"


def _first_data_fields(text: str) -> list[str]:
    delimiter = _detect_delimiter(text)
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    for fields in reader:
        if not fields or all(not field.strip() for field in fields):
            continue
        return [field.strip() for field in fields]
    return []


def _prepare_rows(text: str, *, caller_format: str, sample: str | None, max_rows: int) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    if caller_format == "optitype":
        return _prepare_optitype_rows(text, max_rows=max_rows)
    if caller_format == "stellarpgx_summary":
        return _prepare_stellarpgx_summary_rows(text, sample=sample, max_rows=max_rows)
    if caller_format == "generic_table":
        return _prepare_generic_table_rows(text, max_rows=max_rows)
    if caller_format == "pharmcat_tsv":
        return _parse_rows(text, max_rows=max_rows)
    return [], [{"line_number": None, "reason": "unsupported_caller_format", "caller_format": caller_format}], []


def _prepare_optitype_rows(text: str, *, max_rows: int) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    rows: list[JsonObject] = []
    invalid_rows: list[JsonObject] = []
    warnings: list[JsonObject] = []
    reader = csv.DictReader(text.splitlines(), delimiter=_detect_delimiter(text))
    if not reader.fieldnames:
        return [], [{"line_number": None, "reason": "missing_header"}], warnings
    field_map = {_header_key(field): field for field in reader.fieldnames if field is not None}
    missing = [field for field in ("a1", "a2", "b1", "b2") if field not in field_map]
    if missing:
        return [], [{"line_number": 1, "reason": "missing_optitype_columns", "missing_columns": missing}], warnings
    for index, row in enumerate(reader, start=2):
        if len(rows) >= max_rows:
            warnings.append({"code": "max_rows_reached", "message": "Prepared rows were truncated at max_rows."})
            break
        for gene, first_key, second_key in (("HLA-A", "a1", "a2"), ("HLA-B", "b1", "b2")):
            allele1 = _format_hla_allele(row.get(field_map[first_key]), gene=gene)
            allele2 = _format_hla_allele(row.get(field_map[second_key]), gene=gene)
            if allele1 and allele2:
                rows.append(_outside_call_row(line_number=index, gene=gene, diplotype=f"{allele1}/{allele2}"))
            else:
                invalid_rows.append(
                    {
                        "line_number": index,
                        "gene": gene,
                        "reason": "missing_hla_alleles",
                        "observed": [row.get(field_map[first_key]), row.get(field_map[second_key])],
                    }
                )
    return rows, invalid_rows, warnings


def _prepare_stellarpgx_summary_rows(
    text: str,
    *,
    sample: str | None,
    max_rows: int,
) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    parsed_rows: list[tuple[int, str, str, str | None]] = []
    invalid_rows: list[JsonObject] = []
    warnings: list[JsonObject] = []
    selected_sample = _clean_cell(sample)
    reader = csv.reader(text.splitlines(), delimiter="\t")
    for line_number, fields in enumerate(reader, start=1):
        if not fields or all(not field.strip() for field in fields):
            continue
        if len(fields) < 2:
            invalid_rows.append({"line_number": line_number, "reason": "missing_sample_or_cyp2d6_call"})
            continue
        sample_id = _clean_cell(fields[0])
        call = _clean_stellarpgx_call(fields[1])
        note = _clean_cell(fields[2]) if len(fields) > 2 else None
        if not sample_id or not call:
            invalid_rows.append({"line_number": line_number, "reason": "missing_sample_or_cyp2d6_call"})
            continue
        parsed_rows.append((line_number, sample_id, call, note))
    if selected_sample:
        parsed_rows = [row for row in parsed_rows if row[1] == selected_sample]
        if not parsed_rows:
            invalid_rows.append({"line_number": None, "reason": "sample_not_found", "sample": selected_sample})
            return [], invalid_rows, warnings
    elif len(parsed_rows) > 1:
        invalid_rows.append(
            {
                "line_number": None,
                "reason": "multiple_samples_require_sample",
                "sample_count": len(parsed_rows),
                "samples": [row[1] for row in parsed_rows[:20]],
            }
        )
        return [], invalid_rows, warnings
    rows: list[JsonObject] = []
    for line_number, sample_id, call, note in parsed_rows[:max_rows]:
        if call.casefold() in {"no_call", "nocall", "no call"}:
            invalid_rows.append({"line_number": line_number, "sample": sample_id, "gene": "CYP2D6", "reason": "no_call"})
            continue
        if note:
            warnings.append(
                {
                    "code": "stellarpgx_note",
                    "line_number": line_number,
                    "sample": sample_id,
                    "message": note,
                }
            )
        rows.append(_outside_call_row(line_number=line_number, gene="CYP2D6", diplotype=call))
    return rows, invalid_rows, warnings


def _prepare_generic_table_rows(text: str, *, max_rows: int) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
    rows: list[JsonObject] = []
    invalid_rows: list[JsonObject] = []
    warnings: list[JsonObject] = []
    reader = csv.DictReader(text.splitlines(), delimiter=_detect_delimiter(text))
    if not reader.fieldnames:
        return [], [{"line_number": None, "reason": "missing_header"}], warnings
    field_map = _generic_field_map(reader.fieldnames)
    if "gene" not in field_map:
        return [], [{"line_number": 1, "reason": "missing_gene_column"}], warnings
    if not any(key in field_map for key in ("diplotype", "phenotype", "activity_score")):
        return [], [{"line_number": 1, "reason": "missing_evidence_columns"}], warnings
    for index, row in enumerate(reader, start=2):
        if len(rows) >= max_rows:
            warnings.append({"code": "max_rows_reached", "message": "Prepared rows were truncated at max_rows."})
            break
        gene = _normalize_gene(row.get(field_map["gene"], ""))
        diplotype = _clean_cell(row.get(field_map.get("diplotype", ""), ""))
        phenotype = _clean_cell(row.get(field_map.get("phenotype", ""), ""))
        activity_score = _clean_cell(row.get(field_map.get("activity_score", ""), ""))
        if not gene:
            invalid_rows.append({"line_number": index, "reason": "missing_gene"})
            continue
        if not any((diplotype, phenotype, activity_score)):
            invalid_rows.append({"line_number": index, "gene": gene, "reason": "missing_diplotype_phenotype_or_activity_score"})
            continue
        if activity_score and not _looks_numeric(activity_score):
            warnings.append(
                {
                    "code": "non_numeric_activity_score",
                    "line_number": index,
                    "gene": gene,
                    "message": "Review activity score formatting before PharmCAT execution.",
                }
            )
        rows.append(
            _outside_call_row(
                line_number=index,
                gene=gene,
                diplotype=diplotype or None,
                phenotype=phenotype or None,
                activity_score=activity_score or None,
            )
        )
    return rows, invalid_rows, warnings


def _generic_field_map(fieldnames: list[str | None]) -> dict[str, str]:
    aliases = {
        "gene": "gene",
        "hgnc gene symbol": "gene",
        "hgnc symbol": "gene",
        "symbol": "gene",
        "diplotype": "diplotype",
        "source diplotype": "diplotype",
        "recommendation lookup diplotype": "diplotype",
        "allele": "diplotype",
        "alleles": "diplotype",
        "phenotype": "phenotype",
        "gene result": "phenotype",
        "activityscore": "activity_score",
        "activity score": "activity_score",
        "activity_score": "activity_score",
    }
    result: dict[str, str] = {}
    for field in fieldnames:
        if field is None:
            continue
        key = aliases.get(_header_key(field))
        if key and key not in result:
            result[key] = field
    return result


def _outside_call_row(
    *,
    line_number: int,
    gene: str,
    diplotype: str | None = None,
    phenotype: str | None = None,
    activity_score: str | None = None,
) -> JsonObject:
    return {
        "line_number": line_number,
        "gene": gene,
        "diplotype": diplotype or None,
        "phenotype": phenotype or None,
        "activity_score": activity_score or None,
        "evidence_fields": [
            name
            for name, value in (
                ("diplotype", diplotype),
                ("phenotype", phenotype),
                ("activity_score", activity_score),
            )
            if value
        ],
    }


def _format_hla_allele(value: object, *, gene: str) -> str | None:
    allele = _clean_cell(value)
    if not allele:
        return None
    prefix = gene.split("-", 1)[1]
    if allele.upper().startswith(f"{prefix}*"):
        allele = allele[len(prefix) :]
    if allele.upper().startswith(f"HLA-{prefix}*"):
        allele = allele[len(f"HLA-{prefix}") :]
    if not allele.startswith("*") and ":" in allele:
        allele = f"*{allele}"
    return allele or None


def _looks_like_stellarpgx_call(value: object) -> bool:
    call = _clean_stellarpgx_call(value)
    if not call:
        return False
    return call.casefold() in {"no_call", "nocall"} or "*" in call


def _clean_stellarpgx_call(value: object) -> str:
    call = _clean_cell(value)
    call = call.strip("[] ")
    return call


def _write_outside_call_tsv(path: Path, rows: list[JsonObject]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["gene", "diplotype", "phenotype", "activityScore"])
        for row in rows:
            writer.writerow(
                [
                    row.get("gene") or "",
                    row.get("diplotype") or "",
                    row.get("phenotype") or "",
                    row.get("activity_score") or "",
                ]
            )


def _prepared_summary(rows: list[JsonObject], invalid_rows: list[JsonObject]) -> JsonObject:
    genes = sorted({str(record["gene"]) for record in rows if record.get("gene")})
    return {
        "row_count": len(rows) + len(invalid_rows),
        "prepared_row_count": len(rows),
        "invalid_row_count": len(invalid_rows),
        "gene_count": len(genes),
        "genes": genes,
    }


def _detect_delimiter(text: str) -> str:
    for line in text.splitlines():
        if not line.strip():
            continue
        return "\t" if line.count("\t") >= line.count(",") else ","
    return "\t"


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _looks_like_header(fields: list[str]) -> bool:
    first = _header_key(fields[0]) if fields else ""
    if first != "gene":
        return False
    return any(_header_key(field) in _HEADER_ALIASES for field in fields[1:])


def _header_key(value: str) -> str:
    return " ".join(str(value).strip().lstrip("\ufeff").lower().replace("_", " ").split())


def _normalize_gene(value: str) -> str:
    return " ".join(str(value).strip().split()).upper()


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _duplicates(values: Any) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _input_descriptor(path: Path) -> JsonObject:
    return {
        "hidden_intake_source": True,
        "size_bytes": _size(path),
        "content_sha256": _sha256(path),
    }


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _traceability() -> JsonObject:
    return {
        "source_tool": "PharmCAT",
        "definition_and_guideline_sources": [
            {
                "title": "PharmCAT Outside Call Format",
                "url": PHARMCAT_OUTSIDE_CALL_URL,
                "type": "input_requirements",
            },
            {
                "title": "PharmCAT Calling HLA",
                "url": PHARMCAT_HLA_URL,
                "type": "specialized_caller_integration",
            },
            {
                "title": "PharmCAT Calling CYP2D6",
                "url": PHARMCAT_CYP2D6_URL,
                "type": "specialized_caller_integration",
            }
        ],
    }
