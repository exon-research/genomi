"""Domain-owned compilation of reviewable portal context candidates.

The browser asks for a candidate and presents the returned manifest.  It does
not parse molecular findings or select a Genomi operation.  This module keeps
that interpretation at the GenomiLab application boundary, where the selected
profile revisions and current Genomi metadata can be validated together.
"""

from __future__ import annotations

from typing import Any, Protocol

from .genomic_scope import GENE_VARIANT_OPERATION
from .models import EXACT_VARIANT_RE, RSID_RE, JsonObject
from .service_errors import LabError


_PORTAL_CONTEXT_FIELDS = frozenset(
    {
        "purpose",
        "use_current_agi",
        "observation_revision_ids",
        "exclude_genome",
    }
)
_REVIEWED_STATES = frozenset(
    {"user_confirmed", "record_confirmed", "clinician_confirmed"}
)
_REPORTED_FINDING_MODALITIES = frozenset(
    {"reported_germline_finding", "reported_somatic_finding"}
)
_PHENOTYPE_CANDIDATE_MODALITIES = frozenset({"phenotype"})


class _PortalContextApplication(Protocol):
    store: Any

    def investigation(self, investigation_id: str) -> JsonObject: ...

    def _current_context(self) -> tuple[JsonObject, str]: ...

    def profile_snapshot_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def _issue_context_candidate_receipt(
        self, candidate: JsonObject, *, action: str
    ) -> JsonObject: ...


class PortalContextApplicationMixin:
    """Compile an exact profile/AGI candidate for the UI to review."""

    def investigation_context_candidate(
        self: _PortalContextApplication,
        investigation_id: str,
        payload: JsonObject,
    ) -> JsonObject:
        if not isinstance(payload, dict):
            raise LabError(
                "invalid_context_selection",
                "The context candidate request must be an object.",
            )
        unexpected = set(payload) - _PORTAL_CONTEXT_FIELDS
        if unexpected:
            raise LabError(
                "invalid_context_selection",
                (
                    "The portal may request a context candidate but cannot select "
                    "a genome operation or construct its genomic scope."
                ),
                http_status=409,
            )
        use_current_agi = payload.get("use_current_agi", False)
        if not isinstance(use_current_agi, bool):
            raise LabError(
                "invalid_context_selection",
                "use_current_agi must be a boolean",
            )
        exclude_genome = payload.get("exclude_genome", False)
        if not isinstance(exclude_genome, bool):
            raise LabError(
                "invalid_context_selection",
                "exclude_genome must be a boolean",
            )

        context, user_id = self._current_context()
        investigation = self.investigation(investigation_id)
        pinned_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        pinned = self.store.get_profile_snapshot(pinned_id) if pinned_id else None
        purpose = payload.get("purpose")
        requested_revisions = payload.get("observation_revision_ids")

        # Renewing the current context reproduces its immutable manifest.  The
        # browser does not reconstruct either the selected records or AGI scope.
        if isinstance(pinned, dict) and not use_current_agi:
            pinned_revisions = list(pinned.get("observation_revision_ids") or [])
            if requested_revisions is not None and (
                not isinstance(requested_revisions, list)
                or any(
                    not isinstance(revision_id, str)
                    for revision_id in requested_revisions
                )
                or len(requested_revisions) != len(set(requested_revisions))
                or sorted(requested_revisions) != sorted(pinned_revisions)
            ):
                raise LabError(
                    "invalid_context_selection",
                    (
                        "Renewal must preserve the pinned profile selection. Use "
                        "Compare latest profile to review a different selection."
                    ),
                    http_status=409,
                )
            candidate = self.profile_snapshot_candidate(
                investigation_id,
                {
                    "purpose": purpose or pinned.get("purpose"),
                    "observation_revision_ids": pinned.get("observation_revision_ids"),
                    "artifact_ids": pinned.get("artifact_ids"),
                    "specimen_ids": pinned.get("specimen_ids"),
                    "assay_ids": pinned.get("assay_ids"),
                    "include_genome": bool(pinned.get("agi_id")),
                    "genomic_scope": pinned.get("genomic_scope"),
                    "use_current_agi": False,
                },
            )
            return self._issue_context_candidate_receipt(candidate, action="renewal")

        if not isinstance(requested_revisions, list) or not requested_revisions:
            raise LabError(
                "invalid_context_selection",
                "Select at least one current molecular-profile observation.",
            )
        current_revision_ids = {
            str(row["observation_revision_id"])
            for row in self.store.list_profile_observations(user_id, current_only=True)
        }
        if any(
            not isinstance(revision_id, str) or revision_id not in current_revision_ids
            for revision_id in requested_revisions
        ):
            raise LabError(
                "invalid_context_selection",
                (
                    "Every selected profile observation must be a current revision "
                    "owned by this Genomi user."
                ),
                http_status=409,
            )

        # First validate and resolve the domain-owned profile selection without
        # genome context.  Its exact selected revisions then drive scope
        # compilation; browser-supplied targets never enter this path.
        base = self.profile_snapshot_candidate(
            investigation_id,
            {
                "purpose": purpose,
                "observation_revision_ids": requested_revisions,
                "include_genome": False,
                "use_current_agi": use_current_agi,
            },
        )
        active = context.get("active_genome_index")
        active_agi_id = str(context.get("active_agi_id") or "")
        active_snapshot_id = (
            str(active.get("agi_snapshot_id") or "") if isinstance(active, dict) else ""
        )
        if exclude_genome or not active_agi_id or not active_snapshot_id:
            return self._issue_context_candidate_receipt(
                base, action="refresh" if pinned else "initial"
            )

        observations = [
            self.store.get_profile_observation(user_id, str(revision_id))
            for revision_id in base.get("observation_revision_ids") or []
        ]
        genomic_scope = _reviewed_profile_genomic_scope(observations)
        if genomic_scope is None:
            return self._issue_context_candidate_receipt(
                base, action="refresh" if pinned else "initial"
            )

        candidate = self.profile_snapshot_candidate(
            investigation_id,
            {
                "purpose": base["purpose"],
                "observation_revision_ids": base["observation_revision_ids"],
                "artifact_ids": base["artifact_ids"],
                "specimen_ids": base["specimen_ids"],
                "assay_ids": base["assay_ids"],
                "include_genome": True,
                "genomic_scope": genomic_scope,
                "use_current_agi": True,
            },
        )
        return self._issue_context_candidate_receipt(
            candidate, action="refresh" if pinned else "initial"
        )

    def compare_investigation_context_candidate(
        self: _PortalContextApplication,
        investigation_id: str,
        payload: JsonObject,
    ) -> JsonObject:
        investigation = self.investigation(investigation_id)
        snapshot_id = str(investigation.get("patient_molecular_snapshot_id") or "")
        if not snapshot_id:
            raise LabError(
                "private_context_required",
                (
                    "Approve this investigation's first molecular context before "
                    "comparing changes."
                ),
                http_status=409,
            )
        candidate = self.investigation_context_candidate(investigation_id, payload)
        try:
            comparison = self.store.compare_profile_snapshot(snapshot_id, candidate)
        except (KeyError, ValueError) as exc:
            raise LabError("invalid_context_comparison", str(exc)) from exc
        return {**comparison, "candidate": candidate}


def _reviewed_profile_genomic_scope(
    observations: list[JsonObject],
) -> JsonObject | None:
    scopes: dict[tuple[object, ...], JsonObject] = {}
    for observation in observations:
        if (
            observation.get("modality") not in _REPORTED_FINDING_MODALITIES
            or observation.get("verification_state") not in _REVIEWED_STATES
            or observation.get("assertion_status") != "present"
        ):
            continue
        reported = str(observation.get("reported_variant") or "").strip()
        scope = _reported_variant_scope(reported)
        if scope is None:
            continue
        key = tuple(
            scope.get(field)
            for field in ("operation", "rsid", "chrom", "pos", "ref", "alt")
        )
        scopes[key] = scope
    if len(scopes) == 1:
        return next(iter(scopes.values()))
    if scopes:
        return None
    if any(
        observation.get("modality") in _PHENOTYPE_CANDIDATE_MODALITIES
        and observation.get("verification_state") in _REVIEWED_STATES
        and observation.get("assertion_status") == "present"
        for observation in observations
    ):
        return {"operation": GENE_VARIANT_OPERATION}
    return None


def _reported_variant_scope(reported: str) -> JsonObject | None:
    if RSID_RE.fullmatch(reported):
        return {"operation": "variant.resolve", "rsid": reported.lower()}
    if not EXACT_VARIANT_RE.fullmatch(reported):
        return None
    allele = reported[3:] if reported[:3].lower() == "chr" else reported
    chrom, raw_pos, ref, alt = allele.split(":")
    if ref.upper() == alt.upper():
        return None
    return {
        "operation": "variant.resolve",
        "chrom": chrom,
        "pos": int(raw_pos),
        "ref": ref.upper(),
        "alt": alt.upper(),
    }


__all__ = ["PortalContextApplicationMixin"]
