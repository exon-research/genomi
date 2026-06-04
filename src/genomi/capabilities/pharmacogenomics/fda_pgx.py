from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from ...evidence import envelope as _env
from ...runtime.external import utc_now
from ...runtime.libraries import registry as library_registry

FDA_BIOMARKERS_URL = library_registry.get("fda-pgx").source.api_base or ""
FDA_ASSOCIATIONS_URL = "https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations"
FDA_TIMEOUT_SECONDS = 20
FDA_MAX_LIMIT = 50
FDA_MAX_RAW_TEXT_CHARS = 600


def lookup_fda_pgx(
    *,
    drug: str | None = None,
    gene: str | None = None,
    source: str = "all",
    include_raw_rows: bool = False,
    limit: int = 25,
    biomarkers_url: str | None = None,
    associations_url: str | None = None,
) -> dict[str, Any]:
    """Fetch targeted FDA PGx table rows from official FDA pages."""

    target = {"drug": _clean(drug), "gene": _normalize_gene(gene), "source": _source(source)}
    raw_calls: list[dict[str, Any]] = []
    if not target["drug"] and not target["gene"]:
        return _empty_result(
            target,
            raw_calls=raw_calls,
            status="invalid_target",
            missing_inputs=["drug", "gene"],
        )

    bounded_limit = _bounded_limit(limit)
    rows: list[dict[str, Any]] = []
    if target["source"] in {"all", "biomarkers"}:
        rows.extend(
            _lookup_biomarker_rows(
                biomarkers_url or FDA_BIOMARKERS_URL,
                target=target,
                raw_calls=raw_calls,
                include_raw_rows=include_raw_rows,
                limit=bounded_limit,
            )
        )
    if target["source"] in {"all", "associations"} and len(rows) < bounded_limit:
        rows.extend(
            _lookup_association_rows(
                associations_url or FDA_ASSOCIATIONS_URL,
                target=target,
                raw_calls=raw_calls,
                include_raw_rows=include_raw_rows,
                limit=bounded_limit - len(rows),
            )
        )

    record_payloads = _record_research_payloads(rows, target=target)
    raw_errors = _raw_call_errors(raw_calls)
    if rows:
        status = "completed"
    elif raw_errors:
        status = "source_unavailable"
    else:
        status = "no_matching_fda_pgx_records"
    result = {
        "ok": status in {"completed", "no_matching_fda_pgx_records"},
        "status": status,
        "source": {
            "source_id": "fda_pgx",
            "title": "FDA pharmacogenomic and pharmacogenetic tables",
            "biomarkers_url": biomarkers_url or FDA_BIOMARKERS_URL,
            "associations_url": associations_url or FDA_ASSOCIATIONS_URL,
            "accessed_at": utc_now(),
        },
        "query": target,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "biomarker_labeling_count": sum(1 for row in rows if row.get("evidence_class") == "fda_pharmacogenomic_biomarker_labeling"),
            "association_count": sum(1 for row in rows if row.get("evidence_class") == "fda_pharmacogenetic_association"),
            "record_research_payload_count": len(record_payloads),
        },
        "record_research_payloads": record_payloads,
        "raw_calls": raw_calls,
    }
    if raw_errors:
        result["warnings"] = raw_errors
    return _attach_evidence_envelope(result)


def _empty_result(
    target: dict[str, Any],
    *,
    raw_calls: list[dict[str, Any]],
    status: str,
    missing_inputs: list[str],
) -> dict[str, Any]:
    result = {
        "ok": False,
        "status": status,
        "source": {
            "source_id": "fda_pgx",
            "title": "FDA pharmacogenomic and pharmacogenetic tables",
            "biomarkers_url": FDA_BIOMARKERS_URL,
            "associations_url": FDA_ASSOCIATIONS_URL,
            "accessed_at": utc_now(),
        },
        "query": target,
        "rows": [],
        "summary": {
            "row_count": 0,
            "biomarker_labeling_count": 0,
            "association_count": 0,
            "record_research_payload_count": 0,
        },
        "record_research_payloads": [],
        "raw_calls": raw_calls,
        "unanswered_answer_components": [
            {
                "component": "public_fda_pgx_target",
                "state": "missing",
                "missing_inputs": missing_inputs,
            }
        ],
    }
    return _attach_evidence_envelope(result)


def _attach_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    result["evidence_envelope"] = _fda_pgx_evidence_envelope(result)
    return result


def _fda_pgx_evidence_envelope(result: dict[str, Any]) -> dict[str, Any]:
    operation = "pharmacogenomics.fetch_fda_labels"
    target = dict(result.get("query") or {})
    summary = dict(result.get("summary") or {})
    raw_calls = result.get("raw_calls") or []
    status = str(result.get("status") or "")
    observations = {
        "status": status,
        "row_count": summary.get("row_count", 0),
        "biomarker_labeling_count": summary.get("biomarker_labeling_count", 0),
        "association_count": summary.get("association_count", 0),
    }
    coverage = _env._coverage(
        libraries=[{"library": "fda-pgx", "state": "failed" if status == "source_unavailable" else "installed"}],
        consulted_sources=["fda_pgx"] if raw_calls and status != "source_unavailable" else [],
        unavailable_sources=["fda_pgx"] if status == "source_unavailable" else [],
    )
    if status == "invalid_target":
        return _env.not_assessed(
            operation=operation,
            reason="Missing FDA PGx public target.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "provide_public_fda_pgx_target",
                    "missing_inputs": ["drug", "gene"],
                }
            ],
            guidance=["target_missing:provide_drug_or_gene"],
        )
    if status == "source_unavailable":
        return _env.not_assessed(
            operation=operation,
            reason="FDA PGx source lookup was unavailable.",
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "use_alternate_pgx_source_or_retry",
                    "operations": [
                        "pharmacogenomics.fetch_clinpgx",
                        "pharmacogenomics.fetch_pgxdb",
                    ],
                }
            ],
            guidance=["source_unavailable:retry_or_use_other_pgx_sources"],
        )
    if status == "no_matching_fda_pgx_records":
        return _env.empty_consulted_scope(
            operation=operation,
            query_scope=target,
            coverage=coverage,
            observations=observations,
            next_actions=[
                {
                    "action": "try_alternate_pgx_source_or_target_spelling",
                    "operations": [
                        "pharmacogenomics.fetch_clinpgx",
                        "pharmacogenomics.fetch_pgxdb",
                    ],
                    "target_fields": ["drug", "gene"],
                }
            ],
            guidance=[
                "not_observed_in_consulted_scope:fda_pgx_no_records_for_target",
                "negative_inference_disallowed:check_other_pgx_sources",
            ],
        )
    return _env.evidence_present(
        operation=operation,
        query_scope=target,
        coverage=coverage,
        observations=observations,
        answer_readiness=_env.SCOPED_ANSWER_ONLY,
        next_actions=[
            {
                "action": "check_sample_support_before_personal_statement",
                "operation": "variant.resolve",
                "target_fields": ["gene"],
            }
        ],
        guidance=[
            "fda_pgx_evidence_present:public_label_context_only",
            "sample_context:check_genotype_separately",
        ],
    )


def _lookup_biomarker_rows(
    url: str,
    *,
    target: dict[str, Any],
    raw_calls: list[dict[str, Any]],
    include_raw_rows: bool,
    limit: int,
) -> list[dict[str, Any]]:
    text = _fetch_text(url, raw_calls=raw_calls)
    rows = []
    for row in _html_table_rows(text):
        normalized = _normalize_biomarker_row(row, url=url, include_raw_rows=include_raw_rows)
        if normalized and _row_matches(normalized, target):
            rows.append(normalized)
            if len(rows) >= limit:
                break
    return rows


def _lookup_association_rows(
    url: str,
    *,
    target: dict[str, Any],
    raw_calls: list[dict[str, Any]],
    include_raw_rows: bool,
    limit: int,
) -> list[dict[str, Any]]:
    text = _fetch_text(url, raw_calls=raw_calls)
    rows = []
    for row in _html_table_rows(text):
        normalized = _normalize_association_row(row, url=url, include_raw_rows=include_raw_rows)
        if normalized and _row_matches(normalized, target):
            rows.append(normalized)
            if len(rows) >= limit:
                break
    return rows


def _normalize_biomarker_row(row: dict[str, str], *, url: str, include_raw_rows: bool) -> dict[str, Any]:
    drug = _first_present(row, "Drug")
    biomarker = _first_present(row, "Biomarker", "Biomarker†")
    if not drug or not biomarker:
        return {}
    record = {
        "source_id": "fda_pharmacogenomics",
        "evidence_class": "fda_pharmacogenomic_biomarker_labeling",
        "drug": drug,
        "gene_or_biomarker": biomarker,
        "therapeutic_area": _first_present(row, "Therapeutic Area", "Therapeutic Area*"),
        "labeling_sections": _first_present(row, "Labeling Sections"),
        "source_url": url,
    }
    if include_raw_rows:
        record["raw"] = _compact_raw(row)
    return record


def _normalize_association_row(row: dict[str, str], *, url: str, include_raw_rows: bool) -> dict[str, Any]:
    drug = _first_present(row, "Drug")
    gene = _first_present(row, "Gene")
    if not drug or not gene:
        return {}
    record = {
        "source_id": "fda_pharmacogenetic_associations",
        "evidence_class": "fda_pharmacogenetic_association",
        "drug": drug,
        "gene_or_biomarker": gene,
        "affected_subgroups": _first_present(row, "Affected Subgroups", "Affected Subgroups+"),
        "description": _first_present(row, "Description of Gene-Drug Interaction", "Description"),
        "source_url": url,
    }
    if include_raw_rows:
        record["raw"] = _compact_raw(row)
    return record


def _html_table_rows(text: str) -> list[dict[str, str]]:
    parser = _TableParser()
    parser.feed(text or "")
    return parser.records()


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_cell = False
        self._in_row = False
        self._cell_chunks: list[str] = []
        self._row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(_clean(" ".join(self._cell_chunks)) or "")
            self._in_cell = False
            self._cell_chunks = []
        elif tag == "tr" and self._in_row:
            if any(cell for cell in self._row):
                self._rows.append(self._row)
            self._in_row = False
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_chunks.append(html.unescape(data))

    def records(self) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        header: list[str] = []
        for row in self._rows:
            if not header and _looks_like_header(row):
                header = [_normalize_header(cell) for cell in row]
                continue
            if not header or len(row) < 2:
                continue
            record = {header[index]: row[index] for index in range(min(len(header), len(row))) if header[index]}
            if record:
                records.append(record)
        return records


def _looks_like_header(row: list[str]) -> bool:
    normalized = {_normalize_header(cell).casefold() for cell in row}
    return "drug" in normalized and ("gene" in normalized or "biomarker" in normalized)


def _normalize_header(value: str) -> str:
    text = re.sub(r"[\u2020*+]+", "", value)
    return _clean(text) or ""


def _row_matches(row: dict[str, Any], target: dict[str, Any]) -> bool:
    drug = target.get("drug")
    gene = target.get("gene")
    if drug and _norm_text(drug) not in _norm_text(row.get("drug")):
        return False
    return not (gene and _norm_text(gene) not in _norm_text(row.get("gene_or_biomarker")))


def _record_research_payloads(rows: list[dict[str, Any]], *, target: dict[str, Any]) -> list[dict[str, Any]]:
    accessed_at = utc_now()
    payloads = []
    for row in rows:
        text = _finding_text(row)
        payloads.append(
            {
                "target": _research_target(row, target),
                "source": {
                    "source_id": "fda_pgx",
                    "title": _source_title(row),
                    "url": row.get("source_url"),
                    "type": row.get("evidence_class"),
                    **_fda_source_table_url(row),
                    "accessed_at": accessed_at,
                },
                "finding": {
                    "type": row.get("evidence_class"),
                    "text": text,
                    "summary": _summary(row),
                },
                "searched_query": json.dumps(target, sort_keys=True),
                "captured_by": "genomi call pharmacogenomics.fetch_fda_labels",
            }
        )
    return payloads


def _fda_source_table_url(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("evidence_class") == "fda_pharmacogenomic_biomarker_labeling":
        return {"biomarkers_url": row.get("source_url")}
    if row.get("evidence_class") == "fda_pharmacogenetic_association":
        return {"associations_url": row.get("source_url")}
    return {}


def _finding_text(row: dict[str, Any]) -> str:
    if row.get("evidence_class") == "fda_pharmacogenomic_biomarker_labeling":
        return _bounded_text(
            f"FDA labeling table lists {row.get('drug')} with biomarker {row.get('gene_or_biomarker')}"
            f" in labeling sections {row.get('labeling_sections') or 'not specified'}.",
            FDA_MAX_RAW_TEXT_CHARS,
        )
    return _bounded_text(
        f"FDA pharmacogenetic association table lists {row.get('drug')} and {row.get('gene_or_biomarker')}: "
        f"{row.get('description') or row.get('affected_subgroups') or 'association context listed'}.",
        FDA_MAX_RAW_TEXT_CHARS,
    )


def _summary(row: dict[str, Any]) -> str:
    pieces = [row.get("drug"), row.get("gene_or_biomarker"), row.get("labeling_sections") or row.get("affected_subgroups")]
    return " ".join(str(piece) for piece in pieces if piece)


def _source_title(row: dict[str, Any]) -> str:
    if row.get("evidence_class") == "fda_pharmacogenomic_biomarker_labeling":
        return "FDA Pharmacogenomic Biomarkers in Drug Labeling"
    return "FDA Pharmacogenetic Associations"


def _research_target(row: dict[str, Any], target: dict[str, Any]) -> dict[str, str]:
    drug = target.get("drug") or row.get("drug")
    gene = target.get("gene") or row.get("gene_or_biomarker")
    topic = " ".join(str(item) for item in (drug, gene, row.get("evidence_class")) if item)
    if drug:
        return {"type": "drug", "drug": str(drug), "topic": topic}
    if gene:
        return {"type": "gene", "gene": str(gene), "topic": topic}
    return {"type": "topic", "topic": topic or "FDA pharmacogenomic evidence"}


def _fetch_text(url: str, *, raw_calls: list[dict[str, Any]]) -> str:
    call: dict[str, Any] = {"url": url, "status": None, "attempts": 0}
    raw_calls.append(call)
    request = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": "genomi/0.1"})
    for attempt in range(2):
        call["attempts"] = attempt + 1
        try:
            with urllib.request.urlopen(request, timeout=FDA_TIMEOUT_SECONDS) as response:
                call["status"] = int(getattr(response, "status", 0) or 0)
                call["content_type"] = response.headers.get("content-type")
                body = response.read()
            return body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            call["status"] = exc.code
            call["error"] = f"HTTP {exc.code}"
            if 400 <= exc.code < 500:
                return ""
        except urllib.error.URLError as exc:
            call["error"] = f"URL error: {exc.reason}"
        except TimeoutError as exc:
            call["error"] = f"timeout: {exc}"
        except OSError as exc:
            call["error"] = f"I/O error: {exc}"
        if attempt == 0:
            time.sleep(0.5)
    return ""


def _raw_call_errors(raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"url": call.get("url"), "status": call.get("status"), "error": call.get("error")}
        for call in raw_calls
        if call.get("error")
    ]


def _first_present(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return None


def _source(value: str | None) -> str:
    cleaned = (value or "all").strip().lower().replace("-", "_")
    return cleaned if cleaned in {"all", "biomarkers", "associations"} else "all"


def _bounded_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 25
    return max(1, min(limit, FDA_MAX_LIMIT))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _normalize_gene(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.upper() if cleaned else None


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _bounded_text(value: Any, max_chars: int) -> str:
    text = _clean(value) or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def _compact_raw(value: dict[str, str]) -> dict[str, str]:
    return {key: _bounded_text(item, FDA_MAX_RAW_TEXT_CHARS) for key, item in value.items()}
