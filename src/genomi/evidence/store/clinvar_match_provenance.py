from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any


MATCH_BASIS_EXACT_ALLELE = "exact_allele"
MATCH_BASIS_MULTIALLELIC_ALT = "multiallelic_alt"
MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE = "consumer_array_allele_inference"
MATCH_BASIS_LIFTOVER_EXACT_ALLELE = "liftover_exact_allele"
MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT = "liftover_multiallelic_alt"
MATCH_BASIS_UNKNOWN = "unknown_match_basis"


def build_clinvar_match_payload(
    *,
    sample_variant: dict[str, Any],
    clinvar: dict[str, Any],
    match_basis: str | None = None,
    match_kind: str | None = None,
    source_format: str | None = None,
    source_record: dict[str, Any] | None = None,
    inferred_clinvar_allele: dict[str, Any] | None = None,
    liftover: dict[str, Any] | None = None,
) -> dict[str, Any]:
    basis = match_basis or MATCH_BASIS_UNKNOWN
    kind = match_kind or basis
    sample = dict(sample_variant)
    source = dict(source_record or {})
    source_format = source_format or source.get("source_format")
    if source_format is not None:
        sample["source_format"] = source_format
    _copy_source_record_field(sample, source, "ref")
    _copy_source_record_field(sample, source, "alt")
    _copy_source_record_field(sample, source, "format")
    _copy_source_record_field(sample, source, "genotype")
    _copy_source_record_field(sample, source, "record_kind")
    _copy_source_record_field(sample, source, "observed_alleles")
    if source.get("format") is not None:
        sample["format"] = source["format"]

    provenance: dict[str, Any] = {
        "match_basis": basis,
        "match_kind": kind,
        "evidence_scope": _evidence_scope_for_match_basis(basis),
        "asserted_sample_allele": {
            "chrom": sample.get("chrom"),
            "pos": sample.get("pos"),
            "ref": sample.get("ref"),
            "alt": sample.get("alt"),
        },
    }
    if source_format is not None:
        provenance["source_format"] = source_format
    if source:
        provenance["source_record"] = {
            key: source.get(key)
            for key in ("chrom", "pos", "ref", "alt", "format", "genotype", "record_kind", "observed_alleles")
            if source.get(key) is not None
        }
    if inferred_clinvar_allele is not None:
        provenance["inferred_clinvar_allele"] = inferred_clinvar_allele

    payload: dict[str, Any] = {
        "match_basis": basis,
        "match_kind": kind,
        "sample_variant": sample,
        "clinvar": dict(clinvar),
        "match_provenance": provenance,
    }
    if source_format is not None:
        payload["source_format"] = source_format
    if liftover is not None:
        payload["liftover"] = liftover
    return payload


def match_basis_from_record(item: dict[str, Any]) -> str:
    basis = item.get("match_basis")
    if basis:
        return str(basis)
    provenance = item.get("match_provenance")
    if isinstance(provenance, dict) and provenance.get("match_basis"):
        return str(provenance["match_basis"])
    return MATCH_BASIS_UNKNOWN


def match_kind_from_record(item: dict[str, Any]) -> str:
    kind = item.get("match_kind")
    if kind:
        return str(kind)
    provenance = item.get("match_provenance")
    if isinstance(provenance, dict) and provenance.get("match_kind"):
        return str(provenance["match_kind"])
    return match_basis_from_record(item)


def _write_clinvar_match_rows(
    handle: Any,
    rows: Iterable[sqlite3.Row],
    *,
    sample_build: str | None = None,
    cache_build: str | None = None,
    default_source_format: str | None = None,
) -> dict[str, int]:
    matched_batch_ids: set[str] = set()
    written_records = 0
    clinvar_fields = (
        "chrom",
        "pos",
        "ref",
        "alt",
        "genome_build",
        "clinvar_id",
        "allele_id",
        "clinical_significance",
        "review_status",
        "conditions",
        "gene_info",
        "hgvs",
        "source_path",
        "source_version",
        "imported_at",
    )
    row_keys: set[str] | None = None
    for row in rows:
        if row_keys is None:
            row_keys = set(row.keys())
        batch_id = str(row["batch_id"])
        matched_batch_ids.add(batch_id)
        source_format = (
            _row_value(row, row_keys, "source_format")
            or default_source_format
            or _source_format_from_info(_row_value(row, row_keys, "source_record_info"))
        )
        source_record = {
            "chrom": row["sample_chrom"],
            "pos": int(row["sample_pos"]),
            "ref": _row_value(row, row_keys, "source_record_ref") or row["sample_ref"],
            "alt": _row_value(row, row_keys, "source_record_alt") or row["sample_alt"],
            "format": _row_value(row, row_keys, "source_record_format"),
            "genotype": _row_value(row, row_keys, "source_record_genotype") or row["genotype"],
            "record_kind": _row_value(row, row_keys, "source_record_kind"),
            "observed_alleles": _json_list_or_none(_row_value(row, row_keys, "source_record_observed_alleles")),
            "source_format": source_format,
        }
        sample_variant: dict[str, Any] = {
            "chrom": row["sample_chrom"],
            "pos": int(row["sample_pos"]),
            "id": row["sample_rsid"],
            "sample_index": row["sample_index"],
            "sample_name": row["sample_name"],
            "ref": row["sample_ref"],
            "alt": row["sample_alt"],
            "qual": row["sample_qual"],
            "filter": row["sample_filter"],
            "genotype": row["genotype"],
            "depth": row["depth"],
            "genotype_quality": row["genotype_quality"],
        }
        if source_record.get("record_kind") is not None:
            sample_variant["record_kind"] = source_record["record_kind"]
        if source_record.get("observed_alleles") is not None:
            sample_variant["observed_alleles"] = source_record["observed_alleles"]
        if sample_build is not None:
            sample_variant["genome_build"] = sample_build
        inferred_clinvar_allele = _inferred_clinvar_allele(row, row_keys)
        liftover = None
        if (
            cache_build is not None
            and "lifted_chrom" in row_keys
            and row["lifted_chrom"] is not None
            and row["lifted_pos"] is not None
        ):
            liftover = {
                "source_build": sample_build,
                "target_build": cache_build,
                "lifted_chrom": row["lifted_chrom"],
                "lifted_pos": int(row["lifted_pos"]),
                "chain": "UCSC pyliftover",
            }
        payload = build_clinvar_match_payload(
            sample_variant=sample_variant,
            clinvar={field: row[field] for field in clinvar_fields},
            match_basis=_row_value(row, row_keys, "match_basis"),
            match_kind=_row_value(row, row_keys, "match_kind"),
            source_format=source_format,
            source_record=source_record,
            inferred_clinvar_allele=inferred_clinvar_allele,
            liftover=liftover,
        )
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        written_records += 1

    return {
        "matched_alleles": len(matched_batch_ids),
        "written_records": written_records,
    }


def _copy_source_record_field(sample: dict[str, Any], source: dict[str, Any], field: str) -> None:
    value = source.get(field)
    if value is not None:
        sample[f"source_record_{field}"] = value


def _row_value(row: sqlite3.Row, row_keys: set[str], key: str) -> Any:
    if key not in row_keys:
        return None
    return row[key]


def _source_format_from_info(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    source_format = parsed.get("source_format")
    return str(source_format) if source_format else None


def _json_list_or_none(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    return [str(item) for item in parsed]


def _inferred_clinvar_allele(row: sqlite3.Row, row_keys: set[str]) -> dict[str, Any] | None:
    ref = _row_value(row, row_keys, "inferred_clinvar_ref")
    alt = _row_value(row, row_keys, "inferred_clinvar_alt")
    if ref is None or alt is None:
        return None
    return {
        "chrom": row["chrom"],
        "pos": int(row["pos"]),
        "ref": ref,
        "alt": alt,
    }


def _evidence_scope_for_match_basis(match_basis: str) -> str:
    if match_basis == MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE:
        return "consumer_array_inferred_allele"
    if match_basis == MATCH_BASIS_UNKNOWN:
        return "unknown_match_basis"
    if match_basis.startswith("liftover_"):
        return "liftover_sample_allele"
    if match_basis in {MATCH_BASIS_MULTIALLELIC_ALT, MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT}:
        return "selected_alternate_allele"
    return "sample_allele"
