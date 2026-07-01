from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ._common import (
    JsonObject,
    PHARMCAT_DOCS,
    _artifact_fingerprint,
    _as_dicts,
    _as_list,
    _clean_base_filename,
    _clean_report_text,
    _file_sha256,
    _first_string,
    _int_or_original,
    _size,
    _without_none,
)
from .record_payloads import (
    _has_imported_pharmcat_evidence,
    _readiness,
    _record_payloads_from_calls,
    _record_payloads_from_match,
    _record_payloads_from_phenotype,
    _record_payloads_from_report,
)
from .matrix import build_medication_review_targets, build_sample_pgx_matrix


def import_pharmcat_artifacts(
    *,
    output_dir: str | Path | None = None,
    base_filename: str | None = None,
    report_json: str | Path | None = None,
    calls_only_tsv: str | Path | None = None,
    match_json: str | Path | None = None,
    phenotype_json: str | Path | None = None,
    missing_pgx_positions_vcf: str | Path | None = None,
) -> JsonObject:
    """Summarize existing PharmCAT artifacts without executing PharmCAT."""

    artifacts = _import_artifacts(
        output_dir=output_dir,
        base_filename=base_filename,
        report_json=report_json,
        calls_only_tsv=calls_only_tsv,
        match_json=match_json,
        phenotype_json=phenotype_json,
        missing_pgx_positions_vcf=missing_pgx_positions_vcf,
    )
    record_payloads = [
        *_record_payloads_from_calls(artifacts.get("calls_only") or {}, captured_by="genomi call pharmacogenomics.import_pharmcat_artifacts"),
        *_record_payloads_from_match(artifacts.get("named_allele_match_json") or {}, captured_by="genomi call pharmacogenomics.import_pharmcat_artifacts"),
        *_record_payloads_from_phenotype(artifacts.get("phenotype_json") or {}, captured_by="genomi call pharmacogenomics.import_pharmcat_artifacts"),
        *_record_payloads_from_report(artifacts.get("report_json") or {}, captured_by="genomi call pharmacogenomics.import_pharmcat_artifacts"),
    ]
    status = "completed" if _has_imported_pharmcat_evidence(artifacts) else "no_pharmcat_artifacts"
    sample_pgx_matrix = build_sample_pgx_matrix(artifacts)
    medication_review_targets = build_medication_review_targets(sample_pgx_matrix)
    return {
        "status": status,
        "summary": {
            "record_count": len(record_payloads),
            "artifact_count": int((artifacts.get("file_count") or 0) if isinstance(artifacts, dict) else 0),
        },
        "artifacts": _hide_private_paths(artifacts),
        "sample_pgx_matrix": sample_pgx_matrix,
        "medication_review_targets": medication_review_targets,
        "record_research_payloads": record_payloads,
        "interpretation_readiness": _readiness(0 if status == "completed" else 1, artifacts),
        "traceability": {
            "source_tool": "PharmCAT",
            "import_mode": "existing_artifacts",
            "definition_and_guideline_sources": PHARMCAT_DOCS,
        },
    }


def _summarize_outputs(
    output_dir: Path,
    base_filename: str,
    *,
    max_files: int = 200,
    max_calls: int = 200,
    hide_paths: bool = True,
) -> JsonObject:
    files = []
    if output_dir.exists():
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                files.append(_artifact_descriptor(path, base_filename))
            if len(files) >= max_files:
                break
    calls_tsv = [item for item in files if item["artifact_type"] == "calls_only_tsv"]
    report_json = [item for item in files if item["artifact_type"] == "report_json"]
    match_json = [item for item in files if item["artifact_type"] == "named_allele_match_json"]
    phenotype_json = [item for item in files if item["artifact_type"] == "phenotype_json"]
    missing_pgx = [item for item in files if item["artifact_type"] == "missing_pgx_positions_vcf"]
    payload = {
        "output_dir": str(output_dir.expanduser().resolve(strict=False)),
        "base_filename": base_filename,
        "file_count": len(files),
        "files": files,
        "calls_only": _parse_calls_only_tsv(Path(calls_tsv[0]["path"]), max_calls=max_calls) if calls_tsv else {"available": False, "rows": []},
        "named_allele_match_json": _summarize_match_json(Path(match_json[0]["path"])) if match_json else {"available": False},
        "phenotype_json": _summarize_phenotype_json(Path(phenotype_json[0]["path"])) if phenotype_json else {"available": False},
        "report_json": _summarize_json(Path(report_json[0]["path"])) if report_json else {"available": False},
        "missing_pgx_positions": _summarize_missing_pgx_vcf(Path(missing_pgx[0]["path"])) if missing_pgx else {"available": False},
    }
    return _hide_private_paths(payload) if hide_paths else payload


def _import_artifacts(
    *,
    output_dir: str | Path | None,
    base_filename: str | None,
    report_json: str | Path | None,
    calls_only_tsv: str | Path | None,
    match_json: str | Path | None,
    phenotype_json: str | Path | None,
    missing_pgx_positions_vcf: str | Path | None,
) -> JsonObject:
    base = _clean_base_filename(base_filename) or ""
    if output_dir:
        artifacts = _summarize_outputs(Path(output_dir).expanduser(), base or "*", hide_paths=False)
    else:
        artifacts = {
            "output_dir": None,
            "base_filename": base or None,
            "file_count": 0,
            "files": [],
            "calls_only": {"available": False, "rows": []},
            "named_allele_match_json": {"available": False},
            "phenotype_json": {"available": False},
            "report_json": {"available": False},
            "missing_pgx_positions": {"available": False},
        }
    explicit_files = []
    if calls_only_tsv:
        path = Path(calls_only_tsv).expanduser()
        explicit_files.append(_explicit_artifact_descriptor(path, "calls_only_tsv"))
        artifacts["calls_only"] = _parse_calls_only_tsv(path, max_calls=200) if path.exists() else {"available": False, "path": str(path.expanduser().resolve(strict=False)), "rows": []}
    if report_json:
        path = Path(report_json).expanduser()
        explicit_files.append(_explicit_artifact_descriptor(path, "report_json"))
        artifacts["report_json"] = _summarize_json(path) if path.exists() else {"available": False, "path": str(path.expanduser().resolve(strict=False))}
    if match_json:
        path = Path(match_json).expanduser()
        explicit_files.append(_explicit_artifact_descriptor(path, "named_allele_match_json"))
        artifacts["named_allele_match_json"] = _summarize_match_json(path) if path.exists() else {"available": False, "path": str(path.expanduser().resolve(strict=False))}
    if phenotype_json:
        path = Path(phenotype_json).expanduser()
        explicit_files.append(_explicit_artifact_descriptor(path, "phenotype_json"))
        artifacts["phenotype_json"] = _summarize_phenotype_json(path) if path.exists() else {"available": False, "path": str(path.expanduser().resolve(strict=False))}
    if missing_pgx_positions_vcf:
        path = Path(missing_pgx_positions_vcf).expanduser()
        explicit_files.append(_explicit_artifact_descriptor(path, "missing_pgx_positions_vcf"))
        artifacts["missing_pgx_positions"] = _summarize_missing_pgx_vcf(path) if path.exists() else {"available": False, "path": str(path.expanduser().resolve(strict=False))}
    if explicit_files:
        artifacts["files"] = _dedupe_file_descriptors([*explicit_files, *list(artifacts.get("files") or [])])
        artifacts["file_count"] = len(artifacts["files"])
    return artifacts


def _hide_private_paths(value: Any) -> Any:
    if isinstance(value, list):
        return [_hide_private_paths(item) for item in value]
    if not isinstance(value, dict):
        return value
    hidden: JsonObject = {}
    for key, item in value.items():
        if key == "path" and item not in (None, ""):
            hidden["path_hidden"] = True
            continue
        if key == "output_dir" and item not in (None, ""):
            hidden["output_dir_hidden"] = True
            continue
        hidden[key] = _hide_private_paths(item)
    return hidden


def _explicit_artifact_descriptor(path: Path, artifact_type: str) -> JsonObject:
    return {
        "path": str(path.expanduser().resolve(strict=False)),
        "name": path.name,
        "size_bytes": _size(path),
        "content_sha256": _file_sha256(path),
        "artifact_type": artifact_type,
        "explicit_input": True,
    }


def _dedupe_file_descriptors(files: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    result: list[JsonObject] = []
    for item in files:
        key = str(item.get("path") or item.get("name") or len(result))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _artifact_descriptor(path: Path, base_filename: str) -> JsonObject:
    name = path.name
    return {
        "path": str(path.expanduser().resolve(strict=False)),
        "name": name,
        "size_bytes": _size(path),
        "content_sha256": _file_sha256(path),
        "artifact_type": _artifact_type(name, base_filename),
    }


def _artifact_type(name: str, base_filename: str) -> str:
    lowered = name.lower()
    del base_filename
    if lowered.endswith(".report.tsv"):
        return "calls_only_tsv"
    if lowered.endswith(".report.json"):
        return "report_json"
    if lowered.endswith(".report.html"):
        return "report_html"
    if lowered.endswith(".match.json"):
        return "named_allele_match_json"
    if lowered.endswith(".phenotype.json"):
        return "phenotype_json"
    if "missing_pgx" in lowered and lowered.endswith(".vcf"):
        return "missing_pgx_positions_vcf"
    if ".preprocessed." in lowered and (lowered.endswith(".vcf") or lowered.endswith(".vcf.bgz") or lowered.endswith(".vcf.gz")):
        return "preprocessed_vcf"
    return "pharmcat_output"


def _parse_calls_only_tsv(path: Path, *, max_calls: int) -> JsonObject:
    rows = []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            lines = handle.readlines()
        # PharmCAT prefixes the calls-only TSV with a title line (e.g. "PharmCAT 3.2.0")
        # before the tab-delimited "Gene\t..." header. Skip leading lines that do not
        # contain the delimiter so DictReader uses the real column header.
        header_index = next((i for i, line in enumerate(lines) if "\t" in line), None)
        if header_index is not None:
            reader = csv.DictReader(lines[header_index:], delimiter="\t")
            for row in reader:
                rows.append({key: value for key, value in row.items() if key is not None and value not in {None, ""}})
                if len(rows) >= max_calls:
                    break
    except OSError as exc:
        return {"available": False, "path": str(path), "artifact": _artifact_fingerprint(path, "calls_only_tsv"), "error": str(exc), "rows": []}
    genes = sorted({str(row.get("Gene") or row.get("gene")) for row in rows if row.get("Gene") or row.get("gene")})
    return {
        "available": True,
        "path": str(path.expanduser().resolve(strict=False)),
        "artifact": _artifact_fingerprint(path, "calls_only_tsv"),
        "row_count": len(rows),
        "genes": genes,
        "rows": rows,
    }


def _summarize_missing_pgx_vcf(path: Path, *, max_records: int = 50) -> JsonObject:
    records: list[JsonObject] = []
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line or line.startswith("#"):
                    continue
                count += 1
                if len(records) >= max_records:
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 5:
                    continue
                records.append(
                    {
                        "chrom": fields[0],
                        "pos": _int_or_original(fields[1]),
                        "id": fields[2],
                        "ref": fields[3],
                        "alt": fields[4],
                    }
                )
    except OSError as exc:
        return {"available": False, "path": str(path), "artifact": _artifact_fingerprint(path, "missing_pgx_positions_vcf"), "error": str(exc)}
    return {
        "available": True,
        "path": str(path.expanduser().resolve(strict=False)),
        "artifact": _artifact_fingerprint(path, "missing_pgx_positions_vcf"),
        "record_count": count,
        "records": records,
        "truncated": count > len(records),
    }


def _summarize_json(path: Path, *, max_recommendations: int = 100) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "artifact": _artifact_fingerprint(path, "report_json"), "error": str(exc)}
    if isinstance(value, dict):
        recommendations = _extract_report_recommendations(value, max_recommendations=max_recommendations)
        return {
            "available": True,
            "path": str(path.expanduser().resolve(strict=False)),
            "artifact": _artifact_fingerprint(path, "report_json"),
            "top_level_keys": sorted(str(key) for key in value),
            "metadata": _report_metadata(value),
            "recommendations": {
                "record_count": len(recommendations),
                "records": recommendations,
                "truncated": _report_recommendation_count(value) > len(recommendations),
            },
        }
    if isinstance(value, list):
        return {
            "available": True,
            "path": str(path.expanduser().resolve(strict=False)),
            "artifact": _artifact_fingerprint(path, "report_json"),
            "top_level_type": "array",
            "length": len(value),
        }
    return {
        "available": True,
        "path": str(path.expanduser().resolve(strict=False)),
        "artifact": _artifact_fingerprint(path, "report_json"),
        "top_level_type": type(value).__name__,
    }


def _summarize_match_json(path: Path, *, max_results: int = 100) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "artifact": _artifact_fingerprint(path, "named_allele_match_json"), "error": str(exc)}
    if not isinstance(value, dict):
        return {
            "available": True,
            "path": str(path.expanduser().resolve(strict=False)),
            "artifact": _artifact_fingerprint(path, "named_allele_match_json"),
            "top_level_type": type(value).__name__,
        }
    results = _as_dicts(value.get("results"))
    records = []
    for result in results[:max_results]:
        records.append(
            {
                "gene": result.get("gene"),
                "source": result.get("source"),
                "version": result.get("version"),
                "chromosome": result.get("chromosome"),
                "phased": result.get("phased"),
                "diplotypes": [
                    _without_none({"name": diplotype.get("name"), "score": diplotype.get("score")})
                    for diplotype in _as_dicts(result.get("diplotypes"))[:8]
                ],
                "variant_count": len(_as_list(result.get("variants"))),
                "variant_of_interest_count": len(_as_list(result.get("variantsOfInterest"))),
                "warning_count": len(_as_list(result.get("warnings"))),
                "uncallable_haplotype_count": len(_as_list(result.get("uncallableHaplotypes"))),
            }
        )
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    return {
        "available": True,
        "path": str(path.expanduser().resolve(strict=False)),
        "artifact": _artifact_fingerprint(path, "named_allele_match_json"),
        "metadata": _matcher_metadata(metadata),
        "result_count": len(results),
        "genes": sorted(str(record.get("gene")) for record in records if record.get("gene")),
        "records": records,
        "truncated": len(results) > len(records),
    }


def _summarize_phenotype_json(path: Path, *, max_results: int = 100) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "artifact": _artifact_fingerprint(path, "phenotype_json"), "error": str(exc)}
    if not isinstance(value, dict):
        return {
            "available": True,
            "path": str(path.expanduser().resolve(strict=False)),
            "artifact": _artifact_fingerprint(path, "phenotype_json"),
            "top_level_type": type(value).__name__,
        }
    gene_reports = value.get("geneReports") if isinstance(value.get("geneReports"), dict) else {}
    records = []
    for gene, report in sorted(gene_reports.items())[:max_results]:
        if not isinstance(report, dict):
            continue
        records.append(
            {
                "gene": report.get("geneSymbol") or gene,
                "call_source": report.get("callSource"),
                "phased": report.get("phased"),
                "effectively_phased": report.get("effectivelyPhased"),
                "source_diplotypes": _phenotype_diplotype_summaries(report.get("sourceDiplotypes")),
                "recommendation_diplotypes": _phenotype_diplotype_summaries(report.get("recommendationDiplotypes")),
                "message_count": len(_as_list(report.get("messages"))),
                "uncalled_haplotype_count": len(_as_list(report.get("uncalledHaplotypes"))),
                "related_drug_count": len(_as_list(report.get("relatedDrugs"))),
            }
        )
    metadata = value.get("matcherMetadata") if isinstance(value.get("matcherMetadata"), dict) else {}
    return {
        "available": True,
        "path": str(path.expanduser().resolve(strict=False)),
        "artifact": _artifact_fingerprint(path, "phenotype_json"),
        "metadata": _matcher_metadata(metadata),
        "gene_report_count": len(gene_reports),
        "unannotated_gene_call_count": len(_as_list(value.get("unannotatedGeneCalls"))),
        "genes": sorted(str(record.get("gene")) for record in records if record.get("gene")),
        "records": records,
        "truncated": len(gene_reports) > len(records),
    }


def _matcher_metadata(value: JsonObject) -> JsonObject:
    return {
        "named_allele_matcher_version": value.get("namedAlleleMatcherVersion"),
        "genome_build": value.get("genomeBuild"),
        "sample_id": value.get("sampleId"),
        "timestamp": value.get("timestamp"),
        "top_candidates_only": value.get("topCandidatesOnly"),
        "find_combinations": value.get("findCombinations"),
        "call_cyp2d": value.get("callCyp2d"),
    }


def _phenotype_diplotype_summaries(value: object) -> list[JsonObject]:
    summaries = []
    for diplotype in _as_dicts(value)[:8]:
        summaries.append(
            _without_none(
                {
                    "label": diplotype.get("label") or _diplotype_label(diplotype),
                    "phenotypes": [str(item) for item in _as_list(diplotype.get("phenotypes")) if item],
                    "activity_score": diplotype.get("activityScore"),
                    "match_score": diplotype.get("matchScore"),
                    "outside_phenotype": diplotype.get("outsidePhenotype"),
                    "outside_activity_score": diplotype.get("outsideActivityScore"),
                    "inferred": diplotype.get("inferred"),
                }
            )
        )
    return summaries


def _diplotype_label(diplotype: JsonObject) -> str | None:
    allele1 = diplotype.get("allele1") if isinstance(diplotype.get("allele1"), dict) else {}
    allele2 = diplotype.get("allele2") if isinstance(diplotype.get("allele2"), dict) else {}
    name1 = allele1.get("name")
    name2 = allele2.get("name")
    if name1 and name2:
        return f"{name1}/{name2}"
    return None


def _report_metadata(value: JsonObject) -> JsonObject:
    matcher = value.get("matcherMetadata") if isinstance(value.get("matcherMetadata"), dict) else {}
    return {
        "title": value.get("title"),
        "timestamp": value.get("timestamp"),
        "pharmcat_version": value.get("pharmcatVersion"),
        "data_version": value.get("dataVersion"),
        "genome_build": matcher.get("genomeBuild"),
        "sample_id": matcher.get("sampleId"),
    }


def _extract_report_recommendations(value: JsonObject, *, max_recommendations: int) -> list[JsonObject]:
    records: list[JsonObject] = []
    drugs = value.get("drugs")
    if not isinstance(drugs, dict):
        return records
    for source_group, drug_map in drugs.items():
        if not isinstance(drug_map, dict):
            continue
        for drug_key, drug_record in drug_map.items():
            if not isinstance(drug_record, dict):
                continue
            for guideline in _as_dicts(drug_record.get("guidelines")):
                for annotation in _as_dicts(guideline.get("annotations")):
                    recommendation = _clean_report_text(annotation.get("drugRecommendation"))
                    implications = [_clean_report_text(item) for item in _as_list(annotation.get("implications"))]
                    implications = [item for item in implications if item]
                    if not recommendation and not implications:
                        continue
                    records.append(
                        {
                            "source_group": str(source_group),
                            "drug": drug_record.get("name") or drug_key,
                            "drug_id": drug_record.get("id"),
                            "guideline_id": guideline.get("id"),
                            "guideline_name": guideline.get("name"),
                            "guideline_source": guideline.get("source") or drug_record.get("source"),
                            "source_url": guideline.get("url") or _first_string(drug_record.get("urls")),
                            "classification": annotation.get("classification"),
                            "population": annotation.get("population"),
                            "recommendation": recommendation,
                            "implications": implications,
                            "genes": _genes_from_genotypes(annotation.get("genotypes")),
                            "phenotypes": _phenotypes_from_genotypes(annotation.get("genotypes")),
                            "diplotypes": _diplotypes_from_genotypes(annotation.get("genotypes")),
                            "citations": _compact_citations(drug_record.get("citations")),
                        }
                    )
                    if len(records) >= max_recommendations:
                        return records
    return records


def _report_recommendation_count(value: JsonObject) -> int:
    drugs = value.get("drugs")
    if not isinstance(drugs, dict):
        return 0
    count = 0
    for drug_map in drugs.values():
        if not isinstance(drug_map, dict):
            continue
        for drug_record in drug_map.values():
            if not isinstance(drug_record, dict):
                continue
            for guideline in _as_dicts(drug_record.get("guidelines")):
                for annotation in _as_dicts(guideline.get("annotations")):
                    if annotation.get("drugRecommendation") or annotation.get("implications"):
                        count += 1
    return count


def _genes_from_genotypes(value: object) -> list[str]:
    genes = []
    for diplotype in _diplotypes(value):
        gene = diplotype.get("gene")
        if gene:
            genes.append(str(gene))
    return sorted(set(genes))


def _phenotypes_from_genotypes(value: object) -> list[str]:
    phenotypes = []
    for diplotype in _diplotypes(value):
        phenotypes.extend(str(item) for item in _as_list(diplotype.get("phenotypes")) if item)
    return sorted(set(phenotypes))


def _diplotypes_from_genotypes(value: object) -> list[str]:
    result = []
    for diplotype in _diplotypes(value):
        gene = str(diplotype.get("gene") or "")
        allele1 = diplotype.get("allele1") if isinstance(diplotype.get("allele1"), dict) else {}
        allele2 = diplotype.get("allele2") if isinstance(diplotype.get("allele2"), dict) else {}
        name1 = allele1.get("name")
        name2 = allele2.get("name")
        if gene and name1 and name2:
            result.append(f"{gene} {name1}/{name2}")
    return sorted(set(result))


def _diplotypes(value: object) -> list[JsonObject]:
    diplotypes = []
    for genotype in _as_dicts(value):
        diplotypes.extend(_as_dicts(genotype.get("diplotypes")))
    return diplotypes


def _compact_citations(value: object) -> list[JsonObject]:
    citations = []
    for citation in _as_dicts(value):
        citations.append(
            {
                "pmid": citation.get("pmid"),
                "title": citation.get("title"),
                "year": citation.get("year"),
                "url": citation.get("_sameAs"),
            }
        )
    return citations[:10]
