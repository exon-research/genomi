from __future__ import annotations

import csv
import gzip
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .constants import SUPPORTED_REGION_ASSEMBLIES


def _normalize_cell_marker_source(source: str | None) -> str:
    value = _normalize_source(source)
    return value or "hpa"


def _normalize_source(source: str | None) -> str:
    return _clean_text(source).lower().replace("-", "_")


def _pathway_source_label(source: Any) -> str:
    return {
        "reactome": "Reactome ContentService",
        "kegg": "KEGG REST",
        "msigdb_hallmark": "MSigDB Hallmark GMT",
    }.get(_normalize_source(str(source or "")), _clean_text(source) or "pathway membership source")


def _cell_marker_source_label(source: Any) -> str:
    return {
        "hpa": "Human Protein Atlas",
        "cellmarker": "CellMarker",
        "panglaodb": "PanglaoDB",
        "encode": "ENCODE cell-type annotations",
    }.get(_normalize_source(str(source or "")), _clean_text(source) or "cell-type marker source")


def _is_reactome_id(value: str) -> bool:
    return bool(re.fullmatch(r"R-HSA-\d+(?:\.\d+)?", _clean_text(value)))


def _normalize_kegg_pathway_id(value: Any) -> str:
    text = _clean_text(value)
    if text.startswith("path:"):
        text = text.split(":", 1)[1]
    return text if re.fullmatch(r"hsa\d{5}", text) else ""


def _parse_kegg_pathway_find(text: str) -> list[dict[str, str]]:
    candidates = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        raw_id, raw_name = line.split("\t", 1)
        pathway_id = _normalize_kegg_pathway_id(raw_id)
        if not pathway_id:
            continue
        candidates.append({"id": pathway_id, "name": _clean_text(raw_name), "source": "kegg", "version": "KEGG REST current"})
    return candidates


def _parse_kegg_links(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        source, target = line.split("\t", 1)
        pairs.append((_clean_text(source), _clean_text(target)))
    return pairs


def _parse_kegg_flat_entry(text: str) -> dict[str, list[str]]:
    entry: dict[str, list[str]] = {}
    current_key = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        key = line[:12].strip()
        value = line[12:].strip()
        if key:
            current_key = key
            entry.setdefault(current_key, []).append(value.rstrip(";"))
        elif current_key:
            entry.setdefault(current_key, []).append(value.rstrip(";"))
    return entry


def _kegg_gene_symbol(entry: dict[str, list[str]], gene_ref: str) -> str:
    for value in entry.get("SYMBOL") or []:
        first = _clean_text(value.split(",", 1)[0]).upper()
        if first:
            return first
    return _clean_text(gene_ref.split(":", 1)[-1]).upper()


def _parse_gmt(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.rstrip("\n").split("\t")]
        if len(parts) >= 3:
            rows.append({"name": parts[0], "description": parts[1], "genes": parts[2:]})
    return rows


def _read_marker_table(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def _table_cell_type_value(row: dict[str, Any], source_key: str) -> str:
    if source_key == "cellmarker":
        keys = ["cell_name", "cell name", "cellName", "Cell name", "cell_type", "cell type", "cell_type_name", "Cell type"]
    else:
        keys = ["cell_type", "cell type", "cell_type_name", "cell name", "cellName", "Cell type"]
    return _first_present(row, keys)


def _table_gene_value(row: dict[str, Any], source_key: str) -> str:
    if source_key == "cellmarker":
        keys = ["gene_symbol", "Symbol", "official gene symbol", "Gene", "gene", "marker_gene", "marker"]
    elif source_key == "panglaodb":
        keys = ["official gene symbol", "gene_symbol", "gene", "Symbol", "Gene", "marker_gene", "marker"]
    else:
        keys = ["gene_symbol", "gene", "marker", "marker_gene", "official gene symbol", "Gene", "Symbol"]
    return _first_present(row, keys)


def _row_matches_species(row: dict[str, Any], species: Any) -> bool:
    row_species = _first_present(row, ["species", "organism", "taxon"])
    if not row_species:
        return True
    requested = _normalise_label(species)
    observed = _normalise_label(row_species)
    if not requested or requested in {"homo sapiens", "human", "hs"}:
        return "hs" in observed.split() or "human" in observed or "homo sapiens" in observed
    return requested in observed


def _ccre_class(parts: list[str]) -> str:
    candidates = [parts[index] for index in (9, 8, 6, 5, 4) if len(parts) > index]
    for value in candidates:
        clean = _clean_text(value)
        if clean and clean not in {".", "0"} and not clean.isdigit():
            return clean
    return "candidate_cis_regulatory_element"


def _region_query(*, chrom: str | None, start: int | str | None, end: int | str | None, region: str | None) -> dict[str, Any]:
    if region:
        match = re.fullmatch(r"\s*([^:]+):([0-9,]+)(?:-([0-9,]+))?\s*", region)
        if not match:
            return {"error": "region must look like chrom:start-end."}
        parsed_start = int(match.group(2).replace(",", ""))
        parsed_end = int((match.group(3) or match.group(2)).replace(",", ""))
        return _validated_region(match.group(1), parsed_start, parsed_end)
    parsed_start = _safe_int(start)
    parsed_end = _safe_int(end)
    if not chrom or parsed_start is None or parsed_end is None:
        return {"error": "chrom, start, and end are required unless region is supplied."}
    return _validated_region(chrom, parsed_start, parsed_end)


def _validated_region(chrom: str, start: int, end: int) -> dict[str, Any]:
    if start < 1 or end < 1 or end < start:
        return {"error": "start and end must be 1-based coordinates with end >= start."}
    return {"chrom": _clean_chrom(chrom), "start": start, "end": end}


def _normalize_assembly(value: str | None) -> str:
    cleaned = _clean_text(value).upper().replace("-", "")
    return SUPPORTED_REGION_ASSEMBLIES.get(cleaned, "")


def _dominant_feature_class(features: list[dict[str, Any]]) -> str:
    if not features:
        return "intergenic"
    best = max(features, key=lambda item: (int(item.get("overlap_bp") or 0), _feature_priority(item.get("feature_type"))))
    return _clean_text(best.get("feature_type")) or "annotated_feature"


def _feature_order_key(feature: dict[str, Any]) -> tuple[Any, ...]:
    return (-int(feature.get("overlap_bp") or 0), _feature_priority(feature.get("feature_type")), _clean_text(feature.get("source")), _clean_text(feature.get("feature_id")))


def _feature_priority(value: Any) -> int:
    key = _clean_text(value).lower()
    if key == "gene":
        return 0
    if key == "transcript":
        return 1
    if key == "exon":
        return 2
    if "promoter" in key or "enhancer" in key or "ccre" in key:
        return 3
    return 10


def _nearest_tss(tss_records: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_distance: int | None = None
    for record in tss_records:
        tss = _safe_int(record.get("tss"))
        if tss is None:
            continue
        distance = 0 if start <= tss <= end else min(abs(start - tss), abs(end - tss))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = {**record, "distance_bp": distance}
    return best


def _parse_gtf_attributes(attrs: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in attrs.split(";"):
        item = item.strip()
        if not item:
            continue
        if " " in item:
            key, value = item.split(" ", 1)
            parsed[key] = value.strip().strip('"')
        elif "=" in item:
            key, value = item.split("=", 1)
            parsed[key] = value.strip().strip('"')
    return parsed


def _same_chrom(left: str, right: str) -> bool:
    return _clean_chrom(left).lower() == _clean_chrom(right).lower()


def _clean_chrom(value: Any) -> str:
    text = _clean_text(value)
    return text[3:] if text.lower().startswith("chr") else text


def _overlap_bp(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b) + 1)


def _read_marker_table_text(path: Path) -> str:
    with _open_text(path) as handle:
        return handle.read()


def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _first_present(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        if key in row and _clean_text(row.get(key)):
            return _clean_text(row.get(key))
        lowered = key.lower()
        for existing, value in row.items():
            if existing.lower() == lowered and _clean_text(value):
                return _clean_text(value)
    return ""


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _looks_like_pathway_identifier(value: str) -> bool:
    text = _clean_text(value)
    return bool(
        re.fullmatch(r"R-[A-Z]{3}-\d+", text)
        or re.fullmatch(r"hsa\d{5}", text, flags=re.I)
        or text.upper().startswith("HALLMARK_")
    )


def _normalise_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(value).casefold()).strip()


def _url(base: str, path: str, params: dict[str, str]) -> str:
    base = base.rstrip("/")
    url = f"{base}{path}"
    if params:
        return f"{url}?{urllib.parse.urlencode(params)}"
    return url


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as response:
        import json

        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()
