from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import portal_privacy, portal_target_result_presentations
from .portal_result_presentation_model import (
    PERSISTED_REDACTED_PRESENTATION_STATE,
    array_value as _array,
    count_summary as _count_summary,
    empty as _empty,
    entry_lane as _entry_lane,
    evidence_state_lane as _evidence_state_lane,
    format_value as _format_value,
    humanize as _humanize,
    lane as _lane,
    metric as _metric,
    node as _node,
    object_value as _object,
    presentation as _presentation,
    readable_state as _readable_state,
    safe_model as _safe_model,
    string_list as _string_list,
    summary_from_envelope as _summary_from_envelope,
    text as _text,
    text_array as _text_array,
)

JsonObject = dict[str, Any]
Presenter = Callable[..., JsonObject | None]
SummaryBuilder = Callable[[JsonObject], str]


@dataclass(frozen=True)
class PresentationSpec:
    presenter: Presenter
    persisted_payload_keys: frozenset[str]
    persisted_summary: SummaryBuilder | None = None


_PRESENTATION_SPECS: dict[str, PresentationSpec] | None = None
_COMMON_PERSISTED_PAYLOAD_KEYS = frozenset(
    {
        "headline",
        "status",
        "message",
        "query",
        "summary",
        "coverage",
        "coverage_state",
        "evidence_state",
        "candidate_evidence_state",
        "warnings",
        "evidence_envelope",
        "defaults_applied",
    }
)
_VARIANT_PERSISTED_PAYLOAD_KEYS = _COMMON_PERSISTED_PAYLOAD_KEYS | frozenset(
    {"resolved_targets", "public_context"}
)
_PGX_PERSISTED_PAYLOAD_KEYS = _COMMON_PERSISTED_PAYLOAD_KEYS | frozenset(
    {"medication_review_matrix", "evidence_matrix", "unanswered_answer_components"}
)
_CANDIDATE_PERSISTED_PAYLOAD_KEYS = _COMMON_PERSISTED_PAYLOAD_KEYS | frozenset(
    {
        "evidence_view",
        "candidate_matrix",
        "rankings",
        "ranked_associations",
        "association_records",
        "decision_policy",
    }
)
_PERSISTED_CLINVAR_SCAN_PAYLOAD_KEYS = frozenset(
    {
        "headline",
        "status",
        "message",
        "summary",
        "coverage_state",
        "evidence_state",
        "candidate_evidence_state",
        "warnings",
        "evidence_envelope",
        "defaults_applied",
        "available_evidence_groups",
    }
)
_TARGET_PACKET_PERSISTED_PAYLOAD_KEYS = _COMMON_PERSISTED_PAYLOAD_KEYS | frozenset(
    {
        "purpose",
        "target",
        "stored_research",
        "source_catalog",
        "available_operations",
        "evidence_options",
    }
)
CANDIDATE_EVIDENCE_OPERATIONS = frozenset(
    {
    "gwas.compare_variant_associations",
    "gwas.compare_gene_associations",
    "phenotype.compare_gene_hpo_evidence",
    "phenotype.compare_disease_evidence",
    "phenotype.compare_drug_target_evidence",
    "phenotype.plan_risk_investigation",
    "functional_genomics.compare_gene_perturbation",
    "clinvar.scan_candidates",
    }
)


def presentation_for_tool_event(
    event: JsonObject,
    *,
    payload: Any | None = None,
    presentation_state: str = "",
    display_only: bool = False,
) -> JsonObject | None:
    result_payload = payload if payload is not None else event.get("payload")
    if not isinstance(result_payload, dict):
        return None
    operation = _operation_for_event(event, result_payload)
    if not operation:
        return None
    spec = presentation_spec_for_operation(operation)
    if spec:
        model = spec.presenter(
            operation,
            result_payload,
            presentation_state=presentation_state,
            display_only=display_only,
        )
    else:
        model = _generic_evidence_presentation(operation, result_payload)
    return _safe_model(model)


def persisted_payload_for_tool_event(event: JsonObject) -> JsonObject | None:
    value = event.get("payload")
    if not isinstance(value, dict):
        return None
    envelope = value.get("evidence_envelope")
    if not isinstance(envelope, dict):
        return None
    operation = _operation_for_event(event, value)
    spec = presentation_spec_for_operation(operation)
    safe_keys = spec.persisted_payload_keys if spec else _COMMON_PERSISTED_PAYLOAD_KEYS
    payload = {
        key: portal_privacy.prompt_safe_value(value[key])
        for key in safe_keys
        if key in value and value[key] is not None
    }
    if not isinstance(payload.get("evidence_envelope"), dict):
        return None
    payload["presentation_state"] = PERSISTED_REDACTED_PRESENTATION_STATE
    return payload


def persisted_summary_for_tool_event(event: JsonObject) -> str:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    operation = _operation_for_event(event, payload)
    spec = presentation_spec_for_operation(operation)
    if not spec or spec.persisted_summary is None:
        return ""
    return spec.persisted_summary(payload)


def _variant_resolve_presentation(
    operation: str,
    payload: JsonObject,
    *,
    presentation_state: str,
    display_only: bool,
) -> JsonObject | None:
    envelope = _object(payload.get("evidence_envelope"))
    query = _object(payload.get("query"))
    public_context = _object(payload.get("public_context"))
    sample_context = _object(payload.get("sample_context"))
    support_context = _object(payload.get("support_context"))
    targets = _array(payload.get("resolved_targets"))
    clinvar = [
        *_array(public_context.get("clinvar_by_rsid")),
        *_array(public_context.get("clinvar_by_allele")),
        *_array(public_context.get("clinvar_by_locus")),
    ]
    sample_matches = _array(sample_context.get("matches"))
    support = _array(support_context.get("genotype_support"))
    include_private = not display_only and presentation_state != PERSISTED_REDACTED_PRESENTATION_STATE
    title = (
        _text(query.get("rsid"))
        or _locus_label(query)
        or next((_variant_label(item) for item in targets if _variant_label(item)), "")
        or "Variant target"
    )
    lanes = [
        _lane("Resolved targets", [_node(_variant_label(item), _variant_summary(item), item) for item in targets[:8]]),
        _lane("ClinVar records", [_node(_clinvar_label(item), _clinvar_summary(item), item) for item in clinvar[:8]]),
    ]
    if include_private:
        lanes.extend(
            [
                _lane("Sample evidence", [_node(_sample_label(item), _format_value(item), item) for item in sample_matches[:8]]),
                _lane("Genotype support", [_node(_support_label(item), _format_value(item), item) for item in support[:8]]),
            ]
        )
    return _presentation(
        operation=operation,
        kind="variant",
        kicker="Variant evidence map",
        title=title,
        summary=_summary_from_envelope(envelope) or "Resolved variant target, public records, and sample support are grouped by evidence source.",
        envelope=envelope,
        metrics=[
            _metric("Resolved", len(targets)),
            _metric("ClinVar", len(clinvar)),
            _metric("Sample hits", len(sample_matches)) if include_private and "sample_context" in payload else None,
            _metric("Support", len(support)) if include_private and "support_context" in payload else None,
        ],
        lanes=lanes,
        notice=_redacted_notice() if presentation_state == PERSISTED_REDACTED_PRESENTATION_STATE else None,
    )


def _generic_evidence_presentation(operation: str, payload: JsonObject) -> JsonObject | None:
    envelope = _object(payload.get("evidence_envelope"))
    if not envelope:
        return None
    headline = _summary_from_envelope(envelope) or _text(payload.get("headline")) or _text(payload.get("status")) or _display_label(operation)
    return _presentation(
        operation=operation,
        kind="evidence",
        kicker=_display_label(operation),
        title=headline,
        summary=headline,
        envelope=envelope,
        metrics=[
            _metric("Answer boundary", _readable_state(envelope.get("answer_readiness"))),
            _metric("Evidence support", _readable_state(envelope.get("finding_state"))),
            _metric("Retrieval status", _readable_state(payload.get("status"))),
            _metric("Default assumptions", _count_summary(payload.get("defaults_applied"), "applied")),
        ],
        lanes=[
            _entry_lane("Coverage", envelope.get("coverage")),
            _entry_lane("Observations", envelope.get("observations")),
            _entry_lane("Suggested follow-up", envelope.get("next_actions")),
        ],
    )


def presentation_spec_for_operation(operation: str) -> PresentationSpec | None:
    return _presentation_specs().get(operation)


def _presentation_specs() -> dict[str, PresentationSpec]:
    global _PRESENTATION_SPECS
    if _PRESENTATION_SPECS is None:
        candidate_spec = PresentationSpec(
            presenter=_candidate_evidence_presentation,
            persisted_payload_keys=_CANDIDATE_PERSISTED_PAYLOAD_KEYS,
        )
        _PRESENTATION_SPECS = {
            "variant.resolve": PresentationSpec(
                presenter=_variant_resolve_presentation,
                persisted_payload_keys=_VARIANT_PERSISTED_PAYLOAD_KEYS,
            ),
            "pharmacogenomics.review_medication": PresentationSpec(
                presenter=_pgx_review_presentation,
                persisted_payload_keys=_PGX_PERSISTED_PAYLOAD_KEYS,
            ),
            portal_target_result_presentations.TARGET_PACKET_OPERATION: PresentationSpec(
                presenter=portal_target_result_presentations.target_packet_presentation,
                persisted_payload_keys=_TARGET_PACKET_PERSISTED_PAYLOAD_KEYS,
                persisted_summary=portal_target_result_presentations.target_packet_tool_summary,
            ),
            "clinvar.scan_candidates": PresentationSpec(
                presenter=_candidate_evidence_presentation,
                persisted_payload_keys=_PERSISTED_CLINVAR_SCAN_PAYLOAD_KEYS,
            ),
            **{
                operation: candidate_spec
                for operation in CANDIDATE_EVIDENCE_OPERATIONS
                if operation != "clinvar.scan_candidates"
            },
        }
    return _PRESENTATION_SPECS


def _pgx_review_presentation(
    operation: str,
    payload: JsonObject,
    *,
    presentation_state: str,
    display_only: bool,
) -> JsonObject | None:
    envelope = _object(payload.get("evidence_envelope"))
    query = _object(payload.get("query"))
    matrix = _object(payload.get("medication_review_matrix"))
    evidence_matrix = _object(payload.get("evidence_matrix"))
    sample_evidence = _object(payload.get("sample_evidence"))
    rows = _array(matrix.get("rows"))
    role_counts = _object(evidence_matrix.get("role_counts"))
    unanswered = _array(payload.get("unanswered_answer_components"))
    include_private = not display_only and presentation_state != PERSISTED_REDACTED_PRESENTATION_STATE
    title = " / ".join(
        part
        for part in (
            _text(query.get("drug")),
            _text(query.get("gene")),
            _text(query.get("rsid")),
        )
        if part
    ) or "Medication review"
    item_count = evidence_matrix.get("item_count")
    if not isinstance(item_count, int):
        item_count = len(_array(evidence_matrix.get("items")))
    return _presentation(
        operation=operation,
        kind="pgx",
        kicker="Medication evidence matrix",
        title=title,
        summary=_summary_from_envelope(envelope)
        or "Public source rows, sample follow-up targets, and review readiness are organized as an evidence matrix.",
        envelope=envelope,
        metrics=[
            _metric("Rows", len(rows)),
            _metric("Evidence items", item_count),
            _metric("Source roles", len(role_counts)),
            _metric("Star calls", sample_evidence.get("star_allele_call_count"))
            if include_private and "sample_evidence" in payload
            else None,
        ],
        lanes=[
            _lane("Medication rows", [_node(_pgx_row_label(item), _pgx_row_summary(item), item) for item in rows[:8]]),
            _lane(
                "Evidence roles",
                [
                    _node(_humanize(key), f"{value} item{'s' if value != 1 else ''}", {"role": key, "count": value})
                    for key, value in role_counts.items()
                    if not _empty(value)
                ],
            ),
            _lane("Sample follow-up", _pgx_sample_follow_up_nodes(sample_evidence)) if include_private else None,
            _lane(
                "Unanswered components",
                [
                    _node(_pgx_component_label(item), _format_value(item), item)
                    for item in unanswered[:6]
                ],
            ),
        ],
        notice=_redacted_notice() if presentation_state == PERSISTED_REDACTED_PRESENTATION_STATE else None,
    )


def _candidate_evidence_presentation(
    operation: str,
    payload: JsonObject,
    *,
    presentation_state: str,
    display_only: bool,
) -> JsonObject | None:
    envelope = _object(payload.get("evidence_envelope"))
    view = _object(payload.get("evidence_view"))
    query = _object(view.get("query") or payload.get("query"))
    summary = _object(payload.get("summary"))
    if _redact_candidate_rows(operation, presentation_state=presentation_state, display_only=display_only):
        return _redacted_candidate_evidence_presentation(operation, payload, envelope, view, summary)
    candidates = _candidate_rows(payload, view)
    ranked = _candidate_rankings(payload, view, candidates)
    supporting = _candidate_supporting_evidence(payload, view, candidates)
    policy = _object(view.get("evidence_policy") or payload.get("decision_policy"))
    coverage = _object(view.get("coverage") or payload.get("coverage"))
    top_candidate = (
        view.get("top_observed_candidate")
        or payload.get("top_observed_candidate")
        or summary.get("top_observed_candidate")
        or coverage.get("top_observed_candidate")
    )
    support_level = coverage.get("top_observed_support_level") or summary.get("top_observed_support_level")
    coverage_state = view.get("coverage_state") or payload.get("coverage_state")
    candidate_nodes = ranked or candidates
    return _presentation(
        operation=operation,
        kind="candidate_evidence",
        kicker=_candidate_kicker(operation),
        title=_candidate_query_label(query, operation),
        summary=_summary_from_envelope(envelope) or _candidate_summary(view, candidates, supporting),
        envelope=envelope,
        metrics=[
            _metric("Candidates", coverage.get("candidate_count") if coverage.get("candidate_count") is not None else len(candidates)),
            _metric("Ranked", coverage.get("ranked_candidate_count") if coverage.get("ranked_candidate_count") is not None else len(ranked)),
            _metric("Top observed", top_candidate),
            _metric("Support", support_level),
            _metric("Coverage", coverage_state),
            _metric("Answer boundary", _readable_state(envelope.get("answer_readiness"))),
            _metric("Evidence support", _readable_state(envelope.get("finding_state"))),
            _metric("Retrieval status", _readable_state(payload.get("status"))),
            _metric("Default assumptions", _count_summary(payload.get("defaults_applied"), "applied")),
        ],
        lanes=[
            _lane("Candidate comparison", [_candidate_node(item) for item in candidate_nodes[:10]]),
            _lane("Supporting evidence", [_supporting_evidence_node(item) for item in supporting[:10]]),
            _lane("Evidence boundary", _candidate_boundary_nodes(payload, view, policy)),
            _evidence_state_lane(envelope),
        ],
    )


def _redact_candidate_rows(
    operation: str,
    *,
    presentation_state: str,
    display_only: bool,
) -> bool:
    return operation == "clinvar.scan_candidates" and (
        display_only or presentation_state == PERSISTED_REDACTED_PRESENTATION_STATE
    )


def _redacted_candidate_evidence_presentation(
    operation: str,
    payload: JsonObject,
    envelope: JsonObject,
    view: JsonObject,
    summary: JsonObject,
) -> JsonObject:
    coverage = _object(payload.get("coverage") or view.get("coverage"))
    coverage_state = view.get("coverage_state") or payload.get("coverage_state")
    return _presentation(
        operation=operation,
        kind="candidate_evidence",
        kicker=_candidate_kicker(operation),
        title=_candidate_query_label(_object(view.get("query") or payload.get("query")), operation),
        summary=_summary_from_envelope(envelope)
        or "Saved ClinVar candidate scan history is redacted to aggregate coverage and source limits.",
        envelope=envelope,
        metrics=[
            _metric("Candidates", coverage.get("candidate_count") or summary.get("selected_candidate_variants")),
            _metric("Ranked", coverage.get("ranked_candidate_count") or summary.get("emitted_candidate_variants")),
            _metric("Coverage", coverage_state),
            _metric("Answer boundary", _readable_state(envelope.get("answer_readiness"))),
            _metric("Evidence support", _readable_state(envelope.get("finding_state"))),
            _metric("Retrieval status", _readable_state(payload.get("status"))),
            _metric("Default assumptions", _count_summary(payload.get("defaults_applied"), "applied")),
        ],
        lanes=[
            _lane("Scan summary", _redacted_clinvar_summary_nodes(summary), selectable=False),
            _evidence_state_lane(envelope),
        ],
        notice=_redacted_notice(),
    )


def _redacted_clinvar_summary_nodes(summary: JsonObject) -> list[JsonObject | None]:
    safe_keys = (
        "total_match_records",
        "total_match_variants",
        "total_exact_match_variants",
        "total_exact_allele_match_variants",
        "total_consumer_array_inferred_match_variants",
        "selected_candidate_variants",
        "emitted_candidate_variants",
        "truncated",
        "match_basis_counts",
        "available_evidence_group_counts",
        "clinical_significance_counts",
        "review_status_counts",
    )
    return [
        _node(_humanize(key), _format_value(summary[key]), {"field": key, "value": summary[key]})
        for key in safe_keys
        if key in summary and not _empty(summary[key])
    ]


def _operation_for_event(event: JsonObject, payload: JsonObject) -> str:
    envelope = _object(payload.get("evidence_envelope"))
    envelope_operation = _text(envelope.get("operation"))
    if envelope_operation and envelope_operation != "tool":
        return envelope_operation
    event_name = _text(event.get("name"))
    return event_name if event_name and event_name != "tool" else ""


def _variant_label(value: Any) -> str:
    item = _object(value)
    if item.get("rsid"):
        return _text(item.get("rsid"))
    return _locus_label(item)


def _variant_summary(value: Any) -> str:
    item = _object(value)
    parts = [
        _text(item.get("genome_build")),
        _text(item.get("chrom")) + ":" + str(item.get("pos")) if item.get("chrom") and item.get("pos") else "",
        _text(item.get("ref")) + ">" + _text(item.get("alt")) if item.get("ref") and item.get("alt") else "",
    ]
    return " ".join(part for part in parts if part) or _format_value(value)


def _clinvar_label(value: Any) -> str:
    item = _object(value)
    return _text(item.get("clinical_significance")) or _text(item.get("variation_id")) or _text(item.get("accession")) or "ClinVar record"


def _clinvar_summary(value: Any) -> str:
    item = _object(value)
    return " · ".join(_text(item.get(key)) for key in ("condition", "review_status", "source") if _text(item.get(key))) or _format_value(value)


def _sample_label(value: Any) -> str:
    item = _object(value)
    return _text(item.get("rsid")) or _variant_label(item) or _text(item.get("genotype")) or "Sample evidence"


def _support_label(value: Any) -> str:
    item = _object(value)
    return _text(item.get("label")) or _text(item.get("gene")) or _text(item.get("rsid")) or "Genotype support"


def _pgx_row_label(value: Any) -> str:
    item = _object(value)
    return " · ".join(
        part
        for part in (
            _text(item.get("drug")),
            _text(item.get("gene")),
            _text(item.get("rsid") or item.get("variant_or_haplotype")),
            _text(item.get("row_type")),
        )
        if part
    ) or "Medication row"


def _pgx_row_summary(value: Any) -> str:
    item = _object(value)
    sample_relevance = item.get("sample_relevance")
    return " · ".join(
        part
        for part in (
            _text(item.get("phenotype")),
            _text(item.get("diplotype")),
            _text(item.get("recommendation_text")),
            _format_value(sample_relevance) if isinstance(sample_relevance, dict) else _text(sample_relevance),
        )
        if part
    ) or _format_value(value)


def _pgx_sample_follow_up_nodes(sample_evidence: JsonObject) -> list[JsonObject | None]:
    gene_targets = [
        _node(
            _text(_object(item).get("symbol") or _object(item).get("gene") or _object(item).get("name")) or "Gene",
            _text(_object(item).get("name") or _object(item).get("id")) or _format_value(item),
            item,
        )
        for item in _array(sample_evidence.get("star_gene_targets"))[:6]
    ]
    variant_lookups = [
        _node(
            _text(_object(item).get("rsid") or _object(item).get("variant")) or "Variant lookup",
            _format_value(item),
            item,
        )
        for item in _array(sample_evidence.get("variant_lookups"))[:6]
    ]
    return [*gene_targets, *variant_lookups]


def _pgx_component_label(value: Any) -> str:
    item = _object(value)
    return _text(item.get("component") or item.get("state")) or "Component"


def _candidate_rows(payload: JsonObject, view: JsonObject) -> list[Any]:
    view_rows = _array(view.get("candidate_matrix"))
    if view_rows:
        return view_rows
    return _array(payload.get("candidate_matrix"))


def _candidate_rankings(payload: JsonObject, view: JsonObject, candidates: list[Any]) -> list[Any]:
    rankings = _array(view.get("rankings")) or _array(payload.get("rankings"))
    if rankings:
        return rankings
    return [
        candidate
        for candidate in candidates
        if _object(candidate).get("rank") is not None
    ]


def _candidate_supporting_evidence(payload: JsonObject, view: JsonObject, candidates: list[Any]) -> list[Any]:
    by_candidate = []
    for candidate in candidates:
        candidate_model = _object(candidate)
        candidate_id = candidate_model.get("candidate_id")
        for item in _array(candidate_model.get("supporting_evidence")):
            record = dict(_object(item))
            if candidate_id and not record.get("candidate_id"):
                record["candidate_id"] = candidate_id
            by_candidate.append(record)
    if by_candidate:
        return by_candidate
    decision_evidence = _object(view.get("decision_evidence"))
    return [
        *_array(payload.get("ranked_associations")),
        *_array(payload.get("association_records")),
        *_array(decision_evidence.get("supporting_evidence")),
    ]


def _candidate_node(value: Any) -> JsonObject | None:
    item = _object(value)
    return _node(_candidate_row_label(item), _candidate_row_summary(item), value)


def _candidate_row_label(item: JsonObject) -> str:
    rank = item.get("rank")
    rank_prefix = f"#{rank} " if rank is not None else ""
    return rank_prefix + (
        _text(item.get("candidate_id"))
        or _text(item.get("gene"))
        or _text(item.get("rsid"))
        or _text(item.get("variant"))
        or _text(item.get("id"))
        or "Candidate"
    )


def _candidate_row_summary(item: JsonObject) -> str:
    return " · ".join(
        part
        for part in (
            f"support {_text(item.get('evidence_support_level'))}" if _text(item.get("evidence_support_level")) else "",
            _readable_state(item.get("answerability")),
            _readable_state(item.get("best_evidence_lane")),
            f"p={item.get('best_pvalue')}" if item.get("best_pvalue") is not None else "",
            f"score {item.get('score')}" if item.get("score") is not None else "",
        )
        if part
    ) or _format_value(item)


def _supporting_evidence_node(value: Any) -> JsonObject | None:
    item = _object(value)
    return _node(_supporting_evidence_label(item), _supporting_evidence_summary(item), value)


def _supporting_evidence_label(item: JsonObject) -> str:
    return " · ".join(
        part
        for part in (
            _text(item.get("candidate_id")),
            _text(item.get("rsid") or item.get("variant") or item.get("gene")),
            _text(item.get("trait") or item.get("phenotype") or item.get("mapped_trait") or item.get("reported_trait")),
            _text(item.get("source_id") or item.get("association_id") or item.get("record_id") or item.get("id")),
        )
        if part
    ) or "Supporting record"


def _supporting_evidence_summary(item: JsonObject) -> str:
    return " · ".join(
        part
        for part in (
            _readable_state(item.get("evidence_lane")),
            f"p={item.get('pvalue') or item.get('p_value')}" if item.get("pvalue") or item.get("p_value") else "",
            f"effect {_text(item.get('effect_allele'))}" if _text(item.get("effect_allele")) else "",
            _text(item.get("study") or item.get("source") or item.get("pubmed_id") or item.get("publication")),
        )
        if part
    ) or _format_value(item)


def _candidate_boundary_nodes(payload: JsonObject, view: JsonObject, policy: JsonObject) -> list[JsonObject | None]:
    nodes = [
        _boundary_node("Coverage state", view.get("coverage_state") or payload.get("coverage_state")),
        _boundary_node("Evidence boundary", view.get("evidence_state") or payload.get("evidence_state") or payload.get("candidate_evidence_state")),
        _boundary_node("Agent decision", "Required" if view.get("agent_decision_required") is True else ""),
    ]
    if policy:
        nodes.append(_node("Selection policy", _text(policy.get("policy_id") or policy.get("name")) or "Policy details", policy))
    for warning in _text_array(view.get("warnings") or payload.get("warnings"))[:4]:
        nodes.append(_node("Warning", warning, {"warning": warning}))
    return nodes


def _boundary_node(label: str, value: Any) -> JsonObject | None:
    if _empty(value):
        return None
    return _node(label, _readable_state(value), {"label": label, "value": value})


def _candidate_kicker(operation: str) -> str:
    labels = {
        "gwas.compare_gene_associations": "Gene association evidence",
        "gwas.compare_variant_associations": "Variant association evidence",
        "phenotype.compare_gene_hpo_evidence": "Gene phenotype evidence",
        "phenotype.compare_disease_evidence": "Disease phenotype evidence",
        "phenotype.compare_drug_target_evidence": "Drug-target evidence",
        "functional_genomics.compare_gene_perturbation": "Perturbation evidence",
        "phenotype.plan_risk_investigation": "Risk investigation evidence",
        "clinvar.scan_candidates": "ClinVar candidate evidence",
    }
    return labels.get(operation, "Candidate evidence view")


def _candidate_query_label(query: JsonObject, operation: str) -> str:
    focus = _candidate_query_focus(query)
    candidates = " / ".join(_candidate_query_candidates(query)[:3])
    if focus and candidates:
        return f"{focus} / {candidates}"
    if focus:
        return focus
    if candidates:
        return candidates
    fallbacks = {
        "phenotype.compare_gene_hpo_evidence": "Gene phenotype comparison",
        "phenotype.compare_disease_evidence": "Disease phenotype comparison",
        "phenotype.compare_drug_target_evidence": "Drug-target comparison",
        "functional_genomics.compare_gene_perturbation": "Perturbation comparison",
        "phenotype.plan_risk_investigation": "Risk investigation",
        "clinvar.scan_candidates": "ClinVar candidate scan",
        "gwas.compare_gene_associations": "Gene association comparison",
        "gwas.compare_variant_associations": "Variant association comparison",
    }
    return fallbacks.get(operation, "Candidate comparison")


def _candidate_query_focus(query: JsonObject) -> str:
    for key in (
        "phenotype",
        "phenotype_text",
        "trait",
        "condition",
        "context",
        "drug",
        "drug_class",
        "indication",
        "mechanism",
        "question",
        "topic",
        "raw_query",
    ):
        text = _text(query.get(key))
        if text:
            return text
    return ""


def _candidate_query_candidates(query: JsonObject) -> list[str]:
    for key in ("variants", "rsids", "genes", "candidate_diseases", "diseases", "targets", "hpo_ids"):
        values = _string_list(query.get(key))
        if values:
            return values
    return []


def _candidate_summary(view: JsonObject, candidates: list[Any], supporting: list[Any]) -> str:
    coverage_state = _text(view.get("coverage_state"))
    if coverage_state and coverage_state != "data_returned":
        return "No decision-grade candidate ranking was returned for the consulted scope; boundaries and source state are shown below."
    if candidates or supporting:
        return "Candidates, ranked source support, and evidence boundaries are grouped for the next chat turn."
    return "Candidate evidence view returned no displayable rows."


def _locus_label(value: JsonObject) -> str:
    if value.get("chrom") and value.get("pos"):
        allele = _text(value.get("ref")) + ">" + _text(value.get("alt")) if value.get("ref") and value.get("alt") else ""
        return " ".join(part for part in (_text(value.get("genome_build")), f"{value.get('chrom')}:{value.get('pos')}", allele) if part)
    return ""


def _display_label(operation: str) -> str:
    return _humanize(operation.rsplit(".", 1)[-1] or operation)


def _redacted_notice() -> JsonObject:
    return {
        "title": "Persisted redacted history",
        "text": "This saved view includes only persisted public lanes. Re-check the source before using private or sample-specific evidence.",
    }
