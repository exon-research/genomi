"""Patient Molecular Profile observation persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    ASSERTION_AUTHORS,
    ASSERTION_STATUSES,
    COVERAGE_STATES,
    OBSERVATION_LABEL_MAX,
    OBSERVATION_MODALITIES,
    SOURCE_CLASSES,
    SOURCE_LABEL_MAX,
    VERIFICATION_STATES,
    JsonObject,
    choice,
    compact_json,
    normalize_reported_variant,
    optional_text,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


_OBSERVATION_INPUT_FIELDS = frozenset(
    {
        "modality",
        "label",
        "original_wording",
        "assertion_status",
        "verification_state",
        "source_class",
        "assertion_author",
        "reviewed_by",
        "artifact_id",
        "source_identifier",
        "source_locator",
        "coverage_state",
        "assay_scope",
        "detection_limits",
        "normalized_code",
        "value",
        "onset_or_event_time",
        "specimen_id",
        "assay_id",
        "reported_variant",
        "gene",
        "reported_classification",
        "normalization_provenance",
        "logical_observation_id",
        "supersedes_revision_id",
    }
)
_ISSUED_MEDICAL_SOURCE_TYPES = frozenset(
    {"issued_report", "laboratory_report", "pathology_report", "clinical_note"}
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...

    def _require_owned_references(
        self,
        user_id: str,
        *,
        artifact_id: str | None = None,
        specimen_id: str | None = None,
        assay_id: str | None = None,
    ) -> None: ...

    def get_assay(self, user_id: str, assay_id: str) -> JsonObject: ...

    def list_profile_entities(self, user_id: str) -> JsonObject: ...


class HealthRecordStoreMixin:
    """Versioned molecular-profile methods mixed into ``GenomiLabStore``."""

    def add_profile_observation(
        self: _StoreContract, user_id: str, payload: JsonObject
    ) -> JsonObject:
        self._require_workspace(user_id)
        validate_private_payload(payload)
        unexpected = set(payload) - _OBSERVATION_INPUT_FIELDS
        if unexpected:
            raise ValueError(
                "unsupported profile observation fields: "
                + ", ".join(sorted(unexpected))
            )
        modality = choice(payload.get("modality"), "modality", OBSERVATION_MODALITIES)
        label = required_text(
            payload.get("label") or payload.get("original_wording"),
            "label",
            OBSERVATION_LABEL_MAX,
        )
        original_wording = required_text(
            payload.get("original_wording") or label,
            "original_wording",
            OBSERVATION_LABEL_MAX,
        )
        assertion_status = choice(
            payload.get("assertion_status", "present"),
            "assertion_status",
            ASSERTION_STATUSES,
        )
        verification_state = choice(
            payload.get("verification_state", "user_confirmed"),
            "verification_state",
            VERIFICATION_STATES,
        )
        source_class = choice(
            payload.get("source_class", "patient_reported"),
            "source_class",
            SOURCE_CLASSES,
        )
        supersedes = optional_text(
            payload.get("supersedes_revision_id"),
            "supersedes_revision_id",
            SOURCE_LABEL_MAX,
        )
        reviewed_by = optional_text(payload.get("reviewed_by"), "reviewed_by", 200)
        assertion_author_defaults = {
            "patient_reported": "patient",
            "caregiver_reported": "caregiver",
            "issued_record": "imported_record",
            "clinician_entered": "clinician",
            "model_extracted": "model",
        }
        assertion_author = choice(
            payload.get("assertion_author", assertion_author_defaults[source_class]),
            "assertion_author",
            ASSERTION_AUTHORS,
        )
        if verification_state == "clinician_confirmed":
            if source_class != "clinician_entered" or assertion_author != "clinician":
                raise ValueError(
                    "clinician-confirmed observations require a clinician-entered, "
                    "clinician-authored record"
                )
            if reviewed_by is None:
                raise ValueError("clinician-confirmed observations require reviewed_by")
        if source_class == "model_extracted" and verification_state != "unreviewed":
            if not supersedes or not reviewed_by:
                raise ValueError(
                    "model-extracted observations must remain unreviewed until a named human review creates a revision"
                )
        coverage_state = choice(
            payload.get("coverage_state", "observed"),
            "coverage_state",
            COVERAGE_STATES,
        )
        artifact_id = optional_text(payload.get("artifact_id"), "artifact_id", 200)
        specimen_id = optional_text(payload.get("specimen_id"), "specimen_id", 200)
        assay_id = optional_text(payload.get("assay_id"), "assay_id", 200)
        source_identifier = optional_text(
            payload.get("source_identifier"), "source_identifier", SOURCE_LABEL_MAX
        )
        self._require_owned_references(
            user_id,
            artifact_id=artifact_id,
            specimen_id=specimen_id,
            assay_id=assay_id,
        )
        assay = self.get_assay(user_id, assay_id) if assay_id else None
        entities = (
            self.list_profile_entities(user_id)
            if source_class == "issued_record" or artifact_id or specimen_id or assay_id
            else None
        )
        specimens_by_id = {
            str(item["specimen_id"]): item
            for item in (entities or {}).get("specimens") or []
        }
        if artifact_id is None and assay is not None:
            artifact_id = assay.get("artifact_id")
            assay_specimen = specimens_by_id.get(str(assay.get("specimen_id") or ""))
            artifact_id = artifact_id or (
                assay_specimen.get("artifact_id") if assay_specimen else None
            )
        if artifact_id is None and specimen_id:
            specimen = specimens_by_id.get(specimen_id)
            artifact_id = specimen.get("artifact_id") if specimen else None
        if verification_state == "record_confirmed" and not (
            artifact_id or source_identifier
        ):
            raise ValueError(
                "a record-confirmed observation requires a source artifact or "
                "source identifier"
            )
        if source_class == "issued_record":
            if not (artifact_id or source_identifier):
                raise ValueError(
                    "an issued-record observation requires an owned source artifact "
                    "or source identifier"
                )
            if artifact_id:
                artifact = next(
                    (
                        item
                        for item in (entities or {}).get("source_artifacts") or []
                        if item.get("artifact_id") == artifact_id
                    ),
                    None,
                )
                if (
                    not isinstance(artifact, dict)
                    or artifact.get("source_type") not in _ISSUED_MEDICAL_SOURCE_TYPES
                ):
                    raise ValueError(
                        "an issued-record observation requires an issued medical "
                        "record artifact"
                    )
        assay_scope = payload.get("assay_scope")
        detection_limits = payload.get("detection_limits")
        if assay is not None:
            assay_scope = assay_scope or assay.get("assay_scope")
            detection_limits = detection_limits or assay.get("detection_limits")
        molecular_finding = modality in {
            "reported_germline_finding",
            "reported_somatic_finding",
            "biomarker",
        }
        if (
            molecular_finding
            and assertion_status == "present"
            and coverage_state != "observed"
        ):
            raise ValueError("a present molecular finding must have observed coverage")
        if molecular_finding and assertion_status == "absent":
            if coverage_state != "explicitly_not_detected_within_declared_assay_scope":
                raise ValueError(
                    "an absent molecular finding requires explicit within-scope coverage"
                )
        if assertion_status == "absent" and coverage_state in {
            "not_measured",
            "not_provided",
            "unavailable",
            "out_of_scope",
        }:
            raise ValueError(
                "an absent observation cannot use missing, unavailable, or "
                "out-of-scope coverage"
            )
        if (
            coverage_state == "explicitly_not_detected_within_declared_assay_scope"
            and assertion_status != "absent"
        ):
            raise ValueError(
                "explicit within-scope non-detection requires an absent molecular finding"
            )
        if coverage_state == "explicitly_not_detected_within_declared_assay_scope":
            if not assay_id or not assay_scope or not detection_limits:
                raise ValueError(
                    "an explicit negative requires an assay with scope and detection limits"
                )

        requested_logical_id = optional_text(
            payload.get("logical_observation_id"),
            "logical_observation_id",
            SOURCE_LABEL_MAX,
        )
        if requested_logical_id and not supersedes:
            raise ValueError(
                "logical_observation_id is assigned by GenomiLab for a new observation"
            )

        reported_variant = None
        normalization_state = None
        if modality in {"reported_germline_finding", "reported_somatic_finding"}:
            reported_variant, normalization_state = normalize_reported_variant(
                payload.get("reported_variant") or original_wording
            )

        revision_token = uuid.uuid4().hex
        revision_id = f"observation-revision-{revision_token}"
        now = utc_now()
        value = payload.get("value")
        normalization_provenance = payload.get("normalization_provenance")
        if normalization_provenance is not None:
            if not isinstance(normalization_provenance, dict):
                raise ValueError("normalization_provenance must be an object")
            validate_private_payload(normalization_provenance)
        with self._connect() as connection:
            logical_id = None
            if supersedes:
                prior = connection.execute(
                    "SELECT user_id, logical_observation_id "
                    "FROM molecular_observations "
                    "WHERE observation_revision_id = ?",
                    (supersedes,),
                ).fetchone()
                if prior is None or str(prior["user_id"]) != user_id:
                    raise ValueError(
                        "supersedes_revision_id must name an observation for this user"
                    )
                if (
                    requested_logical_id
                    and requested_logical_id != prior["logical_observation_id"]
                ):
                    raise ValueError(
                        "a revision must retain its logical_observation_id"
                    )
                if (
                    connection.execute(
                        "SELECT 1 FROM molecular_observations "
                        "WHERE supersedes_revision_id = ?",
                        (supersedes,),
                    ).fetchone()
                    is not None
                ):
                    raise ValueError(
                        "only the current observation revision can be superseded"
                    )
                logical_id = str(prior["logical_observation_id"])
            logical_id = logical_id or f"observation-{revision_token}"
            try:
                connection.execute(
                    """
                    INSERT INTO molecular_observations(
                        observation_revision_id, user_id, logical_observation_id,
                        supersedes_revision_id, modality, label, original_wording,
                        assertion_status, verification_state, source_class,
                        assertion_author, reviewed_by, artifact_id,
                        source_identifier, source_locator, coverage_state,
                        normalized_code, value_json, onset_or_event_time, specimen_id,
                        assay_id, reported_variant, gene, reported_classification,
                        normalization_state, normalization_provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision_id,
                        user_id,
                        logical_id,
                        supersedes,
                        modality,
                        label,
                        original_wording,
                        assertion_status,
                        verification_state,
                        source_class,
                        assertion_author,
                        reviewed_by,
                        artifact_id,
                        source_identifier,
                        optional_text(
                            payload.get("source_locator"),
                            "source_locator",
                            SOURCE_LABEL_MAX,
                        ),
                        coverage_state,
                        optional_text(
                            payload.get("normalized_code"),
                            "normalized_code",
                            SOURCE_LABEL_MAX,
                        ),
                        json.dumps(value, separators=(",", ":"))
                        if value is not None
                        else None,
                        optional_text(
                            payload.get("onset_or_event_time"),
                            "onset_or_event_time",
                            SOURCE_LABEL_MAX,
                        ),
                        specimen_id,
                        assay_id,
                        reported_variant,
                        optional_text(payload.get("gene"), "gene", 80),
                        optional_text(
                            payload.get("reported_classification"),
                            "reported_classification",
                            SOURCE_LABEL_MAX,
                        ),
                        normalization_state,
                        compact_json(normalization_provenance)
                        if normalization_provenance is not None
                        else None,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if supersedes and (
                    "supersedes_revision_id" in str(exc)
                    or "current observation revision" in str(exc)
                ):
                    raise ValueError(
                        "only the current observation revision can be superseded"
                    ) from exc
                raise
            connection.execute(
                "UPDATE workspaces SET updated_at = ? WHERE user_id = ?", (now, user_id)
            )
            connection.execute(
                """
                INSERT INTO modality_coverage(
                    user_id, modality, coverage_state, assay_scope_json,
                    detection_limits_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, modality) DO UPDATE SET
                    coverage_state = excluded.coverage_state,
                    assay_scope_json = COALESCE(
                        excluded.assay_scope_json,
                        modality_coverage.assay_scope_json
                    ),
                    detection_limits_json = COALESCE(
                        excluded.detection_limits_json,
                        modality_coverage.detection_limits_json
                    ),
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    modality,
                    coverage_state,
                    compact_json(assay_scope) if assay_scope is not None else None,
                    compact_json(detection_limits)
                    if detection_limits is not None
                    else None,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM molecular_observations WHERE observation_revision_id = ?",
                (revision_id,),
            ).fetchone()
        return row_dict(row)

    def list_profile_observations(
        self: _StoreContract, user_id: str, *, current_only: bool = False
    ) -> list[JsonObject]:
        self._require_workspace(user_id)
        with self._connect() as connection:
            if current_only:
                rows = connection.execute(
                    """
                    SELECT observation.*
                      FROM molecular_observations observation
                     WHERE observation.user_id = ?
                       AND NOT EXISTS (
                           SELECT 1 FROM molecular_observations newer
                            WHERE newer.supersedes_revision_id = observation.observation_revision_id
                       )
                     ORDER BY observation.created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM molecular_observations WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
        return [row_dict(row) for row in rows]

    def get_profile_observation(
        self: _StoreContract, user_id: str, observation_revision_id: str
    ) -> JsonObject:
        self._require_workspace(user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM molecular_observations "
                "WHERE user_id = ? AND observation_revision_id = ?",
                (user_id, observation_revision_id),
            ).fetchone()
        if row is None:
            raise KeyError(observation_revision_id)
        return row_dict(row)

    def review_or_supersede_observation(
        self: _StoreContract,
        user_id: str,
        observation_revision_id: str,
        updates: JsonObject,
    ) -> JsonObject:
        """Create an immutable reviewed/corrected revision of a current fact."""

        validate_private_payload(updates)
        prior = self.get_profile_observation(user_id, observation_revision_id)
        allowed = {
            "label",
            "original_wording",
            "assertion_status",
            "verification_state",
            "source_class",
            "assertion_author",
            "reviewed_by",
            "artifact_id",
            "source_identifier",
            "source_locator",
            "coverage_state",
            "normalized_code",
            "value",
            "onset_or_event_time",
            "specimen_id",
            "assay_id",
            "reported_variant",
            "gene",
            "reported_classification",
            "normalization_provenance",
        }
        unexpected = set(updates) - allowed
        if unexpected:
            raise ValueError(
                "unsupported observation revision fields: "
                + ", ".join(sorted(unexpected))
            )
        if not updates:
            raise ValueError("an observation revision must change at least one field")
        payload = {key: prior.get(key) for key in allowed if prior.get(key) is not None}
        payload.update(updates)
        canonical = _canonical_revision_state(payload, modality=str(prior["modality"]))
        if canonical.get("artifact_id") is None and (
            canonical.get("specimen_id") or canonical.get("assay_id")
        ):
            entities = self.list_profile_entities(user_id)
            specimens_by_id = {
                str(item["specimen_id"]): item
                for item in entities.get("specimens") or []
            }
            if canonical.get("assay_id"):
                assay = self.get_assay(user_id, str(canonical["assay_id"]))
                canonical["artifact_id"] = assay.get("artifact_id")
                assay_specimen = specimens_by_id.get(
                    str(assay.get("specimen_id") or "")
                )
                canonical["artifact_id"] = canonical["artifact_id"] or (
                    assay_specimen.get("artifact_id") if assay_specimen else None
                )
            if canonical.get("artifact_id") is None and canonical.get("specimen_id"):
                specimen = specimens_by_id.get(str(canonical["specimen_id"]))
                canonical["artifact_id"] = (
                    specimen.get("artifact_id") if specimen else None
                )
        if all(prior.get(key) == canonical.get(key) for key in allowed):
            raise ValueError("an observation revision must change at least one field")
        payload = canonical
        payload.update(
            {
                "modality": prior["modality"],
                "logical_observation_id": prior["logical_observation_id"],
                "supersedes_revision_id": observation_revision_id,
            }
        )
        return self.add_profile_observation(user_id, payload)

    def modality_coverage(self: _StoreContract, user_id: str) -> list[JsonObject]:
        self._require_workspace(user_id)
        observations = self.list_profile_observations(user_id, current_only=True)
        groups: dict[tuple[str, str], JsonObject] = {}
        for observation in observations:
            modality = str(observation["modality"])
            coverage_state = str(observation["coverage_state"])
            group = groups.setdefault(
                (modality, coverage_state),
                {
                    "user_id": user_id,
                    "modality": modality,
                    "coverage_state": coverage_state,
                    "observation_revision_ids": [],
                    "assay_ids": [],
                },
            )
            group["observation_revision_ids"].append(
                str(observation["observation_revision_id"])
            )
            if observation.get("assay_id"):
                group["assay_ids"].append(str(observation["assay_id"]))
        result: list[JsonObject] = []
        for key in sorted(groups):
            group = groups[key]
            group["observation_revision_ids"] = sorted(
                set(group["observation_revision_ids"])
            )
            group["assay_ids"] = sorted(set(group["assay_ids"]))
            if not group["assay_ids"]:
                group.pop("assay_ids")
            result.append(group)
        return result


def _canonical_revision_state(payload: JsonObject, *, modality: str) -> JsonObject:
    """Return the exact durable observation state used for no-op comparison."""

    label = required_text(
        payload.get("label") or payload.get("original_wording"),
        "label",
        OBSERVATION_LABEL_MAX,
    )
    original_wording = required_text(
        payload.get("original_wording") or label,
        "original_wording",
        OBSERVATION_LABEL_MAX,
    )
    source_class = choice(
        payload.get("source_class", "patient_reported"),
        "source_class",
        SOURCE_CLASSES,
    )
    assertion_author_defaults = {
        "patient_reported": "patient",
        "caregiver_reported": "caregiver",
        "issued_record": "imported_record",
        "clinician_entered": "clinician",
        "model_extracted": "model",
    }
    reported_variant = None
    if modality in {"reported_germline_finding", "reported_somatic_finding"}:
        reported_variant, _ = normalize_reported_variant(
            payload.get("reported_variant") or original_wording
        )
    return {
        "label": label,
        "original_wording": original_wording,
        "assertion_status": choice(
            payload.get("assertion_status", "present"),
            "assertion_status",
            ASSERTION_STATUSES,
        ),
        "verification_state": choice(
            payload.get("verification_state", "user_confirmed"),
            "verification_state",
            VERIFICATION_STATES,
        ),
        "source_class": source_class,
        "assertion_author": choice(
            payload.get("assertion_author", assertion_author_defaults[source_class]),
            "assertion_author",
            ASSERTION_AUTHORS,
        ),
        "reviewed_by": optional_text(payload.get("reviewed_by"), "reviewed_by", 200),
        "artifact_id": optional_text(payload.get("artifact_id"), "artifact_id", 200),
        "source_identifier": optional_text(
            payload.get("source_identifier"), "source_identifier", SOURCE_LABEL_MAX
        ),
        "source_locator": optional_text(
            payload.get("source_locator"), "source_locator", SOURCE_LABEL_MAX
        ),
        "coverage_state": choice(
            payload.get("coverage_state", "observed"),
            "coverage_state",
            COVERAGE_STATES,
        ),
        "normalized_code": optional_text(
            payload.get("normalized_code"), "normalized_code", SOURCE_LABEL_MAX
        ),
        "value": payload.get("value"),
        "onset_or_event_time": optional_text(
            payload.get("onset_or_event_time"),
            "onset_or_event_time",
            SOURCE_LABEL_MAX,
        ),
        "specimen_id": optional_text(payload.get("specimen_id"), "specimen_id", 200),
        "assay_id": optional_text(payload.get("assay_id"), "assay_id", 200),
        "reported_variant": reported_variant,
        "gene": optional_text(payload.get("gene"), "gene", 80),
        "reported_classification": optional_text(
            payload.get("reported_classification"),
            "reported_classification",
            SOURCE_LABEL_MAX,
        ),
        "normalization_provenance": payload.get("normalization_provenance"),
    }
