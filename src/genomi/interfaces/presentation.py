"""Single-shape presentation for tool results.

There is exactly one rendered shape per operation. The shape:

  - leads with `headline` (one-line verdict) and `evidence_envelope` so a
    host agent sees the answer-readiness immediately
  - preserves the work-trace (steps, coverage, observations, source-level
    lists, warnings) so the agent can judge what the tool actually did
  - prunes pure noise — empty arrays, false-defaulted booleans, long-form
    prose reasons, duplicated schema strings, local filesystem paths
  - has no `disclosure` block: there is nothing to expand into.

A debug-only `--debug-raw` flag on the CLI dumps the uncompacted result
dict; that path is not exposed via MCP.
"""

from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]

MAX_LIST_ITEMS = 8


def present_result(operation: str, result: JsonObject) -> JsonObject:
    if operation == "genomi.parse_source":
        return _present_active_genome_index_parse(result)
    if operation == "pharmacogenomics.review_medication":
        return _present_pgx_medication_review(result)
    if operation == "phenotype.plan_risk_investigation":
        return _present_risk_investigation(result)
    return _present_generic(operation, result)


# --- specialized presenters -----------------------------------------------

def _present_active_genome_index_parse(result: JsonObject) -> JsonObject:
    active = _compact_active_index(result.get("active_genome_index"))
    steps = []
    for step in result.get("steps") or []:
        compact_step = _select(step, ("name", "status", "reason"))
        step_result = step.get("result")
        if isinstance(step_result, dict):
            compact_step["result"] = _select(
                step_result,
                ("status", "stats", "schema_version", "include_reference", "header"),
            )
        steps.append(compact_step)
    payload: JsonObject = {
        "status": result.get("status"),
        "workflow_area": result.get("workflow_area"),
        "source_format": result.get("source_format"),
        "source_kind": result.get("source_kind"),
        "annotation_scope": result.get("annotation_scope"),
        "sample_slug": result.get("sample_slug"),
        "genome_build": result.get("genome_build"),
        "defaults_applied": result.get("defaults_applied"),
        "active_genome_index": active,
        "steps": steps,
        "warnings": result.get("warnings") or [],
        "digitization_contract": result.get("digitization_contract"),
    }
    return _drop_none(payload)


def _present_pgx_medication_review(result: JsonObject) -> JsonObject:
    sample_evidence = result.get("sample_evidence") if isinstance(result.get("sample_evidence"), dict) else {}
    public_evidence = result.get("public_evidence") if isinstance(result.get("public_evidence"), dict) else {}
    target_inventory = result.get("target_inventory") if isinstance(result.get("target_inventory"), dict) else {}
    answer_support = result.get("answer_support") if isinstance(result.get("answer_support"), dict) else {}
    envelope = _compact_envelope(result.get("evidence_envelope"))
    payload: JsonObject = {}
    headline = envelope.get("headline") if isinstance(envelope, dict) else None
    if headline:
        payload["headline"] = headline
    if envelope:
        payload["evidence_envelope"] = envelope
    payload.update({
        "ok": result.get("ok"),
        "status": result.get("status"),
        "query": result.get("query"),
        "defaults_applied": result.get("defaults_applied"),
        "evidence_state": _compact_generic_value(result.get("evidence_state")),
        "interpretation_readiness": _compact_generic_value(result.get("interpretation_readiness")),
        "pgx_evidence_scope": _compact_generic_value(result.get("pgx_evidence_scope")),
        "target_inventory": _select(
            target_inventory,
            (
                "drug",
                "selected_gene",
                "rsid_targets",
                "pharmacogene_targets",
                "implemented_marker_definition_genes",
                "genotype_support_loci",
                "public_evidence_count",
                "active_genome_index",
            ),
        ),
        "public_evidence": _compact_public_evidence(public_evidence),
        "sample_evidence": _compact_sample_evidence(sample_evidence),
        "answer_support": _compact_answer_support(answer_support),
        "unanswered_answer_components": result.get("unanswered_answer_components") or [],
    })
    return _drop_none(payload)


def _present_risk_investigation(result: JsonObject) -> JsonObject:
    evidence = result.get("evidence_view") if isinstance(result.get("evidence_view"), dict) else {}
    source_plan = result.get("source_plan") if isinstance(result.get("source_plan"), dict) else {}
    active_evidence = result.get("active_genome_index_evidence") if isinstance(result.get("active_genome_index_evidence"), dict) else {}
    envelope = _compact_envelope(result.get("evidence_envelope"))
    payload: JsonObject = {}
    headline = envelope.get("headline") if isinstance(envelope, dict) else None
    if headline:
        payload["headline"] = headline
    if envelope:
        payload["evidence_envelope"] = envelope
    payload.update({
        "status": result.get("status"),
        "context_scope": result.get("context_scope"),
        "target": result.get("target"),
        "defaults_applied": result.get("defaults_applied"),
        "source_plan": _compact_risk_source_plan(source_plan),
        "stored_research_summary": (result.get("stored_research") or {}).get("summary") if isinstance(result.get("stored_research"), dict) else None,
        "gene_context_summary": (result.get("gene_context") or {}).get("summary") if isinstance(result.get("gene_context"), dict) else None,
        "active_genome_index_evidence": _compact_active_risk_evidence(active_evidence),
        "review_target_summary": _compact_review_target_summary(evidence.get("coverage") if isinstance(evidence, dict) else {}),
        "evidence_view": _compact_evidence_view(evidence),
        "next_actions": result.get("next_actions"),
        "warnings": result.get("warnings") or [],
    })
    return _drop_none(payload)


def _present_generic(operation: str, result: JsonObject) -> JsonObject:
    body = _compact_generic_value(result)
    if not isinstance(body, dict):
        return {"result": body}
    envelope = _compact_envelope(result.get("evidence_envelope")) if isinstance(result, dict) else None
    headline = envelope.get("headline") if isinstance(envelope, dict) else None
    body.pop("evidence_envelope", None)
    ordered: JsonObject = {}
    if headline:
        ordered["headline"] = headline
    if envelope:
        ordered["evidence_envelope"] = envelope
    # Compact library inventory rows when present (genomi.check_libraries).
    libs = body.get("libraries")
    if isinstance(libs, list):
        body["libraries"] = [
            _select(item, ("library", "title", "installed", "status", "size_class"))
            for item in libs if isinstance(item, dict)
        ]
    for key, value in body.items():
        ordered[key] = value
    return ordered


# --- compaction helpers ---------------------------------------------------

def _compact_envelope(envelope: object) -> JsonObject | None:
    if not isinstance(envelope, dict):
        return None
    order = (
        "operation",
        "headline",
        "finding_state",
        "answer_readiness",
        "guidance",
        "negative_inference",
        "next_actions",
        "personal_context",
        "coverage",
        "observations",
        "query_scope",
        "notes",
    )
    ordered: JsonObject = {}
    for key in order:
        if key not in envelope:
            continue
        value = envelope[key]
        if isinstance(value, list) and not value:
            continue
        if isinstance(value, dict) and key == "personal_context":
            if not value.get("uses_personal_dna") and len(value) <= 1:
                continue
            key = "active_genome_index_context"
            value = {
                **{k: v for k, v in value.items() if k != "uses_personal_dna"},
                "used": bool(value.get("uses_personal_dna")),
            }
        if isinstance(value, dict) and key == "negative_inference":
            value = {k: v for k, v in value.items() if k != "reason"}
            if not value.get("requires"):
                value.pop("requires", None)
            if not value.get("satisfied"):
                value.pop("satisfied", None)
        if isinstance(value, dict) and key == "coverage":
            value = {k: v for k, v in value.items() if v}
            if not value:
                continue
        if isinstance(value, dict) and key == "observations":
            value = {k: v for k, v in value.items() if v not in (None, 0, "", [], {})}
            if not value:
                continue
        if isinstance(value, dict) and key == "query_scope":
            value = {k: v for k, v in value.items() if v not in (None, "", [], False)}
            if not value:
                continue
        ordered[key] = value
    return ordered


def _compact_risk_source_plan(source_plan: JsonObject) -> JsonObject:
    compact = _select(source_plan, ("status", "investigation_type", "safe_external_targets", "write_back_rule"))
    compact["sources"] = [
        _select(source, ("source_id", "title", "query_mode", "best_for", "official_url"))
        for source in (source_plan.get("source_order") or [])[:MAX_LIST_ITEMS]
        if isinstance(source, dict)
    ]
    compact["review_steps"] = source_plan.get("review_steps") or []
    return compact


def _compact_review_target_summary(summary: object) -> JsonObject:
    if not isinstance(summary, dict):
        return {}
    compact = _select(
        summary,
        (
            "candidate_count",
            "ranked_candidate_count",
            "top_observed_support_level",
            "answerability_counts",
        ),
    )
    if "top_observed_candidate" in summary:
        compact["top_observed_review_target"] = summary["top_observed_candidate"]
    return compact


def _compact_evidence_view(evidence: JsonObject) -> JsonObject:
    compact = _select(evidence, ("agent_decision_required", "top_observed_candidate", "coverage", "warnings"))
    compact["rankings"] = [
        _select(candidate, ("candidate_id", "candidate_type", "rank", "score", "evidence_support_level", "answerability", "best_evidence_lane"))
        for candidate in (evidence.get("rankings") or [])[:MAX_LIST_ITEMS]
        if isinstance(candidate, dict)
    ]
    return compact


def _compact_active_risk_evidence(active_evidence: JsonObject) -> JsonObject:
    compact = _select(
        active_evidence,
        ("status", "selection", "summary", "result_state"),
    )
    compact["candidate_summaries"] = [
        _select(candidate, ("candidate_id", "variant", "genes", "conditions", "evidence_groups", "target_match_status"))
        for candidate in (active_evidence.get("candidate_summaries") or [])[:MAX_LIST_ITEMS]
        if isinstance(candidate, dict)
    ]
    return compact


def _compact_public_evidence(public_evidence: JsonObject) -> JsonObject:
    source_availability = public_evidence.get("source_availability")
    compact = _select(
        public_evidence,
        (
            "source_evidence_count",
            "live_public_evidence_count",
            "stored_source_evidence_count",
        ),
    )
    if isinstance(source_availability, dict):
        compact["source_availability"] = _select(
            source_availability,
            (
                "status",
                "live_public_evidence_count",
                "stored_source_evidence_count",
                "unavailable_source_count",
                "warning_source_count",
                "stored_research_status",
            ),
        )
        compact["sources"] = [
            _select(item, ("source_id", "status", "availability", "evidence_count", "warning_count"))
            for item in source_availability.get("sources") or []
        ]
    for key in ("clinpgx", "pgxdb", "fda_pgx"):
        value = public_evidence.get(key)
        if isinstance(value, dict):
            compact[key] = _compact_source_result(value)
    return compact


def _compact_source_result(value: JsonObject) -> JsonObject:
    compact = _select(value, ("ok", "status", "summary", "warnings", "clinical_verification"))
    for key in ("guideline_annotations", "clinical_annotations", "label_annotations", "pgx_records", "rows"):
        records = value.get(key)
        if isinstance(records, list):
            compact[key] = [_truncate_record(item) for item in records[:MAX_LIST_ITEMS]]
            if len(records) > MAX_LIST_ITEMS:
                compact[f"{key}_omitted_count"] = len(records) - MAX_LIST_ITEMS
    return compact


def _compact_sample_evidence(sample_evidence: JsonObject) -> JsonObject:
    compact = _select(
        sample_evidence,
        (
            "sample_context_requested",
            "rsid_targets",
            "lookup_count",
            "sample_match_count",
            "stored_sample_evidence_count",
            "user_provided_sample_evidence_count",
            "total_sample_evidence_count",
            "technical_support_count",
            "sequencing_sample_match_count",
            "active_genome_index_context_available",
            "star_gene_targets",
            "star_allele_call_count",
            "star_marker_match_count",
        ),
    )
    compact["variant_matches"] = _variant_match_summaries(sample_evidence.get("variant_lookups") or [])
    compact["star_allele_calls"] = _star_call_summaries(sample_evidence.get("star_allele_calls") or [])
    user_evidence = sample_evidence.get("user_provided_sample_evidence") or []
    if user_evidence:
        compact["user_provided_sample_evidence"] = [_truncate_record(item) for item in user_evidence[:MAX_LIST_ITEMS]]
    return compact


def _compact_answer_support(answer_support: JsonObject) -> JsonObject:
    compact = _select(
        answer_support,
        (
            "status",
            "public_signal_count",
            "sample_signal_count",
            "technical_sample_support",
            "clinical_boundary",
        ),
    )
    compact["matched_variant_associations"] = [
        _truncate_record(item)
        for item in (answer_support.get("matched_variant_associations") or [])[:MAX_LIST_ITEMS]
    ]
    compact["star_diplotype_summaries"] = [
        _truncate_record(item)
        for item in (answer_support.get("star_diplotype_summaries") or [])[:MAX_LIST_ITEMS]
    ]
    compact["source_recommendation_summaries"] = [
        _truncate_record(item)
        for item in (answer_support.get("source_recommendation_summaries") or [])[:MAX_LIST_ITEMS]
    ]
    return compact


def _variant_match_summaries(lookups: list[object]) -> list[JsonObject]:
    matches = []
    for lookup in lookups:
        if not isinstance(lookup, dict):
            continue
        for match in lookup.get("sample_context", {}).get("matches") or []:
            matches.append(
                _select(
                    match,
                    (
                        "target",
                        "rsid",
                        "chrom",
                        "pos",
                        "ref",
                        "alt",
                        "genotype",
                        "depth",
                        "genotype_quality",
                        "filter",
                        "source_format",
                        "source_kind",
                        "selection",
                    ),
                )
            )
    return [_rename_agi_source_metadata(match) for match in matches[:MAX_LIST_ITEMS]]


def _star_call_summaries(calls: list[object]) -> list[JsonObject]:
    summaries = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        summary = _select(call, ("ok", "status", "gene", "genome_build", "definition_set", "definition_scope", "called_star_alleles", "diplotype", "warnings"))
        marker_calls = []
        for marker in call.get("marker_calls") or []:
            marker_calls.append(
                _select(
                    marker,
                    (
                        "star_allele",
                        "rsid",
                        "effect_allele",
                        "reference_allele",
                        "function",
                        "evidence_status",
                        "effect_allele_count",
                        "sample_calls",
                    ),
                )
            )
        summary["marker_calls"] = marker_calls[:MAX_LIST_ITEMS]
        summaries.append(summary)
    return summaries[:MAX_LIST_ITEMS]


def _compact_generic_value(value: object, *, depth: int = 0) -> object:
    if depth > 4 and isinstance(value, dict):
        return "[omitted_nested_value]"
    if depth > 4 and isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            compacted = [_compact_scalar_value(item) for item in value[:MAX_LIST_ITEMS]]
            if len(value) > MAX_LIST_ITEMS:
                compacted.append({"omitted_count": len(value) - MAX_LIST_ITEMS})
            return compacted
        if all(_is_shallow_scalar_dict(item) for item in value):
            compacted = [_compact_shallow_scalar_dict(item) for item in value[:MAX_LIST_ITEMS]]
            if len(value) > MAX_LIST_ITEMS:
                compacted.append({"omitted_count": len(value) - MAX_LIST_ITEMS})
            return compacted
        return "[omitted_nested_value]"
    if isinstance(value, dict):
        compact: JsonObject = {}
        for key, item in value.items():
            if _omit_key(str(key)):
                continue
            compact[str(key)] = _compact_generic_value(item, depth=depth + 1)
        return compact
    if isinstance(value, list):
        if all(_is_shallow_scalar_dict(item) for item in value):
            compacted = [_compact_shallow_scalar_dict(item) for item in value[:MAX_LIST_ITEMS]]
            if len(value) > MAX_LIST_ITEMS:
                compacted.append({"omitted_count": len(value) - MAX_LIST_ITEMS})
            return compacted
        compacted = [_compact_generic_value(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            compacted.append({"omitted_count": len(value) - MAX_LIST_ITEMS})
        return compacted
    return _compact_scalar_value(value)


def _compact_scalar_value(value: object) -> object:
    if isinstance(value, str) and _looks_like_local_path(value):
        return "[omitted_local_path]"
    return value


def _is_shallow_scalar_dict(value: object) -> bool:
    return isinstance(value, dict) and all(not isinstance(item, (dict, list)) for item in value.values())


def _compact_shallow_scalar_dict(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _compact_scalar_value(item)
        for key, item in value.items()
        if not _omit_key(str(key))
    }


def _compact_active_index(value: object) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    compact = _select(
        value,
        (
            "agi_id",
            "sample_slug",
            "status",
            "source_format",
            "source_kind",
            "source_member",
            "genome_build",
            "digitized",
            "availability",
            "intake_source",
        ),
    )
    return _rename_agi_source_metadata(compact)


def _truncate_record(value: object) -> object:
    if not isinstance(value, dict):
        return value
    return _compact_generic_value(value, depth=1)


def _select(value: object, keys: tuple[str, ...]) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def _omit_key(key: str) -> bool:
    lowered = key.lower()
    if lowered == "schema":
        return True
    if lowered in {"raw", "raw_json", "raw_calls", "external_calls", "record_research_payloads"}:
        return True
    if lowered in {
        "outputs",
        "project_dir",
        "work_dir",
        "evidence_dir",
        "reference_dir",
        "context_file",
        "registry_file",
        "shared_evidence_db",
        "workspace",
    }:
        return True
    return bool(lowered.endswith("_path") or lowered.endswith("_dir") or lowered.endswith("_file") or lowered.endswith("_db") or lowered in {"output", "path", "db", "manifest_path"})


def _looks_like_local_path(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(("/", "~/", "$GENOMI_HOME/"))


def _drop_none(value: JsonObject) -> JsonObject:
    return {key: item for key, item in value.items() if item is not None}


def _rename_agi_source_metadata(value: JsonObject) -> JsonObject:
    renamed = dict(value)
    for old_key, new_key in (
        ("source_format", "agi_source_format"),
        ("source_kind", "agi_source_kind"),
        ("source_member", "agi_source_member"),
    ):
        if old_key in renamed:
            renamed[new_key] = renamed.pop(old_key)
    return renamed
