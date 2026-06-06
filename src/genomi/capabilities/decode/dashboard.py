"""Render the Genomi Dashboard HTML artifact.

The renderer is intentionally plain Python: read the template, splice in the
inline logo data URL, the vendored React/ReactDOM runtime, the precompiled app
JS, and the JSON evidence blob, then write a single HTML file. The page renders
fully offline — no CDN and no in-browser Babel; the dashboard UI is authored in
``templates/dashboard.jsx`` and precompiled to ``templates/vendor/
dashboard.compiled.*.js`` by ``scripts/build_dashboard.py``. (The only external
reference left is an optional Google Fonts stylesheet, which falls back to
system fonts offline and carries no genome data.) Components read evidence from
``window.__GENOMI_DASHBOARD__`` and fall back to the "Not gathered yet"
placeholder when a panel is missing.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...active_genome_index.array_genotypes import called_genotype_tokens
from .panel_adapters import (
    PanelNormalizationError,
    is_native_empty_panel,
    native_panel_rows,
    normalize_pgx_panel,
    normalize_risk_panel,
)

JsonObject = dict[str, Any]

PANEL_KEYS: tuple[str, ...] = (
    "overview",
    "variants",
    "variants_all",
    "pgx",
    "risk",
    "ancestry",
    "nutrigenomics",
    "journal",
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_PATH = _TEMPLATE_DIR / "shell.html"
_VENDOR_DIR = _TEMPLATE_DIR / "vendor"
_LOGO_PATH = _PACKAGE_ROOT / "assets" / "genomi-logo-transparent.png"

# Vendored, inlined at render time so the dashboard opens with zero external
# script requests. React must load before ReactDOM, ReactDOM before the app.
_REACT_PATH = _VENDOR_DIR / "react.production.min.js"
_REACT_DOM_PATH = _VENDOR_DIR / "react-dom.production.min.js"
_APP_JS_CHUNK_RE = re.compile(r"dashboard\.compiled\.(?P<index>\d+)\.js$")

_EVIDENCE_ASSIGNMENT = "window.__GENOMI_DASHBOARD__"


class DashboardRenderError(Exception):
    """Renderer-level error. Translated to OperationError by the registry handler."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _read_logo_data_url() -> str:
    if not _LOGO_PATH.is_file():
        return ""
    encoded = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _read_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _pick(d: dict, *keys: str):
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def _as_dict(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _normalize_source_coverage_item(item: Any) -> JsonObject | None:
    """Normalize a single sourceCoverage entry to ``name``/``coverageState``/``percent``.

    ``sourceCoverage`` is a dashboard-owned shape; native capability results
    should be adapted before reaching this field.
    """
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if name in (None, "", []):
        return None
    coverage_state = _first_present(item.get("coverageState"), item.get("coverage_state"))
    percent = item.get("percent")
    out: JsonObject = {}
    if name is not None:
        out["name"] = name
    out["coverageState"] = coverage_state or "data_returned"
    if percent is not None:
        out["percent"] = percent
    return out or None


def _pass_rate(raw: Any) -> float | None:
    if not isinstance(raw, dict):
        return None
    pr = raw.get("pass_records")
    tr = raw.get("total_records")
    if isinstance(pr, (int, float)) and isinstance(tr, (int, float)) and tr > 0:
        return round(100 * pr / tr, 1)
    return None


def _normalize_overview(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict):
        return None
    if any(key in raw for key in _CANONICAL_OVERVIEW_KEYS):
        out = _normalize_dashboard_overview(raw)
    else:
        out = _normalize_active_genome_index_overview(raw) or {}
    if isinstance(out.get("sourceCoverage"), list):
        normalized_sources = [
            n for n in (_normalize_source_coverage_item(it) for it in out["sourceCoverage"])
            if n is not None
        ]
        out["sourceCoverage"] = normalized_sources or None
    return {k: v for k, v in out.items() if v is not None}


_CANONICAL_OVERVIEW_KEYS = {
    "sampleId",
    "genomeBuild",
    "variantCount",
    "variantCountLabel",
    "genotypeQuality",
    "meanDepth",
    "genomeSource",
    "parsedAt",
    "sourceCoverage",
}


def _normalize_dashboard_overview(raw: JsonObject) -> JsonObject:
    return {key: raw[key] for key in _CANONICAL_OVERVIEW_KEYS if raw.get(key) not in (None, "", [])}


def _normalize_active_genome_index_overview(raw: JsonObject) -> JsonObject | None:
    active = _as_dict(raw.get("active_genome_index"))
    metadata = _as_dict(active.get("metadata"))
    stats = _as_dict(active.get("stats"))
    if not stats:
        return None
    header = _as_dict(metadata.get("header"))
    samples = header.get("samples")
    sample_id = _first_present(
        raw.get("sample_slug"),
        metadata.get("sample_slug"),
        samples[0] if isinstance(samples, list) and samples else None,
    )
    genome_source = _first_present(
        raw.get("agi_source_format"),
        metadata.get("source_format"),
        header.get("dataSourceType"),
    )
    source_kind = _first_present(raw.get("agi_source_kind"), metadata.get("source_kind"))
    is_consumer_array = _is_consumer_array_overview(source_kind, genome_source)
    variant_count = (
        _first_present(
            stats.get("array_call_records"),
            stats.get("pass_records"),
            stats.get("rsid_records"),
            stats.get("total_records"),
        )
        if is_consumer_array
        else stats.get("variant_records")
    )
    return {
        "sampleId": sample_id,
        "genomeBuild": _first_present(raw.get("genome_build"), metadata.get("genome_build"), header.get("reference")),
        "variantCount": variant_count,
        "variantCountLabel": "Markers Indexed" if is_consumer_array else "Variants Indexed",
        "genotypeQuality": _first_present(stats.get("genotype_quality"), stats.get("mean_gq"), _pass_rate(stats)),
        "meanDepth": _first_present(stats.get("mean_depth"), stats.get("mean_dp")),
        "genomeSource": genome_source,
        "parsedAt": metadata.get("active_genome_index_completed_at"),
    }


def _is_consumer_array_overview(source_kind: Any, genome_source: Any) -> bool:
    source_kind = str(source_kind or "").lower()
    if source_kind == "consumer_genotype_array":
        return True
    source = str(genome_source or "").lower()
    return source in {"23andme", "ancestrydna", "myheritage", "ftdna", "livingdna"}


def _normalize_ancestry(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict):
        return None
    if any(key in raw for key in ("dominantAncestry", "neighbors")):
        return _normalize_dashboard_ancestry(raw)
    return _normalize_native_ancestry(raw)


_CANONICAL_ANCESTRY_KEYS = {
    "dominantAncestry",
    "neighbors",
    "pcaPoints",
    "markerOverlapQuality",
    "overlapFraction",
    "panelId",
    "method",
}


def _normalize_dashboard_ancestry(raw: JsonObject) -> JsonObject:
    return {key: raw[key] for key in _CANONICAL_ANCESTRY_KEYS if raw.get(key) not in (None, "", [])}


def _normalize_native_ancestry(raw: JsonObject) -> JsonObject | None:
    neighbors_src = (
        raw.get("neighbors")
        or raw.get("nearest_reference_groups")
        or raw.get("nearest_reference_samples")
        or []
    )
    sample_qc = _as_dict(raw.get("sample_qc"))
    reference_panel = _as_dict(raw.get("reference_panel"))
    neighbors = []
    if isinstance(neighbors_src, list):
        for item in neighbors_src:
            if not isinstance(item, dict):
                continue
            neighbors.append({
                "population": _pick(item, "population", "group", "label", "id", "sample"),
                "similarity": _pick(item, "similarity", "score", "distance", "centroid_distance", "overlap"),
            })
    out = {
        "dominantAncestry": neighbors[0]["population"] if neighbors else None,
        "neighbors": neighbors or None,
        "pcaPoints": raw.get("pca_projection"),
        "markerOverlapQuality": sample_qc.get("marker_overlap_quality"),
        "overlapFraction": sample_qc.get("overlap_fraction"),
        "panelId": reference_panel.get("panel_id"),
        "method": "ancestry.estimate_population_context",
    }
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def _normalize_journal(raw: Any) -> JsonObject | list | None:
    # Dashboard expects a list; tolerate {entries, count, note} wrapper.
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        entries = raw.get("entries")
        if isinstance(entries, list):
            return entries
    return None


def _passthrough(raw: Any) -> Any:
    return raw if raw not in (None, "", []) else None


def _derive_zygosity(genotype: str | None) -> str | None:
    if not genotype:
        return None
    parts = called_genotype_tokens(genotype)
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(), parts[1].strip()
    if a == b:
        return "ref" if a == "0" else "hom"
    return "het"


def _strip_chr(chrom: Any) -> str | None:
    if chrom is None:
        return None
    s = str(chrom)
    return s[3:] if s.startswith("chr") else s


def _condition_short(raw_condition: Any) -> str | None:
    if not raw_condition:
        return None
    if isinstance(raw_condition, list) and raw_condition:
        first = str(raw_condition[0])
    else:
        first = str(raw_condition)
    return first.split("|")[0].strip().replace("_", " ") or None


def _parse_gene_info(gene_info: Any) -> str | None:
    """Parse ClinVar gene_info strings like 'BRCA1:672|BRCA2:675' into 'BRCA1, BRCA2'."""
    if not gene_info:
        return None
    symbols = []
    for token in str(gene_info).split("|"):
        symbol = token.split(":")[0].strip()
        if symbol:
            symbols.append(symbol)
    return ", ".join(symbols) if symbols else None


def _normalize_dashboard_variants_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        key: raw[key]
        for key in _PANEL_SCHEMAS["variants"]["row_fields"]
        if raw.get(key) not in (None, "", [])
    } or None


def _normalize_native_variants_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None

    # Support two nested formats:
    # - scan_candidates: {"variant": {...}, "clinvar": {...}, "genes": [...]}
    # - matches JSONL:   {"sample_variant": {...}, "clinvar": {...}}
    var = raw.get("variant") or raw.get("sample_variant") or {}
    clinvar = raw.get("clinvar") or {}

    rsid = _pick(raw, "rsid", "id") or _pick(var, "id", "rsid")

    genes = raw.get("genes")
    gene = (
        _pick(raw, "gene")
        or (", ".join(str(g) for g in genes) if isinstance(genes, list) and genes else None)
        or _parse_gene_info(_pick(raw, "gene_info") or _pick(clinvar, "gene_info"))
    )

    chrom = _strip_chr(_pick(raw, "chrom") or _pick(var, "chrom"))
    pos = _pick(raw, "pos") or _pick(var, "pos")
    ref = _pick(raw, "ref") or _pick(var, "ref")
    alt = _pick(raw, "alt") or _pick(var, "alt")

    raw_gt = _pick(raw, "genotype") or _pick(var, "genotype")
    zygosity = _pick(raw, "zygosity") or _derive_zygosity(raw_gt)

    # clinvarSignificance comes from dashboard rows, matches JSONL rows, or
    # scan_candidates nested clinvar.clinical_significance_counts.
    clinvar_sig = (
        _pick(raw, "clinvarSignificance", "significance", "clinical_significance")
        or _pick(clinvar, "clinical_significance", "clinvarSignificance")
    )
    if not clinvar_sig:
        sig_counts = clinvar.get("clinical_significance_counts")
        if isinstance(sig_counts, list) and sig_counts:
            first = sig_counts[0]
            clinvar_sig = first[0] if isinstance(first, (list, tuple)) else str(first)

    # conditionShort comes from dashboard rows or the nested ClinVar record.
    condition_short = _pick(raw, "conditionShort", "condition")
    if condition_short:
        condition_short = str(condition_short).replace("_", " ")
    else:
        condition_short = _condition_short(
            clinvar.get("conditions") or clinvar.get("condition")
        )

    # evidenceQuality: as-is or derived from genotype_quality / depth.
    evidence_quality = _pick(raw, "evidenceQuality", "evidence_quality")
    if not evidence_quality:
        parts = []
        gq = _pick(var, "genotype_quality")
        dp = _pick(var, "depth")
        if gq is not None:
            parts.append(f"GQ:{gq}")
        if dp is not None:
            parts.append(f"DP:{dp}")
        if parts:
            evidence_quality = " ".join(parts)

    out: dict[str, Any] = {}
    if rsid is not None:
        out["rsid"] = rsid
    if gene is not None:
        out["gene"] = gene
    if chrom is not None:
        out["chrom"] = chrom
    if pos is not None:
        out["pos"] = pos
    if ref is not None:
        out["ref"] = ref
    if alt is not None:
        out["alt"] = alt
    if zygosity is not None:
        out["zygosity"] = zygosity
    if clinvar_sig is not None:
        out["clinvarSignificance"] = clinvar_sig
    if condition_short is not None:
        out["conditionShort"] = condition_short
    if evidence_quality is not None:
        out["evidenceQuality"] = evidence_quality
    return out or None


def _normalize_variants_panel(raw: Any, *, panel: str) -> list[dict[str, Any]] | None:
    if isinstance(raw, dict):
        rows = native_panel_rows(panel, raw)
        if rows is None:
            return None
        return _normalize_required_rows(rows, panel=panel, row_normalizer=_normalize_native_variants_row)
    return _normalize_required_rows(raw, panel=panel, row_normalizer=_normalize_dashboard_variants_row)


def _normalize_variants(raw: Any) -> list[dict[str, Any]] | None:
    return _normalize_variants_panel(raw, panel="variants")


def _normalize_variants_all(raw: Any) -> list[dict[str, Any]] | None:
    return _normalize_variants_panel(raw, panel="variants_all")


_NUTRI_DOMAIN_LABELS: dict[str, str] = {
    "folate_metabolism": "Folate Metabolism",
    "lactose_tolerance": "Lactose Tolerance",
    "iron_storage": "Iron Storage",
    "vitamin_d_status": "Vitamin D Status",
    "lipid_diet_response": "Lipid Diet Response",
    "obesity_predisposition": "Obesity Predisposition",
}


def _normalize_dashboard_nutrigenomics_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return {
        key: raw[key]
        for key in _PANEL_SCHEMAS["nutrigenomics"]["row_fields"]
        if raw.get(key) not in (None, "", [])
    } or None


def _normalize_native_nutrigenomics_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    variant = raw.get("variant") or {}
    gene_obj = raw.get("gene") or {}
    gene = (gene_obj.get("symbol") if isinstance(gene_obj, dict) else None) or (
        gene_obj if isinstance(gene_obj, str) else None
    ) or _pick(raw, "gene")
    rsid = (variant.get("rsid") if isinstance(variant, dict) else None) or _pick(raw, "rsid")
    domain = _pick(raw, "domain") or ""
    marker = _NUTRI_DOMAIN_LABELS.get(domain) or _pick(raw, "marker")
    if not marker:
        hgvs = variant.get("hgvs_p") if isinstance(variant, dict) else None
        if hgvs and gene:
            marker = f"{gene} {hgvs[2:] if hgvs.startswith('p.') else hgvs}"
        elif gene and rsid:
            marker = f"{gene} ({rsid})"
        else:
            marker = gene or rsid
    effect = raw.get("established_effect") or {}
    recommendation = (
        (effect.get("claim") if isinstance(effect, dict) else None) or _pick(raw, "recommendation")
    )
    evidence_tier = _pick(raw, "evidence_tier", "evidenceTier")
    status = _pick(raw, "status", "genotype")
    out: dict[str, Any] = {}
    if marker:
        out["marker"] = marker
    if gene:
        out["gene"] = gene
    if rsid:
        out["rsid"] = rsid
    if status:
        out["status"] = status
    if evidence_tier:
        out["evidenceTier"] = evidence_tier
    if recommendation:
        out["recommendation"] = recommendation
    return out or None


def _normalize_nutrigenomics(raw: Any) -> list[dict[str, Any]] | None:
    if isinstance(raw, dict):
        rows = native_panel_rows("nutrigenomics", raw)
        if rows is None:
            return None
        return _normalize_required_rows(rows, panel="nutrigenomics", row_normalizer=_normalize_native_nutrigenomics_row)
    return _normalize_required_rows(raw, panel="nutrigenomics", row_normalizer=_normalize_dashboard_nutrigenomics_row)


def _normalize_required_rows(
    raw: Any,
    *,
    panel: str,
    row_normalizer: Any,
) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        normalized = row_normalizer(item)
        if not normalized:
            raise DashboardRenderError(
                "panel_schema_mismatch",
                f"Panel '{panel}' row {index} was supplied but no recognized fields "
                "mapped to the dashboard schema.",
            )
        rows.append(normalized)
    return rows or None


_PANEL_NORMALIZERS: dict[str, Any] = {
    "overview": _normalize_overview,
    "ancestry": _normalize_ancestry,
    "journal": _normalize_journal,
    "variants": _normalize_variants,
    "variants_all": _normalize_variants_all,
    "pgx": normalize_pgx_panel,
    "risk": normalize_risk_panel,
    "nutrigenomics": _normalize_nutrigenomics,
}

# Canonical post-normalization schema each panel must satisfy. A panel the
# agent never supplies (absent, or empty `{}`/`[]`/None) renders as the
# "Not gathered yet" placeholder — that is a valid partial dashboard. But a
# panel supplied with real content that fails this schema raises
# `panel_schema_mismatch` instead of silently rendering blank, so a field that
# didn't map surfaces as a loud error rather than a misleading empty stat.
#
# Object panels require every listed field to be present after normalization.
# List panels require a list whose every row is a non-empty object with at
# least one field the dashboard actually renders.
_PANEL_SCHEMAS: dict[str, dict[str, Any]] = {
    "overview": {"kind": "object", "required": ("sampleId", "variantCount")},
    "ancestry": {"kind": "object", "required": ("dominantAncestry", "neighbors")},
    "variants": {
        "kind": "list",
        "row_fields": (
            "rsid",
            "gene",
            "chrom",
            "pos",
            "ref",
            "alt",
            "zygosity",
            "clinvarSignificance",
            "conditionShort",
            "evidenceQuality",
        ),
    },
    "variants_all": {
        "kind": "list",
        "row_fields": (
            "rsid",
            "gene",
            "chrom",
            "pos",
            "ref",
            "alt",
            "zygosity",
            "clinvarSignificance",
            "conditionShort",
            "evidenceQuality",
        ),
    },
    "pgx": {
        "kind": "list",
        "required": ("gene",),
        "row_fields": ("gene", "diplotype", "phenotype", "impact", "drugs"),
    },
    "risk": {
        "kind": "list",
        "required": ("trait",),
        "row_fields": ("trait", "score", "percentile", "overlap", "sources"),
    },
    "nutrigenomics": {
        "kind": "list",
        "row_fields": ("marker", "gene", "rsid", "status", "recommendation", "evidenceTier"),
    },
    "journal": {
        "kind": "list",
        "row_fields": ("title", "body", "kind", "ts", "evidenceLinks"),
    },
}


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _explicitly_empty_panels(evidence: JsonObject | None) -> set[str]:
    """Return panel keys the caller supplied with an empty value.

    In update mode this is distinct from omission: omission preserves the
    previous panel, while an explicitly empty panel clears it.
    """
    if not isinstance(evidence, dict):
        return set()
    return {
        key
        for key in PANEL_KEYS
        if key in evidence and (_is_empty(evidence[key]) or is_native_empty_panel(key, evidence[key]))
    }


def _normalize_clear_panels(clear_panels: Any) -> set[str]:
    if clear_panels in (None, "", []):
        return set()
    if not isinstance(clear_panels, list):
        raise DashboardRenderError(
            "invalid_params",
            "clear_panels must be a list of dashboard panel names.",
        )
    panels: set[str] = set()
    invalid: list[Any] = []
    for panel in clear_panels:
        if isinstance(panel, str) and panel in PANEL_KEYS:
            panels.add(panel)
        else:
            invalid.append(panel)
    if invalid:
        raise DashboardRenderError(
            "invalid_params",
            "clear_panels contains unknown dashboard panel(s): "
            f"{', '.join(str(p) for p in invalid)}. "
            f"Valid panels: {', '.join(PANEL_KEYS)}.",
        )
    return panels


def _merge_panel_evidence(
    *,
    previous: JsonObject,
    supplied: JsonObject,
    cleared: set[str],
) -> JsonObject:
    merged: JsonObject = {
        key: previous[key]
        for key in PANEL_KEYS
        if key in previous and previous[key] is not None and key not in cleared
    }
    for key, value in supplied.items():
        if key not in cleared:
            merged[key] = value
    return merged


def _validate_panel(panel: str, normalized: Any) -> None:
    """Raise DashboardRenderError when a normalized panel breaks its schema."""
    schema = _PANEL_SCHEMAS.get(panel)
    if schema is None:
        return
    if schema["kind"] == "object":
        if not isinstance(normalized, dict):
            raise DashboardRenderError(
                "panel_schema_mismatch",
                f"Panel '{panel}' must be an object; got {type(normalized).__name__}.",
            )
        missing = [f for f in schema["required"] if normalized.get(f) in (None, "", [])]
        if missing:
            raise DashboardRenderError(
                "panel_schema_mismatch",
                f"Panel '{panel}' is missing required field(s) after normalization: "
                f"{', '.join(missing)}. Recognized keys: {sorted(normalized)}. "
                f"Required: {', '.join(schema['required'])}.",
            )
    else:  # list
        if not isinstance(normalized, list):
            raise DashboardRenderError(
                "panel_schema_mismatch",
                f"Panel '{panel}' must be a list of row objects; got {type(normalized).__name__}.",
            )
        for i, row in enumerate(normalized):
            if not isinstance(row, dict) or not row:
                raise DashboardRenderError(
                    "panel_schema_mismatch",
                    f"Panel '{panel}' row {i} must be a non-empty object; got {row!r}.",
                )
            row_fields = tuple(schema.get("row_fields") or ())
            if row_fields and all(row.get(field) in (None, "", []) for field in row_fields):
                raise DashboardRenderError(
                    "panel_schema_mismatch",
                    f"Panel '{panel}' row {i} has no recognized dashboard field. "
                    f"Recognized row fields: {', '.join(row_fields)}.",
                )
            missing = [f for f in tuple(schema.get("required") or ()) if row.get(f) in (None, "", [])]
            if missing:
                raise DashboardRenderError(
                    "panel_schema_mismatch",
                    f"Panel '{panel}' row {i} is missing required field(s) after normalization: "
                    f"{', '.join(missing)}. Recognized keys: {sorted(row)}.",
                )


def _safe_evidence(
    evidence: JsonObject | None,
    *,
    skip_panels: set[str] | None = None,
) -> JsonObject:
    """Normalize per-panel evidence and validate each supplied panel.

    Absent or empty panels are skipped (they render as placeholders in a full
    render; update-mode clearing is handled by ``render_dashboard``).
    A panel supplied with real content is normalized and then validated against
    `_PANEL_SCHEMAS`; a content-bearing panel that normalizes to nothing, or
    that fails its schema, raises `panel_schema_mismatch`. Empty journal input
    is the one tolerated "supplied but nothing" case, since "no entries" is a
    normal state.
    """
    payload: JsonObject = {}
    skipped = skip_panels or set()
    if not isinstance(evidence, dict):
        return payload
    for key in PANEL_KEYS:
        if key in skipped:
            continue
        if key not in evidence or _is_empty(evidence[key]):
            continue
        normalizer = _PANEL_NORMALIZERS.get(key, _passthrough)
        try:
            normalized = normalizer(evidence[key])
        except PanelNormalizationError as exc:
            raise DashboardRenderError("panel_schema_mismatch", str(exc)) from exc
        if _is_empty(normalized):
            if key == "journal":
                continue
            raise DashboardRenderError(
                "panel_schema_mismatch",
                f"Panel '{key}' was supplied but no recognized fields mapped to the "
                f"dashboard schema. Supplied keys: "
                f"{sorted(evidence[key]) if isinstance(evidence[key], dict) else type(evidence[key]).__name__}.",
            )
        _validate_panel(key, normalized)
        payload[key] = normalized
    return payload


def _json_blob(evidence: JsonObject) -> str:
    blob = json.dumps(evidence, ensure_ascii=False, default=str)
    # Defang any inline ``</script>`` sequences inside the embedded JSON.
    return blob.replace("</", "<\\/")


def _read_existing_evidence(path: Path) -> JsonObject:
    text = path.read_text(encoding="utf-8")
    assignment_index = text.find(_EVIDENCE_ASSIGNMENT)
    if assignment_index < 0:
        raise DashboardRenderError(
            "dashboard_corrupt",
            f"Existing dashboard at {path} does not contain a __GENOMI_DASHBOARD__ block.",
        )
    json_start = text.find("{", assignment_index)
    if json_start < 0:
        raise DashboardRenderError(
            "dashboard_corrupt",
            f"Existing dashboard at {path} does not contain a dashboard evidence object.",
        )
    try:
        loaded, _end = json.JSONDecoder().raw_decode(text[json_start:].replace("<\\/", "</"))
    except json.JSONDecodeError as exc:
        raise DashboardRenderError(
            "dashboard_corrupt",
            f"Existing dashboard at {path} has an unparseable evidence block: {exc}",
        ) from exc
    if not isinstance(loaded, dict):
        raise DashboardRenderError(
            "dashboard_corrupt",
            f"Existing dashboard at {path} has a non-object evidence block.",
        )
    return loaded


def _read_vendor_asset(path: Path) -> str:
    if not path.is_file():
        raise DashboardRenderError(
            "vendor_asset_missing",
            f"Vendored dashboard asset {path.name} is missing at {path}. "
            f"Run scripts/build_dashboard.py to (re)generate the compiled app.",
        )
    return path.read_text(encoding="utf-8")


def _read_app_js() -> str:
    chunks: list[tuple[int, Path]] = []
    for path in _VENDOR_DIR.glob("dashboard.compiled.*.js"):
        match = _APP_JS_CHUNK_RE.fullmatch(path.name)
        if match:
            chunks.append((int(match.group("index")), path))
    chunks.sort()
    if not chunks:
        raise DashboardRenderError(
            "vendor_asset_missing",
            f"Vendored dashboard app chunks are missing under {_VENDOR_DIR}. "
            f"Run scripts/build_dashboard.py to (re)generate the compiled app.",
        )
    expected = list(range(1, len(chunks) + 1))
    observed = [index for index, _ in chunks]
    if observed != expected:
        raise DashboardRenderError(
            "vendor_asset_missing",
            f"Vendored dashboard app chunks are not contiguous under {_VENDOR_DIR}: "
            f"observed {observed}, expected {expected}. Run scripts/build_dashboard.py.",
        )
    return "\n".join(_read_vendor_asset(path) for _, path in chunks)


def _render_html(evidence: JsonObject) -> str:
    template = _read_template()
    logo = _read_logo_data_url()
    blob = _json_blob(evidence)
    # Inline React + ReactDOM (UMD) and the precompiled app, in load order, so
    # the artifact renders fully offline — no CDN, no in-browser transpile.
    react = _read_vendor_asset(_REACT_PATH)
    react_dom = _read_vendor_asset(_REACT_DOM_PATH)
    app_js = _read_app_js()
    vendor_scripts = f"<script>{react}</script>\n  <script>{react_dom}</script>"
    # Inline the scripts first, then substitute logo/evidence across the whole
    # document — the logo placeholder lives in the app JS, so it must already be
    # spliced in before that replacement runs.
    return (
        template.replace("__GENOMI_VENDOR_SCRIPTS__", vendor_scripts)
        .replace("__GENOMI_APP_JS__", app_js)
        .replace("__GENOMI_LOGO_DATA_URL__", logo)
        .replace("__GENOMI_EVIDENCE__", blob)
    )


def default_output_path(work_dir: str | Path | None) -> Path:
    # The dashboard is a transient view artifact, not part of the persistent
    # Active Genome Index tree, so it lives under the system temp dir. Key it
    # by the sample's project-dir name (the parent of work_dir) so repeated
    # renders and mode="update" calls for the same genome hit the same file.
    base = Path(tempfile.gettempdir()) / "genomi-dashboards"
    slug = Path(work_dir).parent.name if work_dir else ""
    return base / (slug or "dashboard") / "dashboard.html"


def _load_variants_all_source(source: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL file of ClinVar match rows and normalize each to the dashboard schema."""
    path = Path(source)
    if not path.is_file():
        raise DashboardRenderError(
            "variants_all_source_not_found",
            f"variants_all_source does not exist or is not a file: {path}",
        )
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_number, line in enumerate(fh, start=1):
            raw_line = line.strip()
            if not raw_line:
                continue
            try:
                raw = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DashboardRenderError(
                    "variants_all_source_malformed",
                    f"variants_all_source line {line_number} is not valid JSON: {exc.msg}.",
                ) from exc
            normalized = _normalize_native_variants_row(raw)
            if not normalized:
                raise DashboardRenderError(
                    "variants_all_source_malformed",
                    f"variants_all_source line {line_number} did not map to a dashboard variant row.",
                )
            rows.append(normalized)
    return rows


def render_dashboard(
    *,
    evidence: JsonObject | None,
    mode: str = "full",
    output: str | Path,
    variants_all_source: str | Path | None = None,
    clear_panels: list[str] | None = None,
) -> JsonObject:
    """Render or update the Genomi Dashboard artifact.

    Parameters
    ----------
    evidence:
        Panel evidence keyed by panel name. Unknown keys are ignored. In update
        mode, omitted panels preserve previous evidence; explicitly empty
        panels clear previous evidence.
    mode:
        ``"full"`` writes a brand-new dashboard. ``"update"`` reads the
        existing dashboard at ``output``, top-level-merges supplied panels
        over the previous evidence, and rewrites the file.
    output:
        Filesystem path for the dashboard HTML file. Parent directories are
        created as needed.
    variants_all_source:
        Optional path to a ClinVar matches JSONL file. When supplied and
        ``variants_all`` is not already in ``evidence``, the file is read,
        each row is normalized, and the result is embedded as ``variants_all``.
    clear_panels:
        Optional explicit list of panel keys to remove from the rendered
        evidence. This is mainly for update mode, where omitted panels are
        otherwise preserved.
    """

    if mode not in {"full", "update"}:
        raise DashboardRenderError(
            "invalid_mode", "mode must be 'full' or 'update'."
        )
    out_path = Path(output)
    if mode == "update" and not out_path.is_file():
        raise DashboardRenderError(
            "dashboard_not_found",
            f"No existing dashboard at {out_path}; run with mode=\"full\" first.",
        )

    # Inject variants_all from source file when not already supplied in evidence.
    if variants_all_source:
        ev = dict(evidence) if isinstance(evidence, dict) else {}
        if "variants_all" not in ev:
            ev["variants_all"] = _load_variants_all_source(variants_all_source)
        evidence = ev

    cleared = _explicitly_empty_panels(evidence) | _normalize_clear_panels(clear_panels)
    supplied = _safe_evidence(evidence, skip_panels=cleared)
    previous = (
        _safe_evidence(_read_existing_evidence(out_path), skip_panels=cleared)
        if mode == "update"
        else {}
    )
    merged = _merge_panel_evidence(
        previous=previous,
        supplied=supplied,
        cleared=cleared,
    )

    merged["__renderedAt"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    html = _render_html(merged)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    panels_rendered = [key for key in PANEL_KEYS if key in merged]
    panels_empty = [key for key in PANEL_KEYS if key not in merged]
    resolved_path = out_path.resolve()
    serve_dir = resolved_path.parent
    serve_port = 8765
    serve_url = f"http://127.0.0.1:{serve_port}/{resolved_path.name}"
    serve_command = (
        f"python3 -m http.server {serve_port} --bind 127.0.0.1 "
        f"--directory {shlex.quote(str(serve_dir))}"
    )
    return {
        "status": "completed",
        "mode": mode,
        "dashboard_path": str(resolved_path),
        "panels_rendered": panels_rendered,
        "panels_empty": panels_empty,
        "serve": {
            "directory": str(serve_dir),
            "filename": resolved_path.name,
            "port": serve_port,
            "url": serve_url,
            "command": serve_command,
            "note": (
                "The host agent serves the dashboard locally. Run `command` in the "
                "background (Claude Code: Bash with run_in_background=true; Codex: "
                "append `&`), then tell the user the URL. If port 8765 is busy, "
                "pick a free port and adjust the URL."
            ),
        },
    }
