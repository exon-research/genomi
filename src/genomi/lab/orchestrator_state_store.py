"""Investigation and cycle persistence for the Lab orchestrator."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping

from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    utc_now,
)
from .orchestrator_support import (
    OrchestratorStoreContract,
    advance_investigation_revision,
    command_replay,
    require_investigation_revision,
    save_command,
)


class OrchestratorStateStoreMixin:
    """Persist cycle boundaries and the command-replay contract."""

    def update_health_profile(
        self: OrchestratorStoreContract,
        user_id: str,
        investigation_id: str,
        *,
        workspace_session_id: object,
        facts: object,
        purpose: object,
        selected_agi_context: object = None,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        """Persist Main-extracted health facts and refresh the approved snapshot.

        Identity and session are supplied only by the runtime authority layer.
        ``selected_agi_context`` is likewise an internal binding created from
        the UI-selected, session-approved AGI; public callers never provide AGI
        identifiers, paths, or genomic scopes.
        """

        self._require_workspace(user_id)  # type: ignore[attr-defined]
        session = required_text(workspace_session_id, "workspace_session_id", 300)
        purpose_value = required_text(purpose, "purpose", QUESTION_MAX)
        if not isinstance(facts, list) or not facts or not all(isinstance(item, Mapping) for item in facts):
            raise ValueError("facts must be a non-empty array of structured health observations")
        allowed_fact_fields = {
            "modality", "label", "original_wording", "assertion_status",
            "coverage_state", "normalized_code", "value", "onset_or_event_time",
            "reported_variant", "gene", "reported_classification",
            "source_class", "verification_state", "assertion_author",
        }
        normalized_facts: list[JsonObject] = []
        for item in facts:
            unexpected = set(item) - allowed_fact_fields
            if unexpected:
                raise ValueError("health facts contain fields outside the extraction contract")
            fact = dict(item)
            expected_provenance = {
                "source_class": "model_extracted",
                "verification_state": "unreviewed",
                "assertion_author": "model",
            }
            for field, expected in expected_provenance.items():
                if field in fact and fact[field] != expected:
                    raise ValueError(f"extracted health fact {field} must be {expected}")
            fact.update({
                **expected_provenance,
            })
            normalized_facts.append(fact)
        agi_id = None
        agi_snapshot_id = None
        genomic_scope = None
        if selected_agi_context is not None:
            if not isinstance(selected_agi_context, Mapping) or set(selected_agi_context) != {
                "access_approved", "agi_id", "agi_snapshot_id"
            }:
                raise ValueError("selected_agi_context must be the runtime-selected AGI binding")
            if selected_agi_context.get("access_approved") is not True:
                raise ValueError("the UI-selected AGI is not approved for this session")
            agi_id = required_text(selected_agi_context.get("agi_id"), "selected AGI id", 300)
            agi_snapshot_id = required_text(
                selected_agi_context.get("agi_snapshot_id"), "selected AGI snapshot id", 300
            )
            genomic_scope = {
                "context_kind": "selected_active_genome_index",
                "access_scope": "session",
            }
        request = {
            "facts": normalized_facts,
            "purpose": purpose_value,
            "selected_agi_context": {
                "access_approved": True,
                "agi_id": agi_id,
                "agi_snapshot_id": agi_snapshot_id,
            } if agi_id else None,
            "expected_revision": expected_revision,
        }
        command, request_hash, replay = command_replay(
            self,
            investigation_id=investigation_id,
            operation="lab.update_health_profile",
            command_id=command_id,
            request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(self, investigation_id, expected_revision)
            if investigation.get("user_id") != user_id:
                raise ValueError("investigation belongs to another user")
            observations = [self.add_profile_observation(user_id, fact) for fact in normalized_facts]  # type: ignore[attr-defined]
            current = self.list_profile_observations(user_id, current_only=True)  # type: ignore[attr-defined]
            current_ids = [str(item["observation_revision_id"]) for item in current]
            candidate = self.profile_snapshot_candidate(  # type: ignore[attr-defined]
                user_id,
                investigation_id=investigation_id,
                purpose=purpose_value,
                observation_revision_ids=current_ids,
                agi_id=agi_id,
                agi_snapshot_id=agi_snapshot_id,
                genomic_scope=genomic_scope,
            )
            snapshot = self.create_profile_snapshot(  # type: ignore[attr-defined]
                user_id,
                workspace_session_id=session,
                investigation_id=investigation_id,
                purpose=purpose_value,
                observation_revision_ids=current_ids,
                agi_id=agi_id,
                agi_snapshot_id=agi_snapshot_id,
                genomic_scope=genomic_scope,
                candidate_sha256=candidate["candidate_sha256"],
                approved=True,
                refresh=bool(investigation.get("patient_molecular_snapshot_id")),
                expected_base_patient_molecular_snapshot_id=investigation.get(
                    "patient_molecular_snapshot_id"
                ),
            )
            with self._connect() as connection:
                revision = int(connection.execute(
                    "SELECT domain_revision FROM investigations WHERE investigation_id = ?",
                    (investigation_id,),
                ).fetchone()["domain_revision"])
            response = {
                "observations": observations,
                "profile_snapshot": snapshot,
                "domain_revision": revision,
            }
            save_command(
                self,
                command_id=command,
                investigation_id=investigation_id,
                operation="lab.update_health_profile",
                request_sha256=request_hash,
                response=response,
            )
        return response

    def create_lab_investigation(
        self: OrchestratorStoreContract,
        user_id: str,
        *,
        workspace_session_id: object,
        question: object,
        disease_scope: object = None,
        public_only: object = False,
        approved_profile_context: object = None,
        command_id: object,
    ) -> JsonObject:
        """Create the canonical investigation behind ``lab.create_investigation``.

        A private context can be carried forward only through an explicit
        approved-profile object containing the exact snapshot and live source
        consent.  The method mints a new investigation-scoped consent receipt;
        it never reuses another investigation's receipt as authority.
        """

        self._require_workspace(user_id)  # type: ignore[attr-defined]
        session = required_text(workspace_session_id, "workspace_session_id", 300)
        question_value = required_text(question, "question", QUESTION_MAX)
        disease = optional_text(disease_scope, "disease_scope", QUESTION_MAX)
        if not isinstance(public_only, bool):
            raise ValueError("public_only must be a boolean")
        if approved_profile_context is not None and not isinstance(
            approved_profile_context, Mapping
        ):
            raise ValueError("approved_profile_context must be an object")
        if public_only and approved_profile_context:
            raise ValueError("public_only investigations cannot include private profile context")
        request = {
            "user_id": user_id,
            "workspace_session_id": session,
            "question": question_value,
            "disease_scope": disease,
            "public_only": public_only,
            "approved_profile_context": dict(approved_profile_context or {}),
        }
        command = required_text(command_id, "command_id", 300)
        request_hash = hashlib.sha256(compact_json(request).encode("utf-8")).hexdigest()
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT * FROM orchestrator_commands WHERE command_id = ?", (command,)
            ).fetchone()
        if prior is not None:
            saved = row_dict(prior)
            if saved.get("operation") != "lab.create_investigation" or saved.get(
                "request_sha256"
            ) != request_hash:
                raise ValueError("command_id was already used for a different request")
            return dict(saved["response"])

        investigation_id = f"investigation-{uuid.uuid4().hex}"
        now = utc_now()
        snapshot_id: str | None = None
        new_consent_id: str | None = None
        with self.atomic_write():
            context = dict(approved_profile_context or {})
            if context:
                if context.get("approved") is not True:
                    raise ValueError("approved_profile_context requires approved=true")
                snapshot_id = required_text(
                    context.get("patient_molecular_snapshot_id"),
                    "approved_profile_context.patient_molecular_snapshot_id",
                    300,
                )
                source_consent_id = required_text(
                    context.get("consent_receipt_id"),
                    "approved_profile_context.consent_receipt_id",
                    300,
                )
                with self._connect() as connection:
                    snapshot = connection.execute(
                        "SELECT * FROM profile_snapshots WHERE patient_molecular_snapshot_id = ? AND user_id = ?",
                        (snapshot_id, user_id),
                    ).fetchone()
                    source_consent = connection.execute(
                        "SELECT * FROM consent_receipts WHERE consent_receipt_id = ? "
                        "AND user_id = ? AND patient_molecular_snapshot_id = ? AND revoked_at IS NULL",
                        (source_consent_id, user_id, snapshot_id),
                    ).fetchone()
                if snapshot is None or source_consent is None:
                    raise ValueError("approved profile context is not active for this user")
                if str(source_consent["workspace_session_id"]) != session:
                    raise ValueError("approved profile context belongs to another session")
                new_consent_id = f"consent-{uuid.uuid4().hex}"
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO investigations(investigation_id, user_id, question, disease_scope, "
                    "status, patient_molecular_snapshot_id, active_consent_receipt_id, "
                    "domain_revision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (
                        investigation_id,
                        user_id,
                        question_value,
                        disease,
                        "running" if public_only else "awaiting_context_approval" if not snapshot_id else "running",
                        snapshot_id,
                        new_consent_id,
                        now,
                        now,
                    ),
                )
                if snapshot_id and new_consent_id:
                    source = row_dict(source_consent)
                    connection.execute(
                        "INSERT INTO consent_receipts(consent_receipt_id, workspace_session_id, user_id, "
                        "investigation_id, patient_molecular_snapshot_id, purpose, "
                        "observation_revision_ids_json, artifact_ids_json, specimen_ids_json, "
                        "assay_ids_json, agi_id, agi_snapshot_id, genomic_scope_json, approved_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            new_consent_id,
                            session,
                            user_id,
                            investigation_id,
                            snapshot_id,
                            required_text(context.get("purpose"), "approved_profile_context.purpose", 2_000),
                            compact_json(source.get("observation_revision_ids") or []),
                            compact_json(source.get("artifact_ids") or []),
                            compact_json(source.get("specimen_ids") or []),
                            compact_json(source.get("assay_ids") or []),
                            source.get("agi_id"),
                            source.get("agi_snapshot_id"),
                            compact_json(source.get("genomic_scope")) if source.get("genomic_scope") is not None else None,
                            now,
                        ),
                    )
                connection.execute(
                    "INSERT INTO orchestrator_investigation_contexts(investigation_id, "
                    "workspace_session_id, public_only, created_by_command_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (investigation_id, session, int(public_only), command, now),
                )
                investigation = row_dict(
                    connection.execute(
                        "SELECT * FROM investigations WHERE investigation_id = ?",
                        (investigation_id,),
                    ).fetchone()
                )
            response = {
                "investigation": investigation,
                "workspace_session_id": session,
                "public_only": public_only,
            }
            save_command(
                self,
                command_id=command,
                investigation_id=investigation_id,
                operation="lab.create_investigation",
                request_sha256=request_hash,
                response=response,
            )
        return response

    def create_investigation_cycle(
        self: OrchestratorStoreContract,
        investigation_id: str,
        *,
        purpose: object,
        patient_molecular_snapshot_id: object = None,
        prior_cycle_id: object = None,
        public_only: object = False,
        command_id: object,
        expected_revision: object,
    ) -> JsonObject:
        purpose_value = required_text(purpose, "purpose", 2_000)
        if not isinstance(public_only, bool):
            raise ValueError("public_only must be a boolean")
        snapshot_id = optional_text(
            patient_molecular_snapshot_id,
            "patient_molecular_snapshot_id",
            300,
        )
        prior_id = optional_text(prior_cycle_id, "prior_cycle_id", 300)
        request = {
            "purpose": purpose_value,
            "patient_molecular_snapshot_id": snapshot_id,
            "prior_cycle_id": prior_id,
            "public_only": public_only,
            "expected_revision": expected_revision,
        }
        command, request_hash, replay = command_replay(
            self,
            investigation_id=investigation_id,
            operation="lab.create_cycle",
            command_id=command_id,
            request=request,
        )
        if replay is not None:
            return replay
        with self.atomic_write():
            investigation = require_investigation_revision(
                self, investigation_id, expected_revision
            )
            with self._connect() as connection:
                prior = connection.execute(
                    "SELECT * FROM investigation_cycles WHERE investigation_id = ? "
                    "ORDER BY ordinal DESC LIMIT 1",
                    (investigation_id,),
                ).fetchone()
                if prior_id is not None and (
                    prior is None or str(prior["cycle_id"]) != prior_id
                ):
                    raise ValueError("prior_cycle_id must be the latest investigation cycle")
                selected_snapshot = snapshot_id or investigation.get(
                    "patient_molecular_snapshot_id"
                )
                if public_only:
                    if selected_snapshot:
                        raise ValueError("public_only cycles cannot include a profile snapshot")
                elif not selected_snapshot:
                    raise ValueError("a private cycle requires an approved profile snapshot")
                elif selected_snapshot != investigation.get("patient_molecular_snapshot_id"):
                    raise ValueError("cycle profile snapshot must be the investigation's current snapshot")
                ordinal = int(prior["ordinal"]) + 1 if prior is not None else 1
                cycle_id = f"cycle-{uuid.uuid4().hex}"
                now = utc_now()
                connection.execute(
                    "INSERT INTO investigation_cycles(cycle_id, investigation_id, ordinal, "
                    "prior_cycle_id, patient_molecular_snapshot_id, evidence_snapshot_id, "
                    "public_only, purpose, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        cycle_id,
                        investigation_id,
                        ordinal,
                        prior["cycle_id"] if prior is not None else None,
                        selected_snapshot,
                        investigation.get("evidence_snapshot_id"),
                        int(public_only),
                        purpose_value,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM investigation_cycles WHERE cycle_id = ?",
                    (cycle_id,),
                ).fetchone()
            revision = advance_investigation_revision(self, investigation_id)
            response = {"cycle": row_dict(row), "domain_revision": revision}
            save_command(
                self,
                command_id=command,
                investigation_id=investigation_id,
                operation="lab.create_cycle",
                request_sha256=request_hash,
                response=response,
            )
        return response

    def list_investigation_cycles(
        self: OrchestratorStoreContract, investigation_id: str
    ) -> list[JsonObject]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM investigation_cycles WHERE investigation_id = ? "
                "ORDER BY ordinal",
                (investigation_id,),
            ).fetchall()
        return [row_dict(row) for row in rows]


__all__ = ["OrchestratorStateStoreMixin"]
