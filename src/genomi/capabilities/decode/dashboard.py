"""Render the Genomi Dashboard self-contained HTML artifact.

The renderer is intentionally plain Python: read the template, splice in the
inline logo data URL and the JSON evidence blob, write a single self-contained
HTML file. Components in the embedded React/Babel block read evidence from
``window.__GENOMI_DASHBOARD__`` and fall back to the "Not gathered yet"
placeholder when a panel is missing.
"""

from __future__ import annotations

import base64
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "shell.html"
_LOGO_PATH = _PACKAGE_ROOT / "assets" / "genomi-logo-transparent.png"

_EVIDENCE_RE = re.compile(
    r"window\.__GENOMI_DASHBOARD__\s*=\s*(?P<json>\{.*?\})\s*;",
    re.DOTALL,
)


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


def _deep_pick(d: Any, *keys: str, max_depth: int = 4):
    """Breadth-first search nested dicts for the first non-empty value at any key.

    Upstream ops nest the same field at different depths (e.g.
    ``active_genome_index.summarize`` puts the variant count at
    ``active_genome_index.stats.variant_records``, two levels down). A shallow parent->child
    lookup misses it. Searching breadth-first keeps an explicit top-level value
    winning over a deeper one.
    """
    if not isinstance(d, dict):
        return None
    queue: list[tuple[dict, int]] = [(d, 0)]
    while queue:
        cur, depth = queue.pop(0)
        for k in keys:
            if k in cur and cur[k] not in (None, "", []):
                return cur[k]
        if depth < max_depth:
            for v in cur.values():
                if isinstance(v, dict):
                    queue.append((v, depth + 1))
    return None


def _normalize_source_coverage_item(item: Any) -> JsonObject | None:
    """Normalize a single sourceCoverage entry to ``name``/``status``/``percent``.

    The upstream evidence often uses alternates like ``label``, ``source``,
    ``library``, ``library_id``, or ``id`` for the display name. Other keys
    are preserved alongside.
    """
    if not isinstance(item, dict):
        return None
    name = _pick(item, "name", "label", "source", "library", "library_id", "id")
    status = _pick(item, "status", "state")
    percent = _pick(item, "percent", "coverage", "coverage_percent", "pct")
    out: JsonObject = {}
    if name is not None:
        out["name"] = name
    if status is not None:
        out["status"] = status
    if percent is not None:
        out["percent"] = percent
    # Preserve any extra agent-supplied keys that don't collide.
    for k, v in item.items():
        if k not in out and v not in (None, "", []):
            out[k] = v
    return out or None


def _pass_rate(raw: Any) -> float | None:
    """Derive a 0-100 PASS-rate proxy when no explicit genotype-quality metric is given.

    Many ops surface `pass_records` + `total_records` (e.g.
    ``active_genome_index.summarize`` under ``active_genome_index.stats``,
    ``classify_callset_qc`` under ``summary``). The ratio is a reasonable
    quality proxy for the Overview "Genotype Quality" stat card.
    """
    if not isinstance(raw, dict):
        return None
    candidates: list[dict] = [raw]
    for parent_key in ("active_genome_index", "stats", "summary"):
        sub = raw.get(parent_key)
        if isinstance(sub, dict):
            candidates.append(sub)
            for nested_key in ("stats", "summary"):
                nested = sub.get(nested_key)
                if isinstance(nested, dict):
                    candidates.append(nested)
    for c in candidates:
        pr = c.get("pass_records")
        tr = c.get("total_records")
        if isinstance(pr, (int, float)) and isinstance(tr, (int, float)) and tr > 0:
            return round(100 * pr / tr, 1)
    return None


def _normalize_overview(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict):
        return None
    sample_id = _pick(raw, "sampleId", "sample_id", "nickname", "user_nickname") or _deep_pick(
        raw, "run_sample_slug", "sample_slug"
    )
    variant_count = (
        _pick(raw, "variantCount", "variant_count")
        or _deep_pick(raw, "variant_count", "variant_records", "record_count")
    )
    if sample_id is None:
        samples = _deep_pick(raw, "samples")
        if isinstance(samples, list) and samples:
            sample_id = samples[0]
    out = {
        "sampleId": sample_id,
        "genomeBuild": _pick(raw, "genomeBuild", "genome_build") or _deep_pick(raw, "reference"),
        "variantCount": variant_count,
        "genotypeQuality": (
            _deep_pick(raw, "genotypeQuality", "genotype_quality", "mean_gq")
            or _pass_rate(raw)
        ),
        "meanDepth": _deep_pick(raw, "meanDepth", "mean_depth", "mean_dp"),
        "genomeSource": _pick(raw, "genomeSource", "genome_source", "source_format")
            or _deep_pick(raw, "dataSourceType"),
        "parsedAt": _pick(raw, "parsedAt", "parsed_at", "active_genome_index_completed_at", "updated_at", "file_date"),
        "sourceCoverage": _pick(raw, "sourceCoverage", "source_coverage"),
    }
    # Preserve any extra agent-supplied keys that don't collide.
    for k, v in raw.items():
        if k not in out and v not in (None, "", []):
            out[k] = v
    if isinstance(out.get("sourceCoverage"), list):
        normalized_sources = [
            n for n in (_normalize_source_coverage_item(it) for it in out["sourceCoverage"])
            if n is not None
        ]
        out["sourceCoverage"] = normalized_sources or None
    return {k: v for k, v in out.items() if v is not None}


def _normalize_ancestry(raw: Any) -> JsonObject | None:
    if not isinstance(raw, dict):
        return None
    neighbors_src = (
        raw.get("neighbors")
        or raw.get("nearest_reference_groups")
        or raw.get("nearest_reference_samples")
        or []
    )
    neighbors = []
    if isinstance(neighbors_src, list):
        for item in neighbors_src:
            if not isinstance(item, dict):
                continue
            neighbors.append({
                "population": _pick(item, "population", "group", "label", "id", "sample"),
                "similarity": _pick(item, "similarity", "score", "distance", "overlap"),
            })
    out = {
        "dominantAncestry": _pick(raw, "dominantAncestry", "dominant_ancestry", "predicted_group")
            or (neighbors[0]["population"] if neighbors else None),
        "neighbors": neighbors or None,
        "pcaPoints": _pick(raw, "pcaPoints", "pca_points"),
        "markerOverlapQuality": _pick(raw, "markerOverlapQuality", "marker_overlap_quality"),
        "overlapFraction": _pick(raw, "overlapFraction", "overlap_fraction"),
        "panelId": _pick(raw, "panelId", "panel_id"),
        "method": _pick(raw, "method"),
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
    parts = genotype.replace("|", "/").split("/")
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


def _normalize_variants_row(raw: Any) -> dict[str, Any] | None:
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

    # clinvarSignificance: canonical name, common aliases, matches-JSONL field, or
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

    # conditionShort: canonical name, common alias, or from clinvar sub-dict.
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


def _normalize_variants(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    rows = [r for r in (_normalize_variants_row(item) for item in raw) if r]
    return rows or None


_NUTRI_DOMAIN_LABELS: dict[str, str] = {
    "folate_metabolism": "Folate Metabolism",
    "lactose_tolerance": "Lactose Tolerance",
    "iron_storage": "Iron Storage",
    "vitamin_d_status": "Vitamin D Status",
    "lipid_diet_response": "Lipid Diet Response",
    "obesity_predisposition": "Obesity Predisposition",
}


def _normalize_nutrigenomics_row(raw: Any) -> dict[str, Any] | None:
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
    if not isinstance(raw, list):
        return None
    rows = [r for r in (_normalize_nutrigenomics_row(item) for item in raw) if r]
    return rows or None


_PANEL_NORMALIZERS: dict[str, Any] = {
    "overview": _normalize_overview,
    "ancestry": _normalize_ancestry,
    "journal": _normalize_journal,
    "variants": _normalize_variants,
    "variants_all": _normalize_variants,
    "pgx": _passthrough,
    "risk": _passthrough,
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
# List panels require a list whose every row is a non-empty object.
_PANEL_SCHEMAS: dict[str, dict[str, Any]] = {
    "overview": {"kind": "object", "required": ("sampleId", "variantCount")},
    "ancestry": {"kind": "object", "required": ("dominantAncestry", "neighbors")},
    "variants": {"kind": "list"},
    "variants_all": {"kind": "list"},
    "pgx": {"kind": "list"},
    "risk": {"kind": "list"},
    "nutrigenomics": {"kind": "list"},
    "journal": {"kind": "list"},
}


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


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


def _safe_evidence(evidence: JsonObject | None) -> JsonObject:
    """Normalize per-panel evidence and validate each supplied panel.

    Absent or empty panels are skipped (they render as placeholders). A panel
    supplied with real content is normalized and then validated against
    `_PANEL_SCHEMAS`; a content-bearing panel that normalizes to nothing, or
    that fails its schema, raises `panel_schema_mismatch`. Empty journal input
    is the one tolerated "supplied but nothing" case, since "no entries" is a
    normal state.
    """
    payload: JsonObject = {}
    if not isinstance(evidence, dict):
        return payload
    for key in PANEL_KEYS:
        if key not in evidence or _is_empty(evidence[key]):
            continue
        normalizer = _PANEL_NORMALIZERS.get(key, _passthrough)
        normalized = normalizer(evidence[key])
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
    match = _EVIDENCE_RE.search(text)
    if not match:
        raise DashboardRenderError(
            "dashboard_corrupt",
            f"Existing dashboard at {path} does not contain a __GENOMI_DASHBOARD__ block.",
        )
    raw = match.group("json").replace("<\\/", "</")
    try:
        loaded = json.loads(raw)
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


def _render_html(evidence: JsonObject) -> str:
    template = _read_template()
    logo = _read_logo_data_url()
    blob = _json_blob(evidence)
    return template.replace("__GENOMI_LOGO_DATA_URL__", logo).replace(
        "__GENOMI_EVIDENCE__", blob
    )


def default_output_path(work_dir: str | Path | None) -> Path:
    # The dashboard is a transient view artifact, not part of the persistent
    # Active Genome Index tree, so it lives under the system temp dir. Key it
    # by the sample's project-dir name (the parent of work_dir) so repeated
    # renders and mode="update" calls for the same genome hit the same file.
    base = Path(tempfile.gettempdir()) / "genomi-dashboards"
    slug = Path(work_dir).parent.name if work_dir else ""
    return base / (slug or "dashboard") / "dashboard.html"


def _load_variants_all_source(source: str | Path) -> list[dict[str, Any]] | None:
    """Read a JSONL file of ClinVar match rows and normalize each to the dashboard schema."""
    path = Path(source)
    if not path.is_file():
        return None
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            normalized = _normalize_variants_row(raw)
            if normalized:
                rows.append(normalized)
    return rows or None


def render_dashboard(
    *,
    evidence: JsonObject | None,
    mode: str = "full",
    output: str | Path,
    variants_all_source: str | Path | None = None,
) -> JsonObject:
    """Render or update the Genomi Dashboard artifact.

    Parameters
    ----------
    evidence:
        Panel evidence keyed by panel name. Unknown keys are ignored.
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
        if not ev.get("variants_all"):
            rows = _load_variants_all_source(variants_all_source)
            if rows:
                ev["variants_all"] = rows
        evidence = ev

    supplied = _safe_evidence(evidence)
    if mode == "update":
        previous = _safe_evidence(_read_existing_evidence(out_path))
        merged: JsonObject = {
            key: previous[key]
            for key in PANEL_KEYS
            if key in previous and previous[key] is not None
        }
        for key, value in supplied.items():
            merged[key] = value
    else:
        merged = supplied

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
        f"python3 -m http.server {serve_port} --bind 127.0.0.1 --directory {serve_dir}"
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
