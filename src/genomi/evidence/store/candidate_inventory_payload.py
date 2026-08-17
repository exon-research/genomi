"""Assembly of one bounded ClinVar candidate-inventory payload.

`candidates.py` owns turning ClinVar match records into candidates. This
module owns the shape those candidates are handed back in: which candidates a
host selection keeps, the bounded window that is returned, the evidence view
built over that window, and the window state the host needs to reach the rest.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ...runtime.handoff import evidence_context
from .. import envelope as _env
from ..candidate_evidence import (
    DIRECT_SOURCE_MATCH,
    NEGATIVE_OR_CONFLICTING_EVIDENCE,
    answerability_for_lane,
    apply_evidence_view,
    evidence_support_level_for_score,
    evidence_view,
    lane,
)
from ..task_profiles import CLINVAR_CANDIDATE_SCAN

from .candidate_groups import build_candidate_review_groups
from .candidate_scoring import (
    _available_evidence_group_summary,
    _candidate_bucket_summary,
    _candidate_is_selected,
    _ordered_bucket_counts,
)
from .clinvar_match_provenance import (
    MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE,
    MATCH_BASIS_LIFTOVER_EXACT_ALLELE,
    MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT,
    MATCH_BASIS_MULTIALLELIC_ALT,
)
from .constants import (
    CANDIDATE_EVIDENCE_GROUPS,
    CANDIDATE_RULE_SET_VERSION,
)

# A ClinVar candidate record carries its full variant, provenance, population
# and genotype-support evidence, so an unbounded inventory cannot be handed to
# a host agent in one tool result. The operation returns a bounded window and
# materializes the wider inventory to its output file; the host reaches the
# rest through offset/limit or by narrowing with gene/evidence_groups.
DEFAULT_RETURNED_CANDIDATE_LIMIT = 5
MAX_RETURNED_CANDIDATE_LIMIT = 100
MATERIALIZED_CANDIDATE_LIMIT = 200

# Row collections that `apply_evidence_view` also publishes at the top level.
# For candidate rows this large they are a verbatim second copy of
# `evidence_view`, so the ClinVar inventory keeps only the canonical one.
_DUPLICATED_EVIDENCE_VIEW_ROW_COLLECTIONS = (
    "candidate_matrix",
    "rankings",
    "decision_evidence",
    "source_local_ordering",
    "top_observed",
)


def _host_selected_candidates(
    materialized_candidates: list[dict[str, Any]],
    *,
    selected_evidence_groups: list[str],
    selected_gene: str | None,
) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in materialized_candidates
        if _candidate_is_selected(candidate, selected_evidence_groups=selected_evidence_groups)
        and (selected_gene is None or _candidate_has_gene(candidate, selected_gene))
    ]


def _inventory_selection(
    *,
    genome_build: str,
    population_source: str | None,
    population: str | None,
    selected_gene: str | None,
    selected_evidence_groups: list[str],
    default_groups_applied: bool,
    available_evidence_group_counts: Counter[str],
) -> dict[str, Any]:
    return {
        "genome_build": genome_build,
        "population_source": population_source,
        "population": population,
        "gene": selected_gene,
        "selected_evidence_groups": selected_evidence_groups,
        "default_groups_applied": default_groups_applied,
        "not_selected_evidence_groups": [
            group
            for group, _description in CANDIDATE_EVIDENCE_GROUPS
            if group not in set(selected_evidence_groups)
            and available_evidence_group_counts[group]
        ],
    }


def _build_inventory_payload(
    *,
    emitted_candidates: list[dict[str, Any]],
    selected_candidates: list[dict[str, Any]],
    available_evidence_group_counts: Counter[str],
    selection: dict[str, Any],
    match_totals: dict[str, Any],
    matches_path: Path,
    output: Path | None,
    genome_build: str,
    population_source: str | None,
    population: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Build one candidate-inventory payload over a bounded candidate window.

    The same shape is written to ``output`` for the materialized inventory and
    returned to the caller for the requested window, so a host agent reads the
    window it asked for and the work-trace counts stay identical in both.
    """

    total_selected = len(selected_candidates)
    tag_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    for candidate in selected_candidates:
        tag_counts.update(candidate["tags"])
        bucket_counts.update(candidate["buckets"])
    candidate_review_groups = build_candidate_review_groups(selected_candidates)
    returned_window = _returned_candidate_window(
        offset=offset,
        limit=limit,
        returned=len(emitted_candidates),
        total_selected=total_selected,
        selection=selection,
    )
    candidate_evidence = _clinvar_candidate_evidence_view(
        emitted_candidates,
        genome_build=genome_build,
        selected_evidence_groups=list(selection["selected_evidence_groups"]),
        population_source=population_source,
        population=population,
    )
    payload = {
        "status": "completed",
        "input": str(matches_path),
        "output": str(output) if output is not None else None,
        "rule_set_version": CANDIDATE_RULE_SET_VERSION,
        "action": {
            "name": "build-candidate-inventory",
            "purpose": "Build source-derived candidate inventory from provenance-marked ClinVar matches so the agent can inspect evidence lenses and decide what facts are missing for the user's question.",
            "result_type": "deterministic candidate inventory with a bounded candidate window, all available ClinVar evidence lenses, bucket summaries, and evidence-context guidance",
            "scope": [
                "builds source-derived candidate evidence lenses",
                "keeps user-intent selection with the host agent",
                "feeds clinical interpretation and current source review performed by later tools",
            ],
        },
        "selection": {**selection, "limit": limit, "offset": offset},
        "returned_window": returned_window,
        "available_evidence_groups": _available_evidence_group_summary(available_evidence_group_counts),
        "summary": {
            **match_totals,
            "selected_candidate_variants": total_selected,
            "emitted_candidate_variants": len(emitted_candidates),
            "truncated": bool(returned_window["has_more"]),
            "tag_counts": tag_counts.most_common(),
            "bucket_counts": _ordered_bucket_counts(bucket_counts),
        },
        "candidate_buckets": _candidate_bucket_summary(selected_candidates, emitted_candidates),
        "evidence_options": _candidate_inventory_options(
            list(selection["selected_evidence_groups"]),
            available_evidence_group_counts,
            emitted_candidates,
        ),
        "evidence_context": evidence_context(
            "research",
            reason="Candidate inventory is static evidence; the agent chooses the target and continues in intent research when source context is needed.",
            commands=[
                "genomi call variant.gather_allele_context --params '{\"db\":\"<evidence.sqlite>\",\"matches\":\"<clinvar.matches.jsonl>\",\"chrom\":\"<chrom>\",\"pos\":123,\"ref\":\"<ref>\",\"alt\":\"<alt>\"}'",
                "genomi call research.build_target_packet --params '{\"db\":\"<evidence.sqlite>\",\"target_type\":\"topic\",\"topic\":\"<topic>\"}'",
            ],
        ),
        "notes": [
            "This command builds a deterministic candidate inventory for host-agent clinical-context interpretation.",
            "User questions are open-ended and belong to the agent's reasoning; evidence lenses are source-derived filters, not intent presets.",
            "candidate_buckets are evidence summary groups, not diagnoses.",
            "clinvar_triage_score is only a ClinVar evidence-strength display aid, not a clinical priority score.",
            "Use match_basis_counts and each candidate's match_provenance before treating a ClinVar hit as an exact VCF allele observation.",
            "summary.total_exact_match_variants counts exact allele provenance only; use summary.total_match_variants for all provenance-marked matches.",
            "Population frequency tags are facts for the agent to interpret against user intent; clinvar_triage_score remains a ClinVar evidence-strength display aid.",
            "Missing population evidence means run a population evidence tool if the candidate is worth investigating.",
        ],
        "candidate_inventory": emitted_candidates,
        "candidate_review_groups": candidate_review_groups,
    }
    apply_evidence_view(
        payload,
        candidate_evidence,
        operation="clinvar.scan_candidates",
        personal_context=_env._personal_context(uses_personal_dna=True, source="clinvar_matches"),
    )
    # A ClinVar candidate carries its whole variant, provenance, population and
    # genotype-support evidence, so lifting the evidence-view row collections to
    # the top level serialized every candidate a second time. `evidence_view`
    # keeps the canonical rows; `candidate_inventory` keeps the source records.
    for duplicated_row_collection in _DUPLICATED_EVIDENCE_VIEW_ROW_COLLECTIONS:
        payload.pop(duplicated_row_collection, None)
    _apply_returned_window_envelope(payload, returned_window)
    return payload


def _returned_candidate_window(
    *,
    offset: int,
    limit: int,
    returned: int,
    total_selected: int,
    selection: dict[str, Any],
) -> dict[str, Any]:
    has_more = offset + returned < total_selected
    window: dict[str, Any] = {
        "offset": offset,
        "limit": limit,
        "returned_candidate_variants": returned,
        "total_selected_candidate_variants": total_selected,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
        "select_remaining_with": {
            "operation": "clinvar.scan_candidates",
            "offset": offset + returned if has_more else None,
            "limit": limit,
            "gene": selection.get("gene"),
            "evidence_groups": list(selection["selected_evidence_groups"]),
        },
    }
    return window


def _apply_returned_window_envelope(payload: dict[str, Any], returned_window: dict[str, Any]) -> None:
    envelope = payload.get("evidence_envelope")
    if not isinstance(envelope, dict):
        return
    if not returned_window["has_more"]:
        return
    guidance = envelope.get("guidance")
    if isinstance(guidance, list):
        guidance.append(
            "bounded_candidate_window_returned:request_next_offset_or_narrow_by_gene_or_evidence_group"
        )
    next_actions = envelope.get("next_actions")
    if isinstance(next_actions, list):
        next_actions.append(
            {
                "action": "request_next_candidate_window",
                "operation": "clinvar.scan_candidates",
                "offset": returned_window["next_offset"],
                "limit": returned_window["limit"],
                "returned_candidate_variants": returned_window["returned_candidate_variants"],
                "total_selected_candidate_variants": returned_window["total_selected_candidate_variants"],
                "narrow_with_parameters": ["gene", "evidence_groups"],
            }
        )


def _returned_inventory_from_materialized(
    materialized_payload: dict[str, Any],
    *,
    genome_build: str,
    population_source: str | None,
    population: str | None,
    selected_evidence_groups: list[str],
    selected_gene: str | None,
    default_groups_applied: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Rebuild the bounded returned payload from a cached materialized inventory."""

    materialized_candidates = [
        candidate
        for candidate in materialized_payload.get("candidate_inventory") or []
        if isinstance(candidate, dict)
    ]
    summary = materialized_payload.get("summary") if isinstance(materialized_payload.get("summary"), dict) else {}
    match_totals = {
        key: value
        for key, value in summary.items()
        if key
        not in {
            "emitted_candidate_variants",
            "truncated",
            "selected_candidate_variants",
            "tag_counts",
            "bucket_counts",
        }
    }
    available_evidence_group_counts: Counter[str] = Counter()
    for group, count in summary.get("available_evidence_group_counts") or []:
        available_evidence_group_counts[str(group)] = int(count)
    candidates = _host_selected_candidates(
        materialized_candidates,
        selected_evidence_groups=selected_evidence_groups,
        selected_gene=selected_gene,
    )
    return _build_inventory_payload(
        emitted_candidates=candidates[offset : offset + limit],
        selected_candidates=candidates,
        available_evidence_group_counts=available_evidence_group_counts,
        selection=_inventory_selection(
            genome_build=genome_build,
            population_source=population_source,
            population=population,
            selected_gene=selected_gene,
            selected_evidence_groups=selected_evidence_groups,
            default_groups_applied=default_groups_applied,
            available_evidence_group_counts=available_evidence_group_counts,
        ),
        match_totals=match_totals,
        matches_path=Path(str(materialized_payload.get("input") or "")),
        output=Path(str(materialized_payload["output"])) if materialized_payload.get("output") else None,
        genome_build=genome_build,
        population_source=population_source,
        population=population,
        offset=offset,
        limit=limit,
    )


def _candidate_has_gene(candidate: dict[str, Any], gene: str) -> bool:
    return any(str(item).strip().upper() == gene for item in candidate.get("genes") or [])


def _clinvar_candidate_evidence_view(
    candidates: list[dict[str, Any]],
    *,
    genome_build: str,
    selected_evidence_groups: list[str],
    population_source: str | None,
    population: str | None,
) -> dict[str, Any]:
    matrix = [_clinvar_candidate_matrix_row(candidate, rank=index + 1) for index, candidate in enumerate(candidates)]
    selected = matrix[0] if matrix else None
    decision_policy = {
        "policy_id": "clinvar_candidate_scan_v1",
        "ranking_order": [
            "ClinVar evidence group selected for review",
            "ClinVar triage evidence strength",
            "variant coordinate for deterministic tie-breaking",
        ],
        "rule": (
            "Provenance-marked ClinVar/sample matches create direct candidate evidence lanes for review. "
            "The lane ranks review targets; it is not a diagnosis or clinical-priority score."
        ),
    }
    warnings = []
    if not matrix:
        warnings.append("no_clinvar_candidate_matches:selected_evidence_groups_empty")
    return evidence_view(
        task_profile=CLINVAR_CANDIDATE_SCAN,
        query={
            "genome_build": genome_build,
            "selected_evidence_groups": selected_evidence_groups,
            "population_source": population_source,
            "population": population,
        },
        candidate_matrix=matrix,
        top_observed_candidate=selected,
        evidence_policy=decision_policy,
        source_local_ordering={
            "scope": "source_local_evidence_ordering",
            "valid_for": "source_local_candidate_ranking",
            "not_valid_for": "host_agent_answer_selection",
            "ordered_candidate_ids": [str(row["candidate_id"]) for row in matrix],
        },
        warnings=warnings,
    )


def _clinvar_candidate_matrix_row(candidate: dict[str, Any], *, rank: int) -> dict[str, Any]:
    clinvar = candidate.get("clinvar") or {}
    variant = candidate.get("variant") or {}
    candidate_id = _variant_candidate_id(variant)
    score = min(1.0, max(0.0, float(candidate.get("clinvar_triage_score") or 0) / 120.0))
    best_lane = DIRECT_SOURCE_MATCH if clinvar.get("clinvar_ids") else NEGATIVE_OR_CONFLICTING_EVIDENCE
    # Only the lane this candidate actually populates is carried. The eight
    # absent lanes are constant filler that every downstream reader already
    # discards, and they repeat in every ranking, ordering and decision row.
    lanes = {
        best_lane: lane(
            best_lane,
            status="present",
            score=score,
            source="ClinVar",
            matched_text=_clinvar_candidate_matched_text(candidate),
            source_id=", ".join(str(item) for item in (clinvar.get("clinvar_ids") or [])[:5]) or None,
            note=_clinvar_match_lane_note(candidate),
        )
    }
    return {
        "candidate_id": candidate_id,
        "candidate_type": "variant",
        "rank": rank,
        "score": score,
        "evidence_support_level": evidence_support_level_for_score(score),
        "answerability": answerability_for_lane(best_lane),
        "best_evidence_lane": best_lane,
        "evidence_lanes": lanes,
        "supporting_evidence": [_clinvar_matrix_supporting_evidence(candidate, candidate_id)],
        "counter_evidence": _clinvar_counter_evidence(candidate),
        "why_not_selected": [] if rank == 1 else ["Lower deterministic ClinVar candidate triage rank than the selected review target."],
    }


def _clinvar_matrix_supporting_evidence(candidate: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    """Decisive ClinVar facts for one matrix row, keyed to its inventory record.

    The full population, genotype-support and provenance evidence for this
    candidate is carried once, in the `candidate_inventory` record with the same
    `candidate_id`. Repeating it in every ranking, ordering and decision-evidence
    row is what made a whole-exome scan unreadable for a host agent.
    """

    clinvar = candidate.get("clinvar") or {}
    population_evidence = candidate.get("population_evidence") or {}
    genotype_support = candidate.get("genotype_support") or {}
    match_provenance = candidate.get("match_provenance") or {}
    return {
        "source": "ClinVar",
        "candidate_id": candidate_id,
        "evidence_detail_in": "candidate_inventory",
        "clinvar_ids": clinvar.get("clinvar_ids") or [],
        "clinical_significance_counts": clinvar.get("clinical_significance_counts") or [],
        "review_status_counts": clinvar.get("review_status_counts") or [],
        "conditions": clinvar.get("conditions") or [],
        "genes": candidate.get("genes") or [],
        "population_evidence_status": population_evidence.get("status"),
        "genotype_support_status": genotype_support.get("support_status"),
        "primary_match_basis": match_provenance.get("primary_match_basis"),
        "match_basis_counts": clinvar.get("match_basis_counts") or [],
    }


def _variant_candidate_id(variant: dict[str, Any]) -> str:
    return "variant:{chrom}-{pos}-{ref}-{alt}".format(
        chrom=variant.get("chrom"),
        pos=variant.get("pos"),
        ref=variant.get("ref"),
        alt=variant.get("alt"),
    )


def _clinvar_match_lane_note(candidate: dict[str, Any]) -> str:
    match_bases = {
        str(basis)
        for basis, _count in ((candidate.get("match_provenance") or {}).get("match_basis_counts") or [])
    }
    if MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE in match_bases:
        return "candidate includes consumer-array allele inference from an observed genotype string; do not describe it as an exact VCF allele match"
    if MATCH_BASIS_LIFTOVER_EXACT_ALLELE in match_bases:
        return "candidate is an exact sample allele match after liftover to the ClinVar cache build"
    if MATCH_BASIS_LIFTOVER_MULTIALLELIC_ALT in match_bases:
        return "candidate is a selected alternate allele from a multiallelic sample record after liftover"
    if MATCH_BASIS_MULTIALLELIC_ALT in match_bases:
        return "candidate is a selected alternate allele from a multiallelic sample record"
    return "candidate is an exact sample allele match to ClinVar records"


def _clinvar_candidate_matched_text(candidate: dict[str, Any]) -> str:
    clinvar = candidate.get("clinvar") or {}
    significance = ", ".join(f"{label}:{count}" for label, count in (clinvar.get("clinical_significance_counts") or [])[:3])
    genes = ", ".join(candidate.get("genes") or [])
    variant = candidate.get("variant") or {}
    return f"{_variant_candidate_id(variant)} {genes} {significance}".strip()


def _clinvar_counter_evidence(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    counter: list[dict[str, Any]] = []
    tags = set(candidate.get("tags") or [])
    if "clinvar_conflicting" in tags or "review_status_conflicting" in tags:
        counter.append({"type": "conflicting_classification", "note": "ClinVar records include conflicting classification context."})
    if "population_frequency_common" in tags or "population_homozygotes_present" in tags:
        counter.append({"type": "population_tension", "note": "Public population evidence may downgrade disease-style interpretation."})
    if "clinvar_benign_or_likely_benign" in tags:
        counter.append({"type": "benign_classification", "note": "ClinVar includes benign or likely benign classification context."})
    return counter


def _candidate_inventory_options(
    selected_evidence_groups: list[str],
    available_evidence_group_counts: Counter[str],
    emitted_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_options: list[dict[str, Any]] = []
    not_selected = [
        group
        for group, _description in CANDIDATE_EVIDENCE_GROUPS
        if group not in set(selected_evidence_groups) and available_evidence_group_counts[group]
    ]
    if not_selected:
        evidence_options.append(
            {
                "component": "candidate_inventory_lens",
                "state": "additional_source_groups_available",
                "available_operation": "clinvar.scan_candidates",
                "available_values": not_selected,
                "evidence_context": evidence_context(
                    "static",
                    reason="Rebuilding a source-derived candidate inventory is deterministic static annotation work.",
                ),
            }
        )
    if emitted_candidates:
        first = emitted_candidates[0]["variant"]
        options = ["--fetch-missing-gnomad"]
        if emitted_candidates[0].get("population_evidence", {}).get("status") == "present":
            options = []
        evidence_options.append(
            {
                "component": "selected_candidate_evidence",
                "state": "available_for_target_scoped_lookup",
                "available_operation": "variant.gather_allele_context",
                "target": {"chrom": first.get("chrom"), "pos": first.get("pos"), "ref": first.get("ref"), "alt": first.get("alt")},
                "options": options,
                "evidence_context": evidence_context(
                    "research",
                    reason="Selected candidate alleles move from static inventory into target-scoped research gathering.",
                ),
            }
        )
    if emitted_candidates:
        evidence_options.append(
            {
                "component": "selected_candidate_reviewed_source_context",
                "state": "may_be_needed_for_interpretation",
                "available_operations": ["research.record", "variant.gather_allele_context", "variant.gather_gene_context"],
                "evidence_context": evidence_context(
                    "research",
                    reason="Focused Journal source-review findings must be stored before candidate interpretation or reporting.",
                ),
            }
        )
    elif not not_selected:
        evidence_options.append(
            {
                "component": "candidate_inventory",
                "state": "no_candidates_selected",
                "evidence_boundary": "No candidates were selected in the chosen ClinVar match inventory lenses.",
                "evidence_context": evidence_context(
                    "research",
                    reason="No static candidates were selected; any further answer or broader target decision belongs in intent research.",
                ),
            }
        )
    return evidence_options
