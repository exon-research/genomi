from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from genomi.lab.authorization_store import (
    AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
    AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
    INVESTIGATION_AUTHORIZATION_INTENTS,
    investigation_authorization_scope_sha256,
)
from genomi.lab.store import GenomiLabStore
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class GenomiLabInvestigationAuthorizationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.store_path = Path(self._temporary_directory.name) / "genomilab.sqlite3"
        self.store = self._open_store()
        self.user_id = "user-authorization"
        self.session_id = "session-authorization"
        self.store.open_workspace(self.user_id, "Authorization test user")
        self.observation = self.store.add_profile_observation(
            self.user_id,
            {
                "modality": "condition",
                "label": "Synthetic condition",
                "source_class": "patient_reported",
                "verification_state": "user_confirmed",
            },
        )
        self.investigation, self.snapshot = self._create_context(
            "primary", session_id=self.session_id
        )
        self.investigation_id = str(self.investigation["investigation_id"])
        self.snapshot_id = str(self.snapshot["patient_molecular_snapshot_id"])
        self.consent_id = str(self.snapshot["consent_receipt_id"])
        self.authorization_scope = {
            "agent_session": {
                "recipient_id": "current-test-agent",
                "destination": "local-test-runtime",
                "allowed_intents": list(
                    reversed(sorted(INVESTIGATION_AUTHORIZATION_INTENTS))
                ),
            },
            "providers": [],
        }

    def _open_store(self) -> GenomiLabStore:
        return GenomiLabStore(
            self.store_path,
            key_provider=TEST_LAB_KEY_PROVIDER,
        )

    def _create_context(
        self, label: str, *, session_id: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        investigation = self.store.create_investigation(
            self.user_id,
            question=f"Investigate synthetic context {label}",
            disease_scope="Synthetic condition",
        )
        investigation_id = str(investigation["investigation_id"])
        purpose = f"Investigate synthetic context {label}"
        observation_ids = [self.observation["observation_revision_id"]]
        candidate = self.store.profile_snapshot_candidate(
            self.user_id,
            investigation_id=investigation_id,
            purpose=purpose,
            observation_revision_ids=observation_ids,
        )
        snapshot = self.store.create_profile_snapshot(
            self.user_id,
            workspace_session_id=session_id,
            investigation_id=investigation_id,
            purpose=purpose,
            observation_revision_ids=observation_ids,
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
        )
        return investigation, snapshot

    @staticmethod
    def _digest(label: str) -> str:
        return hashlib.sha256(label.encode("utf-8")).hexdigest()

    def _create_authorization(
        self,
        label: str = "primary-authorization",
        *,
        session_id: str | None = None,
        investigation_id: str | None = None,
        snapshot_id: str | None = None,
        consent_id: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, object]:
        return self.store.create_investigation_authorization(
            self.user_id,
            workspace_session_id=session_id or self.session_id,
            investigation_id=investigation_id or self.investigation_id,
            patient_molecular_snapshot_id=snapshot_id or self.snapshot_id,
            consent_receipt_id=consent_id or self.consent_id,
            authorization_scope=self.authorization_scope,
            candidate_receipt_sha256=self._digest(label),
            supersedes_authorization_receipt_id=supersedes,
            approved=True,
        )

    def _create_disclosure(
        self,
        label: str,
        *,
        investigation_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        return self.store.create_outbound_disclosure_receipt(
            self.user_id,
            workspace_session_id=session_id or self.session_id,
            investigation_id=investigation_id or self.investigation_id,
            recipient_kind="underlying_agent",
            recipient_id="current-test-agent",
            purpose="Execute approved synthetic investigation work",
            destination="local-test-runtime",
            data_categories=["approved_context", "command_context"],
            payload={"approved_context": {"label": label}},
            policy_versions={"agent_application": "test-v1"},
            approved=True,
        )

    def test_receipt_is_idempotent_queryable_and_durable(self) -> None:
        receipt = self._create_authorization()
        replay = self._create_authorization()

        self.assertEqual(
            replay["authorization_receipt_id"],
            receipt["authorization_receipt_id"],
        )
        self.assertEqual(
            receipt["authorization_scope"]["agent_session"]["allowed_intents"],
            sorted(INVESTIGATION_AUTHORIZATION_INTENTS),
        )
        self.assertEqual(
            receipt["authorization_scope_sha256"],
            investigation_authorization_scope_sha256(
                {
                    **self.authorization_scope,
                    "agent_session": {
                        **self.authorization_scope["agent_session"],
                        "allowed_intents": sorted(
                            INVESTIGATION_AUTHORIZATION_INTENTS
                        ),
                    },
                }
            ),
        )
        found = self.store.find_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=self.user_id,
            investigation_id=self.investigation_id,
            candidate_receipt_sha256=self._digest("primary-authorization"),
        )
        current = self.store.current_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=self.user_id,
            investigation_id=self.investigation_id,
        )
        required = self.store.require_investigation_authorization(
            receipt["authorization_receipt_id"],
            workspace_session_id=self.session_id,
            user_id=self.user_id,
            investigation_id=self.investigation_id,
            patient_molecular_snapshot_id=self.snapshot_id,
            consent_receipt_id=self.consent_id,
            authorization_scope=self.authorization_scope,
        )
        self.assertEqual(found, receipt)
        self.assertEqual(current, receipt)
        self.assertEqual(required, receipt)

        reopened = self._open_store()
        self.assertEqual(
            reopened.current_investigation_authorization(
                workspace_session_id=self.session_id,
                user_id=self.user_id,
                investigation_id=self.investigation_id,
            ),
            receipt,
        )
        self.assertIn(
            "idx_investigation_authorizations_one_active",
            reopened.indexes_for("investigation_authorization_receipts"),
        )

    def test_reopening_an_existing_workspace_adds_authorization_tables(self) -> None:
        with self.store._connect() as connection:
            connection.execute(
                "DROP TABLE investigation_authorization_derivations"
            )
            connection.execute("DROP TABLE investigation_authorization_receipts")

        reopened = self._open_store()
        self.assertEqual(
            reopened.get_workspace(self.user_id)["user_id"],
            self.user_id,
        )
        receipt = reopened.create_investigation_authorization(
            self.user_id,
            workspace_session_id=self.session_id,
            investigation_id=self.investigation_id,
            patient_molecular_snapshot_id=self.snapshot_id,
            consent_receipt_id=self.consent_id,
            authorization_scope=self.authorization_scope,
            candidate_receipt_sha256=self._digest("migrated-workspace"),
            approved=True,
        )
        self.assertTrue(receipt["authorization_receipt_id"])

    def test_creation_requires_exact_current_context_and_empty_provider_scope(
        self,
    ) -> None:
        common = {
            "workspace_session_id": self.session_id,
            "investigation_id": self.investigation_id,
            "patient_molecular_snapshot_id": self.snapshot_id,
            "consent_receipt_id": self.consent_id,
            "authorization_scope": self.authorization_scope,
            "candidate_receipt_sha256": self._digest("unapproved"),
        }
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            self.store.create_investigation_authorization(self.user_id, **common)

        provider_scope = {
            **self.authorization_scope,
            "providers": [{"recipient_id": "external-provider"}],
        }
        with self.assertRaisesRegex(ValueError, "provider authorization"):
            self.store.create_investigation_authorization(
                self.user_id,
                **{**common, "authorization_scope": provider_scope},
                approved=True,
            )

        reduced_scope = {
            **self.authorization_scope,
            "agent_session": {
                **self.authorization_scope["agent_session"],
                "allowed_intents": ["plan"],
            },
        }
        with self.assertRaisesRegex(ValueError, "exactly the routine"):
            self.store.create_investigation_authorization(
                self.user_id,
                **{**common, "authorization_scope": reduced_scope},
                approved=True,
            )

        with self.assertRaisesRegex(ValueError, "consent does not match"):
            self.store.create_investigation_authorization(
                self.user_id,
                **{
                    **common,
                    "workspace_session_id": "different-session",
                    "candidate_receipt_sha256": self._digest("wrong-session"),
                },
                approved=True,
            )

    def test_current_receipt_uses_the_full_context_validator(self) -> None:
        self._create_authorization("full-current-validation")
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE consent_receipts SET workspace_session_id = ? "
                "WHERE consent_receipt_id = ?",
                ("drifted-session", self.consent_id),
            )

        with self.assertRaisesRegex(ValueError, "consent does not match"):
            self.store.current_investigation_authorization(
                workspace_session_id=self.session_id,
                user_id=self.user_id,
                investigation_id=self.investigation_id,
            )

    def test_explicit_supersession_leaves_only_one_active_receipt(self) -> None:
        first = self._create_authorization("first")
        with self.assertRaisesRegex(ValueError, "explicitly superseded"):
            self._create_authorization("second")

        second = self._create_authorization(
            "second",
            supersedes=str(first["authorization_receipt_id"]),
        )
        self.assertEqual(
            second["supersedes_authorization_receipt_id"],
            first["authorization_receipt_id"],
        )
        self.assertIsNotNone(
            self.store.find_investigation_authorization(
                workspace_session_id=self.session_id,
                user_id=self.user_id,
                investigation_id=self.investigation_id,
                candidate_receipt_sha256=self._digest("first"),
            )["revoked_at"]
        )
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.store.require_investigation_authorization(
                first["authorization_receipt_id"],
                workspace_session_id=self.session_id,
                user_id=self.user_id,
                investigation_id=self.investigation_id,
                patient_molecular_snapshot_id=self.snapshot_id,
                consent_receipt_id=self.consent_id,
            )
        self.assertEqual(
            self._create_authorization(
                "second",
                supersedes=str(first["authorization_receipt_id"]),
            ),
            second,
        )

    def test_new_session_can_replace_stale_authority_after_consent_renewal(
        self,
    ) -> None:
        stale = self._create_authorization("stale-session")
        renewed_session = "session-after-restart"
        purpose = "Investigate synthetic context primary"
        observation_ids = [self.observation["observation_revision_id"]]
        candidate = self.store.profile_snapshot_candidate(
            self.user_id,
            investigation_id=self.investigation_id,
            purpose=purpose,
            observation_revision_ids=observation_ids,
        )
        renewed_snapshot = self.store.create_profile_snapshot(
            self.user_id,
            workspace_session_id=renewed_session,
            investigation_id=self.investigation_id,
            purpose=purpose,
            observation_revision_ids=observation_ids,
            candidate_sha256=candidate["candidate_sha256"],
            approved=True,
            expected_base_patient_molecular_snapshot_id=self.snapshot_id,
        )

        renewed = self._create_authorization(
            "renewed-session",
            session_id=renewed_session,
            snapshot_id=str(renewed_snapshot["patient_molecular_snapshot_id"]),
            consent_id=str(renewed_snapshot["consent_receipt_id"]),
        )
        self.assertEqual(
            renewed["supersedes_authorization_receipt_id"],
            stale["authorization_receipt_id"],
        )
        stale_saved = self.store.find_investigation_authorization(
            workspace_session_id=self.session_id,
            user_id=self.user_id,
            investigation_id=self.investigation_id,
            candidate_receipt_sha256=self._digest("stale-session"),
        )
        self.assertIsNotNone(stale_saved["revoked_at"])
        self.assertEqual(
            self._create_authorization(
                "renewed-session",
                session_id=renewed_session,
                snapshot_id=str(
                    renewed_snapshot["patient_molecular_snapshot_id"]
                ),
                consent_id=str(renewed_snapshot["consent_receipt_id"]),
            ),
            renewed,
        )

    def test_revocation_can_target_one_investigation_or_session(self) -> None:
        first = self._create_authorization("first-revocation")
        second_investigation, second_snapshot = self._create_context(
            "second", session_id=self.session_id
        )
        second = self._create_authorization(
            "second-revocation",
            investigation_id=str(second_investigation["investigation_id"]),
            snapshot_id=str(second_snapshot["patient_molecular_snapshot_id"]),
            consent_id=str(second_snapshot["consent_receipt_id"]),
        )

        self.assertEqual(
            self.store.revoke_investigation_authorizations(
                self.investigation_id
            ),
            1,
        )
        self.assertFalse(
            self.store.revoke_investigation_authorization(
                first["authorization_receipt_id"]
            )
        )
        self.assertEqual(
            self.store.revoke_session_investigation_authorizations(
                self.session_id
            ),
            1,
        )
        self.assertFalse(
            self.store.revoke_investigation_authorization(
                second["authorization_receipt_id"]
            )
        )

    def test_outbound_subject_derivation_is_exact_and_revalidated(self) -> None:
        authorization = self._create_authorization("outbound-parent")
        disclosure = self._create_disclosure("derived")
        unlinked = self._create_disclosure("unlinked")

        derivation = self.store.derive_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=disclosure["disclosure_receipt_id"],
        )
        self.assertEqual(
            self.store.derive_investigation_authorization_subject(
                authorization["authorization_receipt_id"],
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=disclosure["disclosure_receipt_id"],
            ),
            derivation,
        )
        required = self.store.require_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=disclosure["disclosure_receipt_id"],
        )
        discovered = self.store.investigation_authorization_for_subject(
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=disclosure["disclosure_receipt_id"],
        )
        self.assertEqual(discovered, required)
        self.assertEqual(required["derivation"], derivation)
        self.assertEqual(required["subject"], disclosure)
        self.assertIsNone(
            self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=unlinked["disclosure_receipt_id"],
            )
        )

        provider_disclosure = self.store.create_outbound_disclosure_receipt(
            self.user_id,
            workspace_session_id=self.session_id,
            investigation_id=self.investigation_id,
            recipient_kind="provider",
            recipient_id="external-provider",
            purpose="Send an external request",
            destination="https://provider.invalid",
            data_categories=["approved_context"],
            payload={"approved_context": {"label": "external"}},
            approved=True,
        )
        with self.assertRaisesRegex(ValueError, "different authorization scope"):
            self.store.derive_investigation_authorization_subject(
                authorization["authorization_receipt_id"],
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=provider_disclosure["disclosure_receipt_id"],
            )

        self.assertTrue(
            self.store.revoke_outbound_disclosure(
                disclosure["disclosure_receipt_id"]
            )
        )
        with self.assertRaisesRegex(ValueError, "disclosure subject is revoked"):
            self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=disclosure["disclosure_receipt_id"],
            )

        self.assertTrue(
            self.store.revoke_investigation_authorization(
                authorization["authorization_receipt_id"]
            )
        )
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=disclosure["disclosure_receipt_id"],
            )

    def test_plan_acceptance_can_be_derived_only_from_matching_context(self) -> None:
        authorization = self._create_authorization("plan-parent")
        plan_version = self.store.commit_plan(
            self.investigation_id,
            {
                "summary": "Review a synthetic research question.",
                "steps": [
                    {
                        "id": "step-a",
                        "title": "Review the approved evidence scope",
                        "capabilities": [],
                    }
                ],
                "capability_requests": [],
            },
        )
        current = self.store.get_investigation(self.investigation_id)[
            "current_plan_version"
        ]
        acceptance = self.store.accept_plan(
            self.investigation_id,
            plan_version_id=plan_version["plan_version_id"],
            user_id=self.user_id,
            workspace_session_id=self.session_id,
            plan_sha256=current["plan_sha256"],
            approved=True,
        )
        derivation = self.store.derive_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
            subject_id=acceptance["plan_acceptance_id"],
        )
        discovered = self.store.investigation_authorization_for_subject(
            subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
            subject_id=acceptance["plan_acceptance_id"],
        )
        self.assertEqual(discovered["derivation"], derivation)
        self.assertEqual(discovered["subject"]["plan_sha256"], current["plan_sha256"])

        newer_plan = self.store.commit_plan(
            self.investigation_id,
            {
                "summary": "Review a synthetic research question.",
                "steps": [
                    {
                        "id": "step-new",
                        "title": "Review the approved evidence scope",
                        "capabilities": [],
                    }
                ],
                "capability_requests": [],
            },
        )
        newer_current = self.store.get_investigation(self.investigation_id)[
            "current_plan_version"
        ]
        self.store.accept_plan(
            self.investigation_id,
            plan_version_id=newer_plan["plan_version_id"],
            user_id=self.user_id,
            workspace_session_id=self.session_id,
            plan_sha256=newer_current["plan_sha256"],
            approved=True,
        )
        with self.assertRaisesRegex(ValueError, "current accepted"):
            self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
                subject_id=acceptance["plan_acceptance_id"],
            )

        other_investigation, _other_snapshot = self._create_context(
            "other-plan", session_id=self.session_id
        )
        other_plan = self.store.commit_plan(
            str(other_investigation["investigation_id"]),
            {
                "summary": "Review a synthetic research question.",
                "steps": [
                    {
                        "id": "step-b",
                        "title": "Review the approved evidence scope",
                        "capabilities": [],
                    }
                ],
                "capability_requests": [],
            },
        )
        other_current = self.store.get_investigation(
            str(other_investigation["investigation_id"])
        )["current_plan_version"]
        other_acceptance = self.store.accept_plan(
            str(other_investigation["investigation_id"]),
            plan_version_id=other_plan["plan_version_id"],
            user_id=self.user_id,
            workspace_session_id=self.session_id,
            plan_sha256=other_current["plan_sha256"],
            approved=True,
        )
        with self.assertRaisesRegex(ValueError, "authorization context"):
            self.store.derive_investigation_authorization_subject(
                authorization["authorization_receipt_id"],
                subject_kind=AUTHORIZATION_SUBJECT_PLAN_ACCEPTANCE,
                subject_id=other_acceptance["plan_acceptance_id"],
            )

    def test_subject_lookup_rechecks_the_canonical_subject_fingerprint(self) -> None:
        authorization = self._create_authorization("fingerprint-parent")
        disclosure = self._create_disclosure("fingerprint-subject")
        self.store.derive_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=disclosure["disclosure_receipt_id"],
        )
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE outbound_disclosure_receipts SET payload_json = ? "
                "WHERE disclosure_receipt_id = ?",
                (
                    '{"approved_context":{"label":"tampered"}}',
                    disclosure["disclosure_receipt_id"],
                ),
            )

        with self.assertRaisesRegex(ValueError, "subject integrity failed"):
            self.store.investigation_authorization_for_subject(
                subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
                subject_id=disclosure["disclosure_receipt_id"],
            )

    def test_receipt_and_derivation_identity_are_immutable(self) -> None:
        authorization = self._create_authorization("immutable-parent")
        disclosure = self._create_disclosure("immutable-subject")
        derivation = self.store.derive_investigation_authorization_subject(
            authorization["authorization_receipt_id"],
            subject_kind=AUTHORIZATION_SUBJECT_OUTBOUND_DISCLOSURE,
            subject_id=disclosure["disclosure_receipt_id"],
        )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "receipts are immutable"):
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE investigation_authorization_receipts "
                    "SET authorization_scope_sha256 = ? "
                    "WHERE authorization_receipt_id = ?",
                    (
                        self._digest("tampered-scope"),
                        authorization["authorization_receipt_id"],
                    ),
                )
        with self.assertRaisesRegex(
            sqlite3.IntegrityError, "derivations are immutable"
        ):
            with self.store._connect() as connection:
                connection.execute(
                    "UPDATE investigation_authorization_derivations "
                    "SET subject_fingerprint = ? "
                    "WHERE authorization_derivation_id = ?",
                    (
                        self._digest("tampered-subject"),
                        derivation["authorization_derivation_id"],
                    ),
                )


if __name__ == "__main__":
    unittest.main()
