"""Source, specimen, and assay records for the Patient Molecular Profile."""

from __future__ import annotations

import re
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    stable_id,
    utc_now,
    validate_private_payload,
)

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_TYPES = frozenset(
    {
        "issued_report",
        "laboratory_report",
        "pathology_report",
        "clinical_note",
        "patient_document",
        "other",
    }
)
_TUMOR_NORMAL_ROLES = frozenset(
    {"patient", "germline", "tumor", "matched_normal", "unknown"}
)
_SOURCE_ARTIFACT_FIELDS = frozenset(
    {
        "content_sha256",
        "source_type",
        "title",
        "source_identifier",
        "issued_at",
        "metadata",
    }
)
_SPECIMEN_FIELDS = frozenset(
    {
        "artifact_id",
        "specimen_type",
        "body_site",
        "collected_at",
        "disease_state",
        "tumor_normal_role",
        "metadata",
    }
)
_ASSAY_FIELDS = frozenset(
    {
        "specimen_id",
        "artifact_id",
        "assay_type",
        "laboratory",
        "platform",
        "pipeline",
        "genome_build",
        "assay_scope",
        "detection_limits",
        "qc",
    }
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...


def _optional_object(value: object, field: str) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    validate_private_payload(value)
    return value


def _required_object(value: object, field: str) -> JsonObject:
    result = _optional_object(value, field)
    if result is None or not result or not _has_substantive_value(result):
        raise ValueError(f"{field} must be a non-empty object")
    return result


def _has_substantive_value(value: object) -> bool:
    if isinstance(value, dict):
        return any(_has_substantive_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_substantive_value(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value is not False


def _validate_entity_payload(
    payload: object, *, allowed_fields: frozenset[str], entity: str
) -> JsonObject:
    if not isinstance(payload, dict):
        raise ValueError(f"{entity} must be an object")
    validate_private_payload(payload)
    unexpected = set(payload) - allowed_fields
    if unexpected:
        raise ValueError(
            f"unsupported {entity} fields: " + ", ".join(sorted(unexpected))
        )
    return payload


class ProfileEntityStoreMixin:
    """Immutable source-artifact, specimen, and assay persistence."""

    def add_source_artifact(
        self: _StoreContract, user_id: str, payload: JsonObject
    ) -> JsonObject:
        self._require_workspace(user_id)
        payload = _validate_entity_payload(
            payload,
            allowed_fields=_SOURCE_ARTIFACT_FIELDS,
            entity="source artifact",
        )
        content_sha256 = required_text(
            payload.get("content_sha256"), "content_sha256", 64
        ).lower()
        if not _SHA256_RE.fullmatch(content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        source_type = required_text(payload.get("source_type"), "source_type", 80)
        if source_type not in _SOURCE_TYPES:
            raise ValueError(
                "source_type must be one of: " + ", ".join(sorted(_SOURCE_TYPES))
            )
        title = required_text(payload.get("title"), "title", 500)
        metadata = _optional_object(payload.get("metadata"), "metadata")
        artifact_id = stable_id("artifact", user_id, content_sha256)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_artifacts(
                    artifact_id, user_id, content_sha256, source_type, title,
                    source_identifier, issued_at, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, content_sha256) DO NOTHING
                """,
                (
                    artifact_id,
                    user_id,
                    content_sha256,
                    source_type,
                    title,
                    optional_text(
                        payload.get("source_identifier"), "source_identifier", 300
                    ),
                    optional_text(payload.get("issued_at"), "issued_at", 100),
                    compact_json(metadata) if metadata is not None else None,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_artifacts WHERE user_id = ? AND content_sha256 = ?",
                (user_id, content_sha256),
            ).fetchone()
        result = row_dict(row)
        expected = {
            "source_type": source_type,
            "title": title,
            "source_identifier": optional_text(
                payload.get("source_identifier"), "source_identifier", 300
            ),
            "issued_at": optional_text(payload.get("issued_at"), "issued_at", 100),
            "metadata": metadata,
        }
        if any(result.get(field) != value for field, value in expected.items()):
            raise ValueError(
                "this source-record fingerprint is already registered with different "
                "immutable metadata"
            )
        return result

    def add_specimen(
        self: _StoreContract, user_id: str, payload: JsonObject
    ) -> JsonObject:
        self._require_workspace(user_id)
        payload = _validate_entity_payload(
            payload, allowed_fields=_SPECIMEN_FIELDS, entity="specimen"
        )
        artifact_id = optional_text(payload.get("artifact_id"), "artifact_id", 200)
        if artifact_id:
            self._require_owned_references(user_id, artifact_id=artifact_id)
        role = required_text(
            payload.get("tumor_normal_role", "unknown"), "tumor_normal_role", 80
        )
        if role not in _TUMOR_NORMAL_ROLES:
            raise ValueError(
                "tumor_normal_role must be one of: "
                + ", ".join(sorted(_TUMOR_NORMAL_ROLES))
            )
        metadata = _optional_object(payload.get("metadata"), "metadata")
        specimen_id = f"specimen-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO specimens(
                    specimen_id, user_id, artifact_id, specimen_type, body_site,
                    collected_at, disease_state, tumor_normal_role, metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    specimen_id,
                    user_id,
                    artifact_id,
                    required_text(payload.get("specimen_type"), "specimen_type", 200),
                    optional_text(payload.get("body_site"), "body_site", 200),
                    optional_text(payload.get("collected_at"), "collected_at", 100),
                    optional_text(payload.get("disease_state"), "disease_state", 300),
                    role,
                    compact_json(metadata) if metadata is not None else None,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM specimens WHERE specimen_id = ?", (specimen_id,)
            ).fetchone()
        return row_dict(row)

    def add_assay(
        self: _StoreContract, user_id: str, payload: JsonObject
    ) -> JsonObject:
        self._require_workspace(user_id)
        payload = _validate_entity_payload(
            payload, allowed_fields=_ASSAY_FIELDS, entity="assay"
        )
        specimen_id = optional_text(payload.get("specimen_id"), "specimen_id", 200)
        artifact_id = optional_text(payload.get("artifact_id"), "artifact_id", 200)
        self._require_owned_references(
            user_id, artifact_id=artifact_id, specimen_id=specimen_id
        )
        assay_scope = _required_object(payload.get("assay_scope"), "assay_scope")
        detection_limits = _required_object(
            payload.get("detection_limits"), "detection_limits"
        )
        qc = _optional_object(payload.get("qc"), "qc")
        assay_id = f"assay-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assays(
                    assay_id, user_id, specimen_id, artifact_id, assay_type,
                    laboratory, platform, pipeline, genome_build,
                    assay_scope_json, detection_limits_json, qc_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assay_id,
                    user_id,
                    specimen_id,
                    artifact_id,
                    required_text(payload.get("assay_type"), "assay_type", 200),
                    optional_text(payload.get("laboratory"), "laboratory", 300),
                    optional_text(payload.get("platform"), "platform", 300),
                    optional_text(payload.get("pipeline"), "pipeline", 300),
                    optional_text(payload.get("genome_build"), "genome_build", 80),
                    compact_json(assay_scope),
                    compact_json(detection_limits),
                    compact_json(qc) if qc is not None else None,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM assays WHERE assay_id = ?", (assay_id,)
            ).fetchone()
        return row_dict(row)

    def list_profile_entities(self: _StoreContract, user_id: str) -> JsonObject:
        self._require_workspace(user_id)
        with self._connect() as connection:
            artifacts = connection.execute(
                "SELECT * FROM source_artifacts WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
            specimens = connection.execute(
                "SELECT * FROM specimens WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
            assays = connection.execute(
                "SELECT * FROM assays WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return {
            "source_artifacts": [row_dict(row) for row in artifacts],
            "specimens": [row_dict(row) for row in specimens],
            "assays": [row_dict(row) for row in assays],
        }

    def get_assay(self: _StoreContract, user_id: str, assay_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assays WHERE assay_id = ? AND user_id = ?",
                (assay_id, user_id),
            ).fetchone()
        if row is None:
            raise ValueError("assay_id must belong to the current user")
        return row_dict(row)

    def _require_owned_references(
        self: _StoreContract,
        user_id: str,
        *,
        artifact_id: str | None = None,
        specimen_id: str | None = None,
        assay_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            if (
                artifact_id
                and connection.execute(
                    "SELECT 1 FROM source_artifacts WHERE artifact_id = ? AND user_id = ?",
                    (artifact_id, user_id),
                ).fetchone()
                is None
            ):
                raise ValueError("artifact_id must belong to the current user")
            specimen = None
            if specimen_id:
                specimen = connection.execute(
                    "SELECT artifact_id FROM specimens WHERE specimen_id = ? AND user_id = ?",
                    (specimen_id, user_id),
                ).fetchone()
                if specimen is None:
                    raise ValueError("specimen_id must belong to the current user")
                if artifact_id and specimen["artifact_id"] not in (None, artifact_id):
                    raise ValueError(
                        "specimen_id and artifact_id refer to different sources"
                    )
            if assay_id:
                assay = connection.execute(
                    "SELECT assay.specimen_id, assay.artifact_id, "
                    "specimen.artifact_id AS specimen_artifact_id "
                    "FROM assays assay LEFT JOIN specimens specimen "
                    "ON specimen.specimen_id = assay.specimen_id "
                    "AND specimen.user_id = assay.user_id "
                    "WHERE assay.assay_id = ? AND assay.user_id = ?",
                    (assay_id, user_id),
                ).fetchone()
                if assay is None:
                    raise ValueError("assay_id must belong to the current user")
                if specimen_id and assay["specimen_id"] not in (None, specimen_id):
                    raise ValueError(
                        "assay_id and specimen_id refer to different specimens"
                    )
                assay_artifact_id = (
                    assay["artifact_id"] or assay["specimen_artifact_id"]
                )
                supplied_specimen_artifact_id = (
                    specimen["artifact_id"] if specimen is not None else None
                )
                if (
                    supplied_specimen_artifact_id
                    and assay_artifact_id
                    and supplied_specimen_artifact_id != assay_artifact_id
                ):
                    raise ValueError(
                        "assay_id and specimen_id refer to different sources"
                    )
                if artifact_id and assay_artifact_id not in (None, artifact_id):
                    raise ValueError(
                        "assay_id and artifact_id refer to different sources"
                    )
