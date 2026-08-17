"""Consent-bound immutable Patient Molecular Profile snapshots."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Callable, ContextManager, Protocol

from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...

    def list_profile_observations(
        self, user_id: str, *, current_only: bool = False
    ) -> list[JsonObject]: ...


def _identifier_list(value: object, field: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    identifiers = [required_text(item, field.removesuffix("s"), 300) for item in value]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{field} must not contain duplicate identifiers")
    return sorted(identifiers)


def _selected_modality_coverage(observations: list[Any]) -> list[JsonObject]:
    """Summarize only the exact revisions selected for one snapshot candidate.

    One row is emitted per modality and coverage state.  Keeping the contributing
    revision IDs makes mixed states (for example ``observed`` and
    ``not_provided``) explicit instead of collapsing them through the mutable
    workspace-level coverage row.
    """

    groups: dict[tuple[str, str], JsonObject] = {}
    for observation in observations:
        modality = str(observation["modality"])
        coverage_state = str(observation["coverage_state"])
        key = (modality, coverage_state)
        group = groups.setdefault(
            key,
            {
                "modality": modality,
                "coverage_state": coverage_state,
                "observation_revision_ids": [],
                "assertion_statuses": [],
                "assay_ids": [],
            },
        )
        group["observation_revision_ids"].append(
            str(observation["observation_revision_id"])
        )
        group["assertion_statuses"].append(str(observation["assertion_status"]))
        if observation["assay_id"]:
            group["assay_ids"].append(str(observation["assay_id"]))

    coverage: list[JsonObject] = []
    for key in sorted(groups):
        group = groups[key]
        for field in (
            "observation_revision_ids",
            "assertion_statuses",
            "assay_ids",
        ):
            group[field] = sorted(set(group[field]))
        if not group["assay_ids"]:
            group.pop("assay_ids")
        coverage.append(group)
    return coverage


class SnapshotStoreMixin:
    """Snapshot, consent, comparison, and projection-selection persistence."""

    def profile_snapshot_candidate(
        self: _StoreContract,
        user_id: str,
        *,
        investigation_id: object,
        purpose: object,
        observation_revision_ids: object = None,
        artifact_ids: object = None,
        specimen_ids: object = None,
        assay_ids: object = None,
        agi_id: object = None,
        agi_snapshot_id: object = None,
        genomic_scope: object = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        investigation = required_text(investigation_id, "investigation_id", 200)
        purpose_value = required_text(purpose, "purpose", QUESTION_MAX)
        requested_revisions = _identifier_list(
            observation_revision_ids, "observation_revision_ids"
        )
        if not requested_revisions:
            raise ValueError(
                "observation_revision_ids must select at least one profile observation"
            )
        requested_artifacts = _identifier_list(artifact_ids, "artifact_ids")
        requested_specimens = _identifier_list(specimen_ids, "specimen_ids")
        requested_assays = _identifier_list(assay_ids, "assay_ids")
        agi = optional_text(agi_id, "agi_id", 300)
        agi_snapshot = optional_text(agi_snapshot_id, "agi_snapshot_id", 300)
        if bool(agi) != bool(agi_snapshot):
            raise ValueError("agi_id and agi_snapshot_id must be supplied together")
        if genomic_scope is not None and not isinstance(genomic_scope, dict):
            raise ValueError("genomic_scope must be an object")
        validate_private_payload(genomic_scope)
        if agi and not genomic_scope:
            raise ValueError(
                "genomic_scope is required when genome context is approved"
            )

        with self._connect() as connection:
            target = connection.execute(
                "SELECT user_id FROM investigations WHERE investigation_id = ?",
                (investigation,),
            ).fetchone()
            if target is None or str(target["user_id"]) != user_id:
                raise ValueError("investigation_id must belong to the current user")
            observations = self._owned_rows(
                connection,
                table="molecular_observations",
                identifier_column="observation_revision_id",
                user_id=user_id,
                identifiers=requested_revisions,
            )
            derived_artifacts = {
                str(row["artifact_id"]) for row in observations if row["artifact_id"]
            }
            derived_specimens = {
                str(row["specimen_id"]) for row in observations if row["specimen_id"]
            }
            derived_assays = {
                str(row["assay_id"]) for row in observations if row["assay_id"]
            }
            if requested_assays is not None and set(requested_assays) != derived_assays:
                raise ValueError(
                    "assay_ids must exactly match the selected observation dependency closure"
                )
            selected_assays = derived_assays
            assay_rows = self._owned_rows(
                connection,
                table="assays",
                identifier_column="assay_id",
                user_id=user_id,
                identifiers=sorted(selected_assays),
            )
            derived_specimens.update(
                str(row["specimen_id"]) for row in assay_rows if row["specimen_id"]
            )
            derived_artifacts.update(
                str(row["artifact_id"]) for row in assay_rows if row["artifact_id"]
            )
            if (
                requested_specimens is not None
                and set(requested_specimens) != derived_specimens
            ):
                raise ValueError(
                    "specimen_ids must exactly match the selected observation and assay dependency closure"
                )
            selected_specimens = derived_specimens
            specimen_rows = self._owned_rows(
                connection,
                table="specimens",
                identifier_column="specimen_id",
                user_id=user_id,
                identifiers=sorted(selected_specimens),
            )
            derived_artifacts.update(
                str(row["artifact_id"]) for row in specimen_rows if row["artifact_id"]
            )
            if (
                requested_artifacts is not None
                and set(requested_artifacts) != derived_artifacts
            ):
                raise ValueError(
                    "artifact_ids must exactly match the selected profile dependency closure"
                )
            selected_artifacts = derived_artifacts
            self._owned_rows(
                connection,
                table="source_artifacts",
                identifier_column="artifact_id",
                user_id=user_id,
                identifiers=sorted(selected_artifacts),
            )
            coverage = _selected_modality_coverage(observations)
        candidate: JsonObject = {
            "status": "candidate",
            "user_id": user_id,
            "investigation_id": investigation,
            "purpose": purpose_value,
            "observation_revision_ids": requested_revisions,
            "artifact_ids": sorted(selected_artifacts),
            "specimen_ids": sorted(selected_specimens),
            "assay_ids": sorted(selected_assays),
            "modality_coverage": coverage,
            "agi_id": agi,
            "agi_snapshot_id": agi_snapshot,
            "genomic_scope": genomic_scope,
            "requires_explicit_approval": True,
        }
        candidate["candidate_sha256"] = hashlib.sha256(
            compact_json(
                {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"status", "requires_explicit_approval"}
                }
            ).encode("utf-8")
        ).hexdigest()
        return candidate

    def create_profile_snapshot(
        self: _StoreContract,
        user_id: str,
        *,
        workspace_session_id: object,
        investigation_id: object,
        purpose: object,
        observation_revision_ids: object,
        artifact_ids: object = None,
        specimen_ids: object = None,
        assay_ids: object = None,
        agi_id: object = None,
        agi_snapshot_id: object = None,
        genomic_scope: object = None,
        candidate_sha256: object = None,
        approved: object = False,
        refresh: object = False,
        expected_base_patient_molecular_snapshot_id: object = None,
        authorization_before_commit: Callable[[JsonObject], None] | None = None,
    ) -> JsonObject:
        if approved is not True:
            raise ValueError(
                "explicit approval is required before creating a profile snapshot"
            )
        if not isinstance(refresh, bool):
            raise ValueError("refresh must be a boolean")
        if authorization_before_commit is not None and not callable(
            authorization_before_commit
        ):
            raise ValueError("authorization_before_commit must be callable")
        session = required_text(workspace_session_id, "workspace_session_id", 200)
        expected_base_snapshot_id = optional_text(
            expected_base_patient_molecular_snapshot_id,
            "expected_base_patient_molecular_snapshot_id",
            200,
        )
        candidate = self.profile_snapshot_candidate(
            user_id,
            investigation_id=investigation_id,
            purpose=purpose,
            observation_revision_ids=observation_revision_ids,
            artifact_ids=artifact_ids,
            specimen_ids=specimen_ids,
            assay_ids=assay_ids,
            agi_id=agi_id,
            agi_snapshot_id=agi_snapshot_id,
            genomic_scope=genomic_scope,
        )
        approved_candidate_hash = required_text(
            candidate_sha256, "candidate_sha256", 64
        ).lower()
        if (
            len(approved_candidate_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in approved_candidate_hash
            )
            or approved_candidate_hash != candidate["candidate_sha256"]
        ):
            raise ValueError(
                "the approved profile candidate changed after preview; review it again"
            )
        approved_at = utc_now()
        consent_id = f"consent-{uuid.uuid4().hex}"
        manifest = {
            key: value
            for key, value in candidate.items()
            if key not in {"status", "requires_explicit_approval", "candidate_sha256"}
        }
        manifest.update({"consent_receipt_id": consent_id, "created_at": approved_at})
        manifest_hash = hashlib.sha256(
            compact_json(manifest).encode("utf-8")
        ).hexdigest()
        snapshot_id = f"molecular-snapshot-{manifest_hash[:24]}"
        scope_json = (
            compact_json(candidate["genomic_scope"])
            if candidate["genomic_scope"] is not None
            else None
        )
        result_snapshot_id = snapshot_id
        result_consent_id = consent_id
        context_change = "snapshot_created"
        snapshot_created = True
        snapshot_version = 1
        prior_snapshot_id: str | None = None
        snapshot_diff = self._profile_snapshot_diff(None, candidate)
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT user_id, patient_molecular_snapshot_id, "
                "active_consent_receipt_id FROM investigations "
                "WHERE investigation_id = ?",
                (candidate["investigation_id"],),
            ).fetchone()
            if investigation is None or str(investigation["user_id"]) != user_id:
                raise ValueError("investigation_id must belong to the current user")
            current_snapshot_id = str(
                investigation["patient_molecular_snapshot_id"] or ""
            )
            if current_snapshot_id != str(expected_base_snapshot_id or ""):
                raise ValueError(
                    "the investigation context changed after preview; review it again"
                )
            if not current_snapshot_id or refresh:
                current_revision_ids = {
                    str(row["observation_revision_id"])
                    for row in connection.execute(
                        "SELECT observation.observation_revision_id "
                        "FROM molecular_observations observation "
                        "WHERE observation.user_id = ? AND NOT EXISTS ("
                        "SELECT 1 FROM molecular_observations newer "
                        "WHERE newer.supersedes_revision_id = "
                        "observation.observation_revision_id)",
                        (user_id,),
                    ).fetchall()
                }
                if any(
                    revision_id not in current_revision_ids
                    for revision_id in candidate["observation_revision_ids"]
                ):
                    raise ValueError(
                        "the selected profile changed after preview; review the current observations again"
                    )
            if current_snapshot_id:
                context_change = "profile_refreshed"
                current_row = connection.execute(
                    "SELECT * FROM profile_snapshots "
                    "WHERE patient_molecular_snapshot_id = ?",
                    (current_snapshot_id,),
                ).fetchone()
                if current_row is None:
                    raise ValueError(
                        "the investigation's profile snapshot is unavailable"
                    )
                current = row_dict(current_row)
                snapshot_version = int(current["version"]) + 1
                prior_snapshot_id = current_snapshot_id
                snapshot_diff = self._profile_snapshot_diff(current, candidate)
                if self._snapshot_candidate_equal(current, candidate):
                    self._insert_consent_receipt(
                        connection,
                        consent_id=consent_id,
                        workspace_session_id=session,
                        user_id=user_id,
                        candidate=candidate,
                        snapshot_id=current_snapshot_id,
                        approved_at=approved_at,
                        scope_json=scope_json,
                    )
                    prior_consent_id = str(
                        investigation["active_consent_receipt_id"] or ""
                    )
                    if prior_consent_id:
                        connection.execute(
                            "UPDATE consent_receipts SET revoked_at = ? "
                            "WHERE consent_receipt_id = ? AND revoked_at IS NULL",
                            (approved_at, prior_consent_id),
                        )
                    connection.execute(
                        "UPDATE investigations SET active_consent_receipt_id = ?, "
                        "domain_revision = domain_revision + 1, "
                        "updated_at = ? WHERE investigation_id = ?",
                        (consent_id, approved_at, candidate["investigation_id"]),
                    )
                    result_snapshot_id = current_snapshot_id
                    context_change = "authorization_renewed"
                    snapshot_created = False
                elif not refresh:
                    raise ValueError(
                        "the approved context differs from the pinned snapshot; "
                        "compare it and explicitly approve a refresh"
                    )

            if not current_snapshot_id or snapshot_created:
                self._insert_consent_receipt(
                    connection,
                    consent_id=consent_id,
                    workspace_session_id=session,
                    user_id=user_id,
                    candidate=candidate,
                    snapshot_id=snapshot_id,
                    approved_at=approved_at,
                    scope_json=scope_json,
                )
                if current_snapshot_id and investigation["active_consent_receipt_id"]:
                    connection.execute(
                        "UPDATE consent_receipts SET revoked_at = ? "
                        "WHERE consent_receipt_id = ? AND revoked_at IS NULL",
                        (approved_at, investigation["active_consent_receipt_id"]),
                    )
                connection.execute(
                    """
                INSERT INTO profile_snapshots(
                    patient_molecular_snapshot_id, user_id, investigation_id,
                    version, prior_patient_molecular_snapshot_id, diff_json,
                    purpose, observation_revision_ids_json, artifact_ids_json,
                    specimen_ids_json, assay_ids_json, modality_coverage_json,
                    genomic_scope_json, agi_id, agi_snapshot_id,
                    consent_receipt_id, manifest_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        snapshot_id,
                        user_id,
                        candidate["investigation_id"],
                        snapshot_version,
                        prior_snapshot_id,
                        compact_json(snapshot_diff),
                        candidate["purpose"],
                        compact_json(candidate["observation_revision_ids"]),
                        compact_json(candidate["artifact_ids"]),
                        compact_json(candidate["specimen_ids"]),
                        compact_json(candidate["assay_ids"]),
                        compact_json(candidate["modality_coverage"]),
                        scope_json,
                        candidate["agi_id"],
                        candidate["agi_snapshot_id"],
                        consent_id,
                        manifest_hash,
                        approved_at,
                    ),
                )
                connection.execute(
                    """
                UPDATE investigations
                   SET patient_molecular_snapshot_id = ?, agi_id = ?,
                       agi_snapshot_id = ?, active_consent_receipt_id = ?,
                       status = 'approved',
                       domain_revision = domain_revision + 1, updated_at = ?
                 WHERE investigation_id = ?
                """,
                    (
                        snapshot_id,
                        candidate["agi_id"],
                        candidate["agi_snapshot_id"],
                        consent_id,
                        approved_at,
                        candidate["investigation_id"],
                    ),
                )
            if authorization_before_commit is not None:
                # Issuance is deliberately inside this transaction boundary:
                # any failure leaves the prior snapshot, consent, and
                # investigation lifecycle canonical and exactly retryable.
                authorization_before_commit(
                    {
                        "workspace_session_id": session,
                        "user_id": user_id,
                        "investigation_id": candidate["investigation_id"],
                        "patient_molecular_snapshot_id": result_snapshot_id,
                        "consent_receipt_id": result_consent_id,
                        "agi_id": candidate["agi_id"],
                        "agi_snapshot_id": candidate["agi_snapshot_id"],
                        "purpose": candidate["purpose"],
                        "genomic_scope": candidate["genomic_scope"],
                    }
                )
        result = self.get_profile_snapshot(result_snapshot_id)
        if str(result.get("consent_receipt_id") or "") != result_consent_id:
            result["snapshot_origin_consent_receipt_id"] = result.get(
                "consent_receipt_id"
            )
        result["consent_receipt_id"] = result_consent_id
        result["context_change"] = context_change
        result["snapshot_created"] = snapshot_created
        return result

    @staticmethod
    def _profile_snapshot_diff(
        prior: JsonObject | None, candidate: JsonObject
    ) -> JsonObject:
        collection_fields = (
            "observation_revision_ids",
            "artifact_ids",
            "specimen_ids",
            "assay_ids",
        )
        diff: JsonObject = {}
        for field in collection_fields:
            old = set(prior.get(field) or []) if prior is not None else set()
            new = set(candidate.get(field) or [])
            diff[field] = {
                "added": sorted(new - old),
                "removed": sorted(old - new),
            }
        diff["agi_revision_changed"] = prior is not None and (
            prior.get("agi_id"),
            prior.get("agi_snapshot_id"),
        ) != (candidate.get("agi_id"), candidate.get("agi_snapshot_id"))
        diff["purpose_changed"] = prior is not None and prior.get(
            "purpose"
        ) != candidate.get("purpose")
        diff["genomic_scope_changed"] = prior is not None and prior.get(
            "genomic_scope"
        ) != candidate.get("genomic_scope")
        diff["modality_coverage_changed"] = prior is not None and prior.get(
            "modality_coverage"
        ) != candidate.get("modality_coverage")
        return diff

    @staticmethod
    def _snapshot_candidate_equal(snapshot: JsonObject, candidate: JsonObject) -> bool:
        fields = (
            "user_id",
            "investigation_id",
            "purpose",
            "observation_revision_ids",
            "artifact_ids",
            "specimen_ids",
            "assay_ids",
            "modality_coverage",
            "genomic_scope",
            "agi_id",
            "agi_snapshot_id",
        )
        return all(snapshot.get(field) == candidate.get(field) for field in fields)

    @staticmethod
    def _insert_consent_receipt(
        connection: Any,
        *,
        consent_id: str,
        workspace_session_id: str,
        user_id: str,
        candidate: JsonObject,
        snapshot_id: str,
        approved_at: str,
        scope_json: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO consent_receipts(
                consent_receipt_id, workspace_session_id, user_id,
                investigation_id, patient_molecular_snapshot_id, purpose,
                observation_revision_ids_json, artifact_ids_json,
                specimen_ids_json, assay_ids_json, agi_id, agi_snapshot_id,
                genomic_scope_json, approved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                consent_id,
                workspace_session_id,
                user_id,
                candidate["investigation_id"],
                snapshot_id,
                candidate["purpose"],
                compact_json(candidate["observation_revision_ids"]),
                compact_json(candidate["artifact_ids"]),
                compact_json(candidate["specimen_ids"]),
                compact_json(candidate["assay_ids"]),
                candidate["agi_id"],
                candidate["agi_snapshot_id"],
                scope_json,
                approved_at,
            ),
        )

    def compare_profile_snapshot(
        self: _StoreContract,
        patient_molecular_snapshot_id: str,
        candidate: JsonObject,
    ) -> JsonObject:
        current = self.get_profile_snapshot(patient_molecular_snapshot_id)
        if candidate.get("user_id") != current.get("user_id"):
            raise ValueError("candidate and snapshot must belong to the same user")
        comparisons = self._profile_snapshot_diff(current, candidate)
        changed = (
            bool(comparisons["agi_revision_changed"])
            or any(
                value["added"] or value["removed"]
                for key, value in comparisons.items()
                if isinstance(value, dict) and "added" in value
            )
            or any(
                bool(comparisons[field])
                for field in (
                    "purpose_changed",
                    "genomic_scope_changed",
                    "modality_coverage_changed",
                )
            )
        )
        return {
            "status": "changed" if changed else "unchanged",
            "patient_molecular_snapshot_id": patient_molecular_snapshot_id,
            "comparison": comparisons,
            "snapshot_created": False,
            "requires_explicit_approval": changed,
        }

    def get_profile_snapshot(
        self: _StoreContract, patient_molecular_snapshot_id: str
    ) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM profile_snapshots WHERE patient_molecular_snapshot_id = ?",
                (patient_molecular_snapshot_id,),
            ).fetchone()
        if row is None:
            raise KeyError(patient_molecular_snapshot_id)
        return row_dict(row)

    def revoke_session_consents(self: _StoreContract, workspace_session_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE consent_receipts SET revoked_at = ? "
                "WHERE workspace_session_id = ? AND revoked_at IS NULL",
                (utc_now(), workspace_session_id),
            )
        return int(cursor.rowcount)

    def revoke_consent(self: _StoreContract, consent_receipt_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE consent_receipts SET revoked_at = ? "
                "WHERE consent_receipt_id = ? AND revoked_at IS NULL",
                (utc_now(), consent_receipt_id),
            )
        return bool(cursor.rowcount)

    def consent_receipt(self: _StoreContract, consent_receipt_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM consent_receipts WHERE consent_receipt_id = ?",
                (consent_receipt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(consent_receipt_id)
        return row_dict(row)

    @staticmethod
    def _owned_rows(
        connection: Any,
        *,
        table: str,
        identifier_column: str,
        user_id: str,
        identifiers: list[str],
    ) -> list[Any]:
        allowed = {
            ("molecular_observations", "observation_revision_id"),
            ("source_artifacts", "artifact_id"),
            ("specimens", "specimen_id"),
            ("assays", "assay_id"),
        }
        if (table, identifier_column) not in allowed:
            raise ValueError("unsupported snapshot entity")
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = connection.execute(
            f"SELECT * FROM {table} WHERE user_id = ? "
            f"AND {identifier_column} IN ({placeholders})",
            (user_id, *identifiers),
        ).fetchall()
        found = {str(row[identifier_column]) for row in rows}
        if found != set(identifiers):
            raise ValueError(
                f"every {identifier_column} must belong to the current user"
            )
        return list(rows)
