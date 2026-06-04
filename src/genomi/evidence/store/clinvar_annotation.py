from __future__ import annotations
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexReader,
)
from ...runtime.external import file_metadata, matching_manifest, utc_now
from ...runtime.handoff import evidence_context
from ...runtime.sqlite_support import (
    LONG_WRITE_BUSY_TIMEOUT_SECONDS,
    connect_sqlite,
)

from .constants import (
    CLINVAR_ANNOTATION_INDEX_RULE_SET_VERSION,
    CLINVAR_RSID_ANNOTATION_RULE_SET_VERSION,
    STRICT_PATHOGENIC_CLINSIG,
)
from .helpers import (
    _gene_symbols,
    _has_strict_pathogenic_component,
    _iter_jsonl,
    _ordered_unique,
)
from .connection import (
    _clinvar_cache_identity,
    _ensure_schema,
    connect_evidence,
)
from .candidate_scoring import (
    _candidate_evidence_groups,
    _ordered_candidate_evidence_group_counts,
)
from .clinvar_match_provenance import (
    MATCH_BASIS_EXACT_ALLELE,
    match_basis_from_record,
    match_kind_from_record,
)



def summarize_clinvar_matches(
    matches_path: str | Path,
    output_path: str | Path | None = None,
    *,
    example_limit: int = 25,
    force: bool = False,
) -> dict[str, Any]:
    matches_path = Path(matches_path)
    if not matches_path.exists():
        raise FileNotFoundError(matches_path)

    output_path = Path(output_path) if output_path is not None else Path(f"{matches_path}.summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"{output_path}.genomi-manifest.json")
    cache_expected = {
        "step": "summarize_clinvar_matches",
        "input": file_metadata(matches_path),
        "output": str(output_path),
        "example_limit": example_limit,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            return {
                "status": "cached",
                "output": str(output_path),
                "manifest_path": str(manifest_path),
                "total_clinvar_match_records": cached["summary"]["total_clinvar_match_records"],
                "strict_pathogenic_or_likely_pathogenic_count": cached["summary"][
                    "strict_pathogenic_or_likely_pathogenic_count"
                ],
                "top_clinical_significance": cached["summary"]["clinical_significance_counts"][:12],
                "top_review_status": cached["summary"]["review_status_counts"][:8],
                "evidence_context": evidence_context(
                    "static",
                    reason="The static match summary can feed deterministic candidate inventory.",
                    commands=["genomi call clinvar.scan_candidates"],
                ),
            }

    clinical_significance: Counter[str] = Counter()
    review_status: Counter[str] = Counter()
    genes: Counter[str] = Counter()
    strict_pathogenic_examples: list[dict[str, Any]] = []
    total = 0

    with matches_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            item = json.loads(line)
            clinvar = item["clinvar"]
            significance = clinvar.get("clinical_significance") or "missing"
            clinical_significance[significance] += 1
            review_status[clinvar.get("review_status") or "missing"] += 1

            gene_info = clinvar.get("gene_info") or "missing"
            for gene in gene_info.split("|"):
                genes[gene.split(":", 1)[0]] += 1

            if _has_strict_pathogenic_component(Counter({significance: 1})) and len(strict_pathogenic_examples) < example_limit:
                strict_pathogenic_examples.append(item)

    summary = {
        "input": str(matches_path),
        "total_clinvar_match_records": total,
        "clinical_significance_counts": clinical_significance.most_common(),
        "review_status_counts": review_status.most_common(),
        "top_gene_counts": genes.most_common(25),
        "strict_pathogenic_clinsig_values": sorted(STRICT_PATHOGENIC_CLINSIG),
        "strict_pathogenic_component_values": sorted(STRICT_PATHOGENIC_CLINSIG),
        "strict_pathogenic_or_likely_pathogenic_count": sum(
            count
            for significance, count in clinical_significance.items()
            if _has_strict_pathogenic_component(Counter({significance: count}))
        ),
        "strict_pathogenic_or_likely_pathogenic_examples": strict_pathogenic_examples,
    }
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "step": "summarize_clinvar_matches",
        "created_at_utc": utc_now(),
        "input": file_metadata(matches_path),
        "output": str(output_path),
        "output_metadata": file_metadata(output_path),
        "example_limit": example_limit,
        "summary": {
            "total_clinvar_match_records": total,
            "strict_pathogenic_or_likely_pathogenic_count": summary[
                "strict_pathogenic_or_likely_pathogenic_count"
            ],
            "clinical_significance_counts": clinical_significance.most_common(),
            "review_status_counts": review_status.most_common(),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "status": "completed",
        "output": str(output_path),
        "manifest_path": str(manifest_path),
        "total_clinvar_match_records": total,
        "strict_pathogenic_or_likely_pathogenic_count": summary[
            "strict_pathogenic_or_likely_pathogenic_count"
        ],
        "top_clinical_significance": clinical_significance.most_common(12),
        "top_review_status": review_status.most_common(8),
        "evidence_context": evidence_context(
            "static",
            reason="The static match summary can feed deterministic candidate inventory.",
            commands=["genomi call clinvar.scan_candidates"],
        ),
    }


def build_clinvar_annotation_index(
    matches_path: str | Path,
    output_path: str | Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Build an unfiltered exact-match annotation index for stage-1 consumers.

    Candidate inventory is intentionally lens-filtered for report/research workflows.
    This index keeps every exact ClinVar match so later stages can recover
    objective gene and ClinVar fields without re-reading large JSONL match files.
    """

    matches_path = Path(matches_path)
    if not matches_path.exists():
        raise FileNotFoundError(matches_path)

    output_path = Path(output_path) if output_path is not None else Path(f"{matches_path}.annotations.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"{output_path}.genomi-manifest.json")
    cache_expected = {
        "step": "build_clinvar_annotation_index",
        "input": file_metadata(matches_path),
        "output": str(output_path),
        "rule_set_version": CLINVAR_ANNOTATION_INDEX_RULE_SET_VERSION,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            payload["status"] = "cached"
            payload["manifest_path"] = str(manifest_path)
            return payload

    grouped: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    total_match_records = 0
    for item in _iter_jsonl(matches_path):
        total_match_records += 1
        sample = item.get("sample_variant") or {}
        candidate_allele = _candidate_allele_from_match(item, sample)
        key = (
            str(candidate_allele.get("chrom")),
            int(candidate_allele.get("pos") or 0),
            str(candidate_allele.get("ref")),
            str(candidate_allele.get("alt")),
        )
        group = grouped.setdefault(key, {"candidate_allele": candidate_allele, "sample_variant": sample, "records": []})
        group["records"].append(item)

    annotations = [_build_clinvar_annotation(group) for group in grouped.values()]
    annotations.sort(key=_clinvar_annotation_sort_key)
    clinical_significance_counts: Counter[str] = Counter()
    review_status_counts: Counter[str] = Counter()
    gene_counts: Counter[str] = Counter()
    evidence_group_counts: Counter[str] = Counter()
    match_basis_counts: Counter[str] = Counter()
    match_kind_counts: Counter[str] = Counter()
    exact_match_variants = 0
    for annotation in annotations:
        clinical_significance_counts.update(dict(annotation["clinvar"]["clinical_significance_counts"]))
        review_status_counts.update(dict(annotation["clinvar"]["review_status_counts"]))
        gene_counts.update(annotation["genes"])
        evidence_group_counts.update(annotation["evidence_groups"])
        provenance = annotation["match_provenance"]
        match_basis_counts.update(dict(provenance["match_basis_counts"]))
        match_kind_counts.update(dict(provenance["match_kind_counts"]))
        if provenance["primary_match_basis"] == MATCH_BASIS_EXACT_ALLELE:
            exact_match_variants += 1

    payload = {
        "status": "completed",
        "input": str(matches_path),
        "output": str(output_path),
        "rule_set_version": CLINVAR_ANNOTATION_INDEX_RULE_SET_VERSION,
        "action": {
            "name": "build-clinvar-annotation-index",
            "purpose": (
                "Materialize every provenance-labeled ClinVar allele match from stage 1 so downstream "
                "research can recover objective genes, conditions, review "
                "status, and clinical-significance source fields without applying a report lens."
            ),
            "scope": [
                "materializes objective ClinVar annotation fields",
                "preserves all matched rows for agent-selected intent filtering",
                "feeds report-specific interpretation written by the agent",
            ],
        },
        "summary": {
            "total_match_records": total_match_records,
            "matched_variants": len(annotations),
            "exact_match_variants": exact_match_variants,
            "match_basis_counts": match_basis_counts.most_common(),
            "match_kind_counts": match_kind_counts.most_common(),
            "gene_counts": gene_counts.most_common(25),
            "clinical_significance_counts": clinical_significance_counts.most_common(),
            "review_status_counts": review_status_counts.most_common(),
            "evidence_group_counts": _ordered_candidate_evidence_group_counts(evidence_group_counts),
        },
        "annotations": annotations,
        "evidence_context": evidence_context(
            "research",
            reason="ClinVar annotations are static source fields with explicit match provenance; interpretation still belongs in intent research.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"gene\":\"<gene>\"}'",
            ],
        ),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        **cache_expected,
        "created_at_utc": utc_now(),
        "output_metadata": file_metadata(output_path),
        "summary": payload["summary"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["manifest_path"] = str(manifest_path)
    return payload


def _build_clinvar_annotation(group: dict[str, Any]) -> dict[str, Any]:
    sample = dict(group["sample_variant"])
    candidate_allele = dict(group.get("candidate_allele") or _allele_identity(sample))
    records = group["records"]
    clinvar_records = [item.get("clinvar") or {} for item in records]
    clinical_significance: Counter[str] = Counter(
        record.get("clinical_significance") or "missing" for record in clinvar_records
    )
    review_status: Counter[str] = Counter(record.get("review_status") or "missing" for record in clinvar_records)
    genes = sorted(
        {
            gene
            for record in clinvar_records
            for gene in _gene_symbols(record.get("gene_info") or "")
        }
    )
    conditions = _ordered_unique(record.get("conditions") for record in clinvar_records if record.get("conditions"))
    clinvar_ids = _ordered_unique(record.get("clinvar_id") for record in clinvar_records if record.get("clinvar_id"))
    match_basis = Counter(match_basis_from_record(item) for item in records)
    match_kind = Counter(match_kind_from_record(item) for item in records)
    return {
        "candidate_allele": candidate_allele,
        "variant": {
            "chrom": sample.get("chrom"),
            "pos": sample.get("pos"),
            "ref": sample.get("ref"),
            "alt": sample.get("alt"),
            "id": sample.get("id"),
            "filter": sample.get("filter"),
            "genotype": sample.get("genotype"),
            "depth": sample.get("depth"),
            "genotype_quality": sample.get("genotype_quality"),
            "record_kind": sample.get("record_kind"),
            "observed_alleles": sample.get("observed_alleles"),
            "source_record_ref": sample.get("source_record_ref"),
            "source_record_alt": sample.get("source_record_alt"),
            "source_record_format": sample.get("source_record_format") or sample.get("format"),
            "source_record_record_kind": sample.get("source_record_record_kind"),
            "source_record_observed_alleles": sample.get("source_record_observed_alleles"),
        },
        "genes": genes,
        "evidence_groups": _candidate_evidence_groups(clinical_significance),
        "match_provenance": {
            "primary_match_basis": _primary_counter_value(match_basis),
            "primary_match_kind": _primary_counter_value(match_kind),
            "match_basis_counts": match_basis.most_common(),
            "match_kind_counts": match_kind.most_common(),
        },
        "clinvar": {
            "match_records": len(records),
            "clinical_significance_counts": clinical_significance.most_common(),
            "review_status_counts": review_status.most_common(),
            "clinvar_ids": clinvar_ids[:20],
            "conditions": conditions[:20],
        },
    }


def _clinvar_annotation_sort_key(annotation: dict[str, Any]) -> tuple[str, int, str, str]:
    variant = annotation.get("candidate_allele") or annotation["variant"]
    return (
        str(variant.get("chrom")),
        int(variant.get("pos") or 0),
        str(variant.get("ref")),
        str(variant.get("alt")),
    )


def _candidate_allele_from_match(item: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    provenance = item.get("match_provenance")
    inferred = provenance.get("inferred_clinvar_allele") if isinstance(provenance, dict) else None
    if isinstance(inferred, dict):
        return _allele_identity(inferred)
    clinvar = item.get("clinvar")
    if isinstance(clinvar, dict):
        return {
            "chrom": clinvar.get("chrom") or sample.get("chrom"),
            "pos": clinvar.get("pos") or sample.get("pos"),
            "ref": clinvar.get("ref") or sample.get("ref"),
            "alt": clinvar.get("alt") or sample.get("alt"),
        }
    return _allele_identity(sample)


def _allele_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "chrom": record.get("chrom"),
        "pos": record.get("pos"),
        "ref": record.get("ref"),
        "alt": record.get("alt"),
    }


def _primary_counter_value(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def build_clinvar_rsid_annotation_index(
    reader: ActiveGenomeIndexReader,
    evidence_db: str | Path,
    output_path: str | Path | None = None,
    *,
    genome_build: str = "GRCh38",
    force: bool = False,
    batch_size: int = 1000,
    max_evidence_per_rsid: int = 20,
) -> dict[str, Any]:
    """Build per-sample ClinVar annotations joined by VCF rsID.

    This complements exact allele matching. It is still a static VCF-only
    artifact: sample rsIDs come from the Active Genome Index, and gene/source fields come
    from the shared ClinVar source.
    """

    agi_path = reader.agi_path
    evidence_db = Path(evidence_db)
    if not agi_path.exists():
        raise FileNotFoundError(agi_path)
    if not evidence_db.exists():
        raise FileNotFoundError(evidence_db)

    output_path = Path(output_path) if output_path is not None else Path(f"{agi_path}.clinvar-rsid-annotations.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(f"{output_path}.genomi-manifest.json")
    with connect_evidence(evidence_db) as evidence_connection:
        _ensure_schema(evidence_connection)
        clinvar_identity = _clinvar_cache_identity(evidence_connection)
    cache_expected = {
        "step": "build_clinvar_rsid_annotation_index",
        "input_active_genome_index": file_metadata(agi_path),
        "evidence_db": str(evidence_db),
        "clinvar_evidence": clinvar_identity,
        "output": str(output_path),
        "genome_build": genome_build,
        "rule_set_version": CLINVAR_RSID_ANNOTATION_RULE_SET_VERSION,
        "batch_size": batch_size,
        "max_evidence_per_rsid": max_evidence_per_rsid,
    }
    if not force:
        cached = matching_manifest(manifest_path, cache_expected, required_paths=[output_path])
        if cached is not None:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            payload["status"] = "cached"
            payload["manifest_path"] = str(manifest_path)
            return payload

    annotations: list[dict[str, Any]] = []
    sample_variant_count = 0
    queried_rsids = 0
    matched_rsids = 0
    clinical_significance_counts: Counter[str] = Counter()
    gene_counts: Counter[str] = Counter()
    with connect_evidence(evidence_db) as evidence_connection:
        _ensure_schema(evidence_connection)
        for sample_by_rsid in reader.iter_pass_variant_rsid_batches(batch_size=batch_size):
            queried_rsids += len(sample_by_rsid)
            sample_variant_count += sum(len(records) for records in sample_by_rsid.values())
            clinvar_by_rsid = _query_clinvar_by_rsid(
                evidence_connection,
                sample_by_rsid.keys(),
                genome_build=genome_build,
                limit_per_rsid=max_evidence_per_rsid,
            )
            matched_rsids += len(clinvar_by_rsid)
            for rsid, clinvar_records in clinvar_by_rsid.items():
                annotation = _build_clinvar_rsid_annotation(rsid, sample_by_rsid[rsid], clinvar_records)
                annotations.append(annotation)
                clinical_significance_counts.update(dict(annotation["clinvar"]["clinical_significance_counts"]))
                gene_counts.update(annotation["genes"])

    annotations.sort(key=_clinvar_rsid_annotation_sort_key)
    payload = {
        "status": "completed",
        "input_active_genome_index": str(agi_path),
        "evidence_db": str(evidence_db),
        "output": str(output_path),
        "genome_build": genome_build,
        "rule_set_version": CLINVAR_RSID_ANNOTATION_RULE_SET_VERSION,
        "action": {
            "name": "build-clinvar-rsid-annotation-index",
            "purpose": (
                "Materialize ClinVar gene and source fields for sample variants whose VCF rows carry rsIDs, "
                "including cases where exact REF/ALT matching cannot recover a ClinVar allele."
            ),
            "scope": [
                "uses VCF rsID fields and ClinVar source fields",
                "materializes annotation context for report reconstruction and source review",
                "marks rsID-only evidence separately from exact allele equivalence",
            ],
        },
        "summary": {
            "sample_variant_records_with_rsid": sample_variant_count,
            "queried_rsids": queried_rsids,
            "matched_rsids": matched_rsids,
            "annotations": len(annotations),
            "gene_counts": gene_counts.most_common(25),
            "clinical_significance_counts": clinical_significance_counts.most_common(),
        },
        "annotations": annotations,
        "evidence_context": evidence_context(
            "research",
            reason="rsID-level ClinVar annotations are static source fields; interpretation still belongs in intent research.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call variant.gather_gene_context --params '{\"db\":\"<evidence.sqlite>\",\"gene\":\"<gene>\"}'",
            ],
        ),
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        **cache_expected,
        "created_at_utc": utc_now(),
        "output_metadata": file_metadata(output_path),
        "summary": payload["summary"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["manifest_path"] = str(manifest_path)
    return payload


def _query_clinvar_by_rsid(
    connection: sqlite3.Connection,
    rsids: Iterable[str],
    *,
    genome_build: str,
    limit_per_rsid: int,
) -> dict[str, list[dict[str, Any]]]:
    rsid_values = sorted({str(rsid) for rsid in rsids if str(rsid).startswith("rs")})
    if not rsid_values:
        return {}
    placeholders = ", ".join("?" for _rsid in rsid_values)
    rows = connection.execute(
        f"""
        select cr.rsid, cv.chrom, cv.pos, cv.ref, cv.alt, cv.genome_build, cv.clinvar_id, cv.allele_id,
               cv.clinical_significance, cv.review_status, cv.conditions, cv.gene_info,
               cv.hgvs, cv.source_path, cv.source_version, cv.imported_at
        from clinvar_variant_rsids as cr
        join clinvar_variants as cv
          on cv.rowid = cr.variant_rowid
         and cv.genome_build = cr.genome_build
        where cr.genome_build = ?
          and cr.rsid in ({placeholders})
        order by cr.rsid, cv.imported_at desc, cv.chrom, cv.pos
        """,
        (genome_build, *rsid_values),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = grouped.setdefault(str(row["rsid"]), [])
        if len(bucket) < limit_per_rsid:
            bucket.append({key: row[key] for key in row.keys() if key != "rsid"})  # noqa: SIM118 — sqlite3.Row iteration yields values, .keys() yields column names
    return grouped


def _build_clinvar_rsid_annotation(
    rsid: str,
    sample_variants: list[dict[str, Any]],
    clinvar_records: list[dict[str, Any]],
) -> dict[str, Any]:
    clinical_significance: Counter[str] = Counter(
        record.get("clinical_significance") or "missing" for record in clinvar_records
    )
    review_status: Counter[str] = Counter(record.get("review_status") or "missing" for record in clinvar_records)
    genes = sorted(
        {
            gene
            for record in clinvar_records
            for gene in _gene_symbols(record.get("gene_info") or "")
        }
    )
    conditions = _ordered_unique(record.get("conditions") for record in clinvar_records if record.get("conditions"))
    clinvar_ids = _ordered_unique(record.get("clinvar_id") for record in clinvar_records if record.get("clinvar_id"))
    first_sample = sample_variants[0]
    return {
        "variant": {
            "chrom": first_sample.get("chrom"),
            "pos": first_sample.get("pos"),
            "ref": first_sample.get("ref"),
            "alt": first_sample.get("alt"),
            "id": rsid,
            "filter": first_sample.get("filter"),
            "genotype": first_sample.get("genotype"),
            "depth": first_sample.get("depth"),
            "genotype_quality": first_sample.get("genotype_quality"),
        },
        "rsid": rsid,
        "genes": genes,
        "evidence_groups": _candidate_evidence_groups(clinical_significance),
        "match_level": "rsid",
        "clinvar": {
            "match_records": len(clinvar_records),
            "sample_variant_records": len(sample_variants),
            "clinical_significance_counts": clinical_significance.most_common(),
            "review_status_counts": review_status.most_common(),
            "clinvar_ids": clinvar_ids[:20],
            "conditions": conditions[:20],
        },
    }


def _clinvar_rsid_annotation_sort_key(annotation: dict[str, Any]) -> tuple[str, str, int]:
    variant = annotation["variant"]
    return (
        str(annotation.get("rsid")),
        str(variant.get("chrom")),
        int(variant.get("pos") or 0),
    )
