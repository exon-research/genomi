from __future__ import annotations

import unittest
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from genomi.lab.evidence_types import EvidenceStatus, ProviderTransportError
from genomi.lab.provider_connections import (
    ProviderConnectionError,
    ProviderConnections,
)
from genomi.lab.provider_credentials import (
    OSKeyringProviderCredentialStore,
    provider_credential_lock_path,
)
from genomi.lab.provider_policy import (
    AuthorizationBasis,
    DeploymentAuthorization,
    EvidenceDataClass,
    PAPERCLIP_PROVIDER,
    PatientDataContract,
    SourceFamily,
)
from genomi.lab.paperclip_transport import GxlPaperclipTransport
from genomi.lab.service import GenomiLabService
from genomi.lab.service_errors import LabError
from genomi.lab.store import GenomiLabStore
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


POLICY_EFFECTIVE_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)
POLICY_EXPIRES_AT = datetime(2100, 1, 1, tzinfo=timezone.utc)
CONNECTION_OPERATIONS = frozenset({"search", "lookup"})
CONNECTION_PURPOSES = frozenset(
    {
        "Build an evidence packet",
        "Patient investigation",
    }
)
ALL_PAPERCLIP_ROUTES = [
    {"source_family": "literature", "operations": ["search", "lookup"]},
    {"source_family": "regulatory", "operations": ["search"]},
    {"source_family": "trial_registry", "operations": ["search"]},
]


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def _authorization(
    permitted_source_families: frozenset[SourceFamily] = frozenset(SourceFamily),
) -> DeploymentAuthorization:
    return DeploymentAuthorization(
        provider=PAPERCLIP_PROVIDER,
        authorization_id="written-authorization",
        basis=AuthorizationBasis.WRITTEN_PROVIDER_AUTHORIZATION,
        permitted_source_families=permitted_source_families,
        permitted_operations=CONNECTION_OPERATIONS,
        permitted_purposes=CONNECTION_PURPOSES,
        permitted_data_classes=frozenset(EvidenceDataClass),
        effective_at=POLICY_EFFECTIVE_AT,
        expires_at=POLICY_EXPIRES_AT,
        revoked_at=None,
        policy_version_id="paperclip-policy-2026-08",
        aup_version_id="paperclip-aup-2026-08",
        terms_version_id="paperclip-terms-2026-08",
        privacy_version_id="paperclip-privacy-2026-08",
        live_use_authorized=True,
    )


def _patient_data_contract(
    permitted_source_families: frozenset[SourceFamily] = frozenset(SourceFamily),
) -> PatientDataContract:
    return PatientDataContract(
        provider=PAPERCLIP_PROVIDER,
        contract_id="independent-patient-data-contract",
        permitted_source_families=permitted_source_families,
        permitted_operations=CONNECTION_OPERATIONS,
        permitted_purposes=CONNECTION_PURPOSES,
        permitted_data_classes=frozenset(EvidenceDataClass),
        effective_at=POLICY_EFFECTIVE_AT,
        expires_at=POLICY_EXPIRES_AT,
        revoked_at=None,
        policy_version_id="patient-data-policy-2026-08",
        aup_version_id="patient-data-aup-2026-08",
        terms_version_id="patient-data-terms-2026-08",
        privacy_version_id="patient-data-privacy-2026-08",
        patient_influenced_data_authorized=True,
    )


class ProviderConnectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.keyring = _Keyring()
        self.store = OSKeyringProviderCredentialStore(self.keyring)
        self.calls: list[object] = []
        self.connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda secret: self.calls.append(("paperclip", secret)),
            biohub_esm_probe=lambda secret: self.calls.append(("biohub-esm", secret)),
            proto_probe=lambda token_id, token_secret, environment: self.calls.append(
                ("proto", token_id, token_secret, environment)
            ),
            clock=lambda: datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc),
        )

    def test_listing_is_network_free_and_redacted(self) -> None:
        payload = self.connections.list_integrations()
        self.assertEqual(
            [item["provider"] for item in payload["integrations"]],
            ["paperclip", "biohub-esm", "proto"],
        )
        self.assertTrue(
            all(
                item["connection_state"] == "not_configured"
                for item in payload["integrations"]
            )
        )
        self.assertEqual(self.calls, [])
        self.assertNotIn("api_key", repr(payload))
        self.assertNotIn("api_token", repr(payload))

    def test_unreadable_and_corrupt_keyring_state_is_never_reported_missing(
        self,
    ) -> None:
        class _UnreadableKeyring(_Keyring):
            def get_password(self, service: str, account: str) -> str | None:
                del service, account
                raise OSError("synthetic keyring failure")

        unavailable = ProviderConnections(
            credential_store=OSKeyringProviderCredentialStore(_UnreadableKeyring()),
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
        ).integration("paperclip")
        self.assertEqual(
            unavailable["connection_state"], "credential_store_unavailable"
        )
        self.assertEqual(unavailable["credential_state"], "unavailable")

        self.keyring.values[
            ("com.genomi.genomilab.providers.v1", "provider:paperclip")
        ] = "not-json"
        corrupt = self.connections.integration("paperclip")
        self.assertEqual(corrupt["connection_state"], "credential_corrupt")
        self.assertEqual(corrupt["credential_state"], "corrupt")

    def test_paperclip_key_can_be_checked_without_patient_investigation_authorization(
        self,
    ) -> None:
        saved = self.connections.connect("paperclip", {"api_key": "gxl-secret"})
        result = self.connections.verify("paperclip")

        self.assertEqual(result["credential_state"], "stored")
        self.assertEqual(saved["connection_state"], "configured_unverified")
        self.assertEqual(result["connection_state"], "ready")
        self.assertEqual(
            result["policy_state"], "blocked_missing_deployment_authorization"
        )
        self.assertTrue(result["verification_available"])
        self.assertEqual(result["investigation_operations"], [])
        self.assertEqual(self.calls, [("paperclip", "gxl-secret")])
        self.assertNotIn("gxl-secret", repr(result))

    def test_authorized_paperclip_and_fixed_synthetic_biohub_checks_are_explicit(
        self,
    ) -> None:
        authorized = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda secret: self.calls.append(("paperclip", secret)),
            biohub_esm_probe=lambda secret: self.calls.append(("biohub-esm", secret)),
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
            paperclip_patient_data_contract=_patient_data_contract(),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
            clock=lambda: datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc),
        )
        saved_paperclip = authorized.connect("paperclip", {"api_key": "gxl-secret"})
        saved_biohub = authorized.connect("biohub-esm", {"api_token": "esm-secret"})
        self.assertEqual(saved_paperclip["connection_state"], "configured_unverified")
        self.assertEqual(saved_biohub["connection_state"], "configured_unverified")
        self.assertTrue(saved_paperclip["verification_may_consume_credits"])
        self.assertTrue(saved_paperclip["verification_available"])
        self.assertTrue(saved_biohub["verification_may_consume_credits"])
        self.assertTrue(saved_biohub["verification_available"])
        self.assertEqual(self.calls, [])
        paperclip = authorized.verify("paperclip")
        biohub = authorized.verify("biohub-esm")

        self.assertEqual(paperclip["connection_state"], "ready")
        self.assertEqual(paperclip["investigation_operations"], ["search", "lookup"])
        self.assertEqual(paperclip["investigation_routes"], ALL_PAPERCLIP_ROUTES)
        self.assertEqual(
            paperclip["investigation_purposes"], sorted(CONNECTION_PURPOSES)
        )
        self.assertEqual(biohub["connection_state"], "ready")
        self.assertEqual(biohub["investigation_operations"], [])
        self.assertEqual(biohub["investigation_routes"], [])
        self.assertEqual(biohub["investigation_purposes"], [])
        self.assertEqual(biohub["policy_state"], "connection_only_no_product_operation")
        self.assertEqual(
            self.calls,
            [("paperclip", "gxl-secret"), ("biohub-esm", "esm-secret")],
        )
        self.assertEqual(paperclip["last_verified_at"], "2026-08-14T12:30:00Z")
        self.assertEqual(biohub["last_verified_at"], "2026-08-14T12:30:00Z")
        self.assertNotIn("gxl-secret", repr(paperclip))
        self.assertNotIn("esm-secret", repr(biohub))

    def test_paperclip_public_check_does_not_imply_patient_data_readiness(
        self,
    ) -> None:
        literature_only = frozenset({SourceFamily.LITERATURE})
        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda secret: self.calls.append(("paperclip", secret)),
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(literature_only),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})

        result = connections.verify("paperclip")

        self.assertEqual(result["connection_state"], "ready")
        self.assertTrue(result["verification_available"])
        self.assertEqual(
            result["policy_state"], "blocked_missing_patient_data_contract"
        )
        self.assertEqual(result["investigation_operations"], [])
        self.assertEqual(result["investigation_routes"], [])
        self.assertEqual(result["investigation_purposes"], [])
        self.assertEqual(self.calls, [("paperclip", "gxl-secret")])

    def test_manifest_reports_the_furthest_reached_investigation_gate(self) -> None:
        regulatory_only = frozenset({SourceFamily.REGULATORY})
        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(regulatory_only),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})

        result = connections.verify("paperclip")

        self.assertEqual(
            result["policy_state"], "blocked_missing_patient_data_contract"
        )
        self.assertEqual(result["investigation_operations"], [])
        self.assertEqual(result["investigation_routes"], [])
        self.assertEqual(result["investigation_purposes"], [])

    def test_paperclip_probe_is_independent_of_patient_route_scope(self) -> None:
        restricted_scopes = (
            frozenset({SourceFamily.REGULATORY}),
            frozenset(),
        )
        for deployment_scope in restricted_scopes:
            with self.subTest(deployment_scope=deployment_scope):
                calls: list[str] = []
                connections = ProviderConnections(
                    credential_store=OSKeyringProviderCredentialStore(_Keyring()),
                    paperclip_probe=lambda secret: calls.append(secret),
                    biohub_esm_probe=lambda *_: None,
                    proto_probe=lambda *_: None,
                    paperclip_deployment_authorization=_authorization(deployment_scope),
                    paperclip_patient_data_contract=_patient_data_contract(
                        deployment_scope
                    ),
                    paperclip_routes=GxlPaperclipTransport.supported_routes,
                )
                saved = connections.connect("paperclip", {"api_key": "gxl-secret"})

                result = connections.verify("paperclip")

                self.assertTrue(saved["verification_available"])
                self.assertTrue(result["verification_available"])
                self.assertEqual(result["connection_state"], "ready")
                self.assertEqual(calls, ["gxl-secret"])

    def test_paperclip_probe_is_independent_of_patient_policy_lifecycle(self) -> None:
        now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
        authorization = _authorization()
        blocked_authorizations = {
            "expired": replace(authorization, expires_at=now),
            "revoked": replace(authorization, revoked_at=now),
            "wrong_purpose": replace(
                authorization,
                permitted_purposes=frozenset({"Patient investigation"}),
            ),
            "wrong_data_class": replace(
                authorization,
                permitted_data_classes=frozenset(
                    {EvidenceDataClass.PATIENT_INFLUENCED_PUBLIC_EVIDENCE_QUERY}
                ),
            ),
            "wrong_operation": replace(
                authorization,
                permitted_operations=frozenset({"lookup"}),
            ),
        }
        for name, blocked in blocked_authorizations.items():
            with self.subTest(name=name):
                keyring = _Keyring()
                calls: list[str] = []
                connections = ProviderConnections(
                    credential_store=OSKeyringProviderCredentialStore(keyring),
                    paperclip_probe=lambda secret: calls.append(secret),
                    biohub_esm_probe=lambda *_: None,
                    proto_probe=lambda *_: None,
                    paperclip_deployment_authorization=blocked,
                    paperclip_patient_data_contract=_patient_data_contract(),
                    paperclip_routes=GxlPaperclipTransport.supported_routes,
                    clock=lambda: now,
                )
                connections.connect("paperclip", {"api_key": "gxl-secret"})

                result = connections.verify("paperclip")

                self.assertTrue(result["verification_available"])
                self.assertEqual(result["connection_state"], "ready")
                self.assertEqual(calls, ["gxl-secret"])

    def test_paperclip_manifest_uses_one_policy_time_snapshot(self) -> None:
        expires_at = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
        before_expiry = expires_at - timedelta(microseconds=1)
        clock_values = [before_expiry]

        def clock() -> datetime:
            return clock_values.pop(0) if len(clock_values) > 1 else clock_values[0]

        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=replace(
                _authorization(), expires_at=expires_at
            ),
            paperclip_patient_data_contract=replace(
                _patient_data_contract(), expires_at=expires_at
            ),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
            clock=clock,
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})
        connections.verify("paperclip")

        clock_values[:] = [before_expiry, expires_at]
        before = connections.integration("paperclip")
        self.assertEqual(before["policy_state"], "authorized")
        self.assertEqual(before["investigation_operations"], ["search", "lookup"])
        self.assertEqual(before["investigation_routes"], ALL_PAPERCLIP_ROUTES)
        self.assertEqual(before["investigation_purposes"], sorted(CONNECTION_PURPOSES))

        clock_values[:] = [expires_at]
        expired = connections.integration("paperclip")
        self.assertEqual(expired["policy_state"], "blocked_deployment_expired")
        self.assertEqual(expired["investigation_operations"], [])
        self.assertEqual(expired["investigation_routes"], [])
        self.assertEqual(expired["investigation_purposes"], [])

    def test_paperclip_operations_intersect_both_authorized_route_scopes(
        self,
    ) -> None:
        regulatory_only = frozenset({SourceFamily.REGULATORY})
        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
            paperclip_patient_data_contract=_patient_data_contract(regulatory_only),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})

        result = connections.verify("paperclip")

        self.assertEqual(result["policy_state"], "authorized")
        self.assertEqual(result["investigation_operations"], ["search"])
        self.assertEqual(
            result["investigation_routes"],
            [{"source_family": "regulatory", "operations": ["search"]}],
        )
        self.assertEqual(result["investigation_purposes"], sorted(CONNECTION_PURPOSES))

    def test_paperclip_operations_intersect_exact_operation_scopes(self) -> None:
        search_only = frozenset({"search"})
        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=replace(
                _authorization(), permitted_operations=search_only
            ),
            paperclip_patient_data_contract=replace(
                _patient_data_contract(), permitted_operations=search_only
            ),
            paperclip_routes=GxlPaperclipTransport.supported_routes,
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})

        result = connections.verify("paperclip")

        self.assertEqual(result["policy_state"], "authorized")
        self.assertEqual(result["investigation_operations"], ["search"])
        self.assertEqual(
            result["investigation_routes"],
            [
                {"source_family": route["source_family"], "operations": ["search"]}
                for route in ALL_PAPERCLIP_ROUTES
            ],
        )

    def test_paperclip_without_explicit_routes_advertises_no_operations(self) -> None:
        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
            paperclip_patient_data_contract=_patient_data_contract(),
        )
        connections.connect("paperclip", {"api_key": "gxl-secret"})

        result = connections.verify("paperclip")

        self.assertEqual(result["policy_state"], "authorized_unavailable")
        self.assertEqual(result["investigation_operations"], [])
        self.assertEqual(result["investigation_routes"], [])
        self.assertEqual(result["investigation_purposes"], [])

    def test_proto_verify_calls_only_the_explicit_modal_prerequisite_probe(
        self,
    ) -> None:
        saved = self.connections.connect(
            "proto",
            {
                "modal_token_id": "modal-id",
                "modal_token_secret": "modal-secret",
                "modal_environment": "genomilab-research",
            },
        )
        self.assertEqual(saved["connection_state"], "configured_unverified")
        self.assertEqual(self.calls, [])
        result = self.connections.verify("proto")
        self.assertEqual(result["connection_state"], "ready")
        self.assertEqual(result["policy_state"], "connection_only_no_product_operation")
        self.assertTrue(result["verification_available"])
        self.assertEqual(result["investigation_operations"], [])
        self.assertEqual(result["last_verified_at"], "2026-08-14T12:30:00Z")
        self.assertEqual(
            self.calls,
            [("proto", "modal-id", "modal-secret", "genomilab-research")],
        )
        self.assertNotIn("genomilab-research", repr(result))

    def test_ready_state_and_secret_are_bound_to_the_exact_credential_revision(
        self,
    ) -> None:
        first = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
        )
        second = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=lambda *_: None,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
        )
        first.connect("paperclip", {"api_key": "first-key"})
        self.assertEqual(first.verify("paperclip")["connection_state"], "ready")
        self.assertEqual(first.verified_paperclip_api_key(), "first-key")

        second.connect("paperclip", {"api_key": "replacement-key"})

        self.assertEqual(
            first.integration("paperclip")["connection_state"],
            "configured_unverified",
        )
        self.assertEqual(first.verified_paperclip_api_key(), "")

    def test_credential_replaced_during_probe_cannot_become_ready(self) -> None:
        def replace_during_probe(_secret: str) -> None:
            self.store.replace("paperclip", {"api_key": "replacement-key"})

        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=replace_during_probe,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
        )
        connections.connect("paperclip", {"api_key": "first-key"})

        result = connections.verify("paperclip")

        self.assertEqual(result["connection_state"], "configured_unverified")
        self.assertEqual(connections.verified_paperclip_api_key(), "")

    def test_probe_failure_is_typed_and_never_echoes_provider_error(self) -> None:
        def fail(_secret: str) -> None:
            raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)

        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=fail,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
        )
        connections.connect("paperclip", {"api_key": "paperclip-secret"})
        result = connections.verify("paperclip")
        self.assertEqual(result["connection_state"], "authentication_failed")
        self.assertEqual(result["credential_state"], "stored")
        self.assertNotIn("paperclip-secret", repr(result))

    def test_unavailable_provider_source_is_distinct_from_network_failure(self) -> None:
        def missing(_secret: str) -> None:
            raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)

        connections = ProviderConnections(
            credential_store=self.store,
            paperclip_probe=missing,
            biohub_esm_probe=lambda *_: None,
            proto_probe=lambda *_: None,
            paperclip_deployment_authorization=_authorization(),
        )
        connections.connect("paperclip", {"api_key": "paperclip-secret"})
        result = connections.verify("paperclip")
        self.assertEqual(result["connection_state"], "source_unavailable")

    def test_disconnect_requires_confirmation_and_removes_keyring_record(self) -> None:
        self.connections.connect("biohub-esm", {"api_token": "esm-secret"})
        with self.assertRaisesRegex(ProviderConnectionError, "confirmation"):
            self.connections.disconnect("biohub-esm", confirmed=False)

        result = self.connections.disconnect("biohub-esm", confirmed=True)
        self.assertEqual(result["connection_state"], "not_configured")
        self.assertFalse(self.store.has("biohub-esm"))

    def test_unknown_provider_and_extra_fields_fail_closed(self) -> None:
        with self.assertRaises(ProviderConnectionError):
            self.connections.connect("unknown", {"api_key": "secret"})
        with self.assertRaises(ProviderConnectionError):
            self.connections.connect(
                "paperclip", {"api_key": "secret", "endpoint": "https://evil.test"}
            )

    def test_service_persists_redacted_connection_result_before_returning(self) -> None:
        class _PaperclipClient:
            calls: list[tuple[object, ...]] = []

            @classmethod
            def search(cls, *args: object, **kwargs: object) -> object:
                cls.calls.append((*args, kwargs))
                return SimpleNamespace(exit_code=0, result_data={"papers": []})

        with tempfile.TemporaryDirectory() as temporary:
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-command-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=self.store,
                paperclip_transport=GxlPaperclipTransport(
                    client_factory=lambda _secret: _PaperclipClient()
                ),
            )
            try:
                saved = service.connect_integration(
                    "paperclip", {"api_key": "must-not-persist"}
                )
                checked = service.verify_integration("paperclip")
                commands = lab_store.list_provider_connection_commands(
                    "provider-command-session"
                )
                events = lab_store.list_provider_connection_events(
                    "provider-command-session"
                )

                self.assertEqual(len(commands), 2)
                self.assertEqual(len(events), 2)
                by_action = {command["action"]: command for command in commands}
                by_event = {event["event_type"]: event for event in events}
                self.assertEqual(
                    saved["connection_command_id"], by_action["connect"]["command_id"]
                )
                self.assertEqual(
                    checked["connection_command_id"], by_action["verify"]["command_id"]
                )
                self.assertEqual(
                    by_event["provider_connection_connect_recorded"]["payload"],
                    by_action["connect"]["result"],
                )
                self.assertEqual(
                    by_event["provider_connection_verify_recorded"]["payload"],
                    by_action["verify"]["result"],
                )
                self.assertEqual(commands[0]["result"]["credential_state"], "stored")
                self.assertEqual(checked["connection_state"], "ready")
                self.assertEqual(
                    checked["policy_state"],
                    "blocked_missing_deployment_authorization",
                )
                self.assertEqual(checked["investigation_operations"], [])
                self.assertEqual(checked["investigation_routes"], [])
                self.assertEqual(checked["investigation_purposes"], [])
                self.assertEqual(len(_PaperclipClient.calls), 1)
                self.assertNotIn("must-not-persist", repr([commands, events]))
            finally:
                service.close()

    def test_service_wires_patient_contract_and_transport_routes_into_manifest(
        self,
    ) -> None:
        class _PaperclipClient:
            @staticmethod
            def search(*_args: object, **_kwargs: object) -> object:
                return SimpleNamespace(exit_code=0, result_data={"papers": []})

        with tempfile.TemporaryDirectory() as temporary:
            service = GenomiLabService(
                store=GenomiLabStore(
                    Path(temporary) / "lab.sqlite3",
                    key_provider=TEST_LAB_KEY_PROVIDER,
                ),
                session_id="provider-wiring-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=self.store,
                paperclip_deployment_authorization=_authorization(),
                paperclip_patient_data_contract=_patient_data_contract(),
                paperclip_transport=GxlPaperclipTransport(
                    client_factory=lambda _secret: _PaperclipClient()
                ),
            )
            try:
                service.connect_integration("paperclip", {"api_key": "gxl-secret"})

                result = service.verify_integration("paperclip")

                self.assertEqual(result["policy_state"], "authorized")
                self.assertEqual(
                    result["investigation_operations"], ["search", "lookup"]
                )
            finally:
                service.close()

    def test_service_failure_persists_matching_redacted_event_before_raise(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-command-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=self.store,
            )
            try:
                with self.assertRaises(LabError) as raised:
                    service.verify_integration("biohub-esm")
                commands = lab_store.list_provider_connection_commands(
                    "provider-command-session"
                )
                events = lab_store.list_provider_connection_events(
                    "provider-command-session"
                )

                self.assertEqual(raised.exception.code, "integration_not_configured")
                self.assertEqual(events[0]["command_id"], commands[0]["command_id"])
                self.assertEqual(events[0]["payload"], commands[0]["result"])
                self.assertEqual(commands[0]["result"]["status"], "failed")
                self.assertNotIn("api_token", repr([commands, events]))
            finally:
                service.close()

    def test_audit_finalization_failure_restores_connect_and_disconnect_state(
        self,
    ) -> None:
        for action in ("connect", "disconnect"):
            with (
                self.subTest(action=action),
                tempfile.TemporaryDirectory() as temporary,
            ):
                keyring = _Keyring()
                credential_store = OSKeyringProviderCredentialStore(keyring)
                if action == "disconnect":
                    credential_store.replace(
                        "biohub-esm", {"api_token": "existing-secret"}
                    )
                lab_store = GenomiLabStore(
                    Path(temporary) / "lab.sqlite3",
                    key_provider=TEST_LAB_KEY_PROVIDER,
                )
                with lab_store._connect() as connection:
                    connection.execute(
                        """
                        CREATE TRIGGER reject_provider_event_finalization
                        BEFORE UPDATE ON provider_connection_events
                        BEGIN
                            SELECT RAISE(ABORT, 'synthetic finalization failure');
                        END
                        """
                    )
                service = GenomiLabService(
                    store=lab_store,
                    session_id=f"provider-{action}-rollback-session",
                    operation_call=lambda _operation, _params: {
                        "active_user_id": "synthetic-user"
                    },
                    provider_credential_store=credential_store,
                )
                try:
                    with self.assertRaises(LabError) as raised:
                        if action == "connect":
                            service.connect_integration(
                                "biohub-esm", {"api_token": "new-secret"}
                            )
                        else:
                            service.disconnect_integration("biohub-esm", confirmed=True)
                    self.assertEqual(
                        raised.exception.code, "provider_connection_audit_unavailable"
                    )
                    retained = credential_store.get("biohub-esm")
                    if action == "connect":
                        self.assertIsNone(retained)
                    else:
                        assert retained is not None
                        self.assertEqual(retained["api_token"], "existing-secret")
                    commands = lab_store.list_provider_connection_commands(
                        f"provider-{action}-rollback-session"
                    )
                    events = lab_store.list_provider_connection_events(
                        f"provider-{action}-rollback-session"
                    )
                    self.assertEqual(commands[0]["result"]["status"], "requested")
                    self.assertEqual(events[0]["payload"]["status"], "requested")
                    self.assertTrue(events[0]["event_type"].endswith("_requested"))
                    self.assertNotIn("secret", repr([commands, events]))
                finally:
                    service.close()

    def test_ambiguous_keyring_completion_is_reconciled_before_failed_audit(
        self,
    ) -> None:
        class _FailSelectedReadsKeyring(_Keyring):
            def __init__(self) -> None:
                super().__init__()
                self.get_calls = 0
                self.fail_on: set[int] = set()

            def get_password(self, service: str, account: str) -> str | None:
                self.get_calls += 1
                if self.get_calls in self.fail_on:
                    raise OSError("synthetic post-mutation read failure")
                return super().get_password(service, account)

        for action in ("connect", "disconnect"):
            with (
                self.subTest(action=action),
                tempfile.TemporaryDirectory() as temporary,
            ):
                keyring = _FailSelectedReadsKeyring()
                credential_store = OSKeyringProviderCredentialStore(keyring)
                if action == "disconnect":
                    credential_store.replace(
                        "biohub-esm", {"api_token": "existing-secret"}
                    )
                    keyring.fail_on.add(4)
                else:
                    keyring.fail_on.add(2)
                lab_store = GenomiLabStore(
                    Path(temporary) / "lab.sqlite3",
                    key_provider=TEST_LAB_KEY_PROVIDER,
                )
                service = GenomiLabService(
                    store=lab_store,
                    session_id=f"provider-{action}-ambiguous-session",
                    operation_call=lambda _operation, _params: {
                        "active_user_id": "synthetic-user"
                    },
                    provider_credential_store=credential_store,
                )
                try:
                    with self.assertRaises(LabError) as raised:
                        if action == "connect":
                            service.connect_integration(
                                "biohub-esm", {"api_token": "new-secret"}
                            )
                        else:
                            service.disconnect_integration("biohub-esm", confirmed=True)
                    self.assertEqual(
                        raised.exception.code, "credential_store_unavailable"
                    )
                    retained = credential_store.get("biohub-esm")
                    if action == "connect":
                        self.assertIsNone(retained)
                    else:
                        assert retained is not None
                        self.assertEqual(retained["api_token"], "existing-secret")
                    commands = lab_store.list_provider_connection_commands(
                        f"provider-{action}-ambiguous-session"
                    )
                    events = lab_store.list_provider_connection_events(
                        f"provider-{action}-ambiguous-session"
                    )
                    self.assertEqual(
                        commands[0]["result"],
                        {
                            "provider": "biohub-esm",
                            "status": "failed",
                            "error_code": "credential_store_unavailable",
                        },
                    )
                    self.assertEqual(events[0]["payload"], commands[0]["result"])
                    self.assertNotIn("secret", repr([commands, events]))
                finally:
                    service.close()

    def test_unreadable_post_failure_state_never_overwrites_newer_credential(
        self,
    ) -> None:
        class _ConcurrentMutationKeyring(_Keyring):
            def __init__(self) -> None:
                super().__init__()
                self.get_calls = 0

            def get_password(self, service: str, account: str) -> str | None:
                self.get_calls += 1
                if self.get_calls == 2:
                    raise OSError("synthetic post-write read failure")
                if self.get_calls == 3:
                    self.values[(service, account)] = (
                        '{"api_token":"concurrent-secret"}'
                    )
                    raise OSError("synthetic concurrent read failure")
                return super().get_password(service, account)

        with tempfile.TemporaryDirectory() as temporary:
            keyring = _ConcurrentMutationKeyring()
            credential_store = OSKeyringProviderCredentialStore(keyring)
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-concurrent-reconciliation-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=credential_store,
            )
            try:
                with self.assertRaises(LabError) as raised:
                    service.connect_integration(
                        "biohub-esm", {"api_token": "command-secret"}
                    )
                self.assertEqual(
                    raised.exception.code,
                    "provider_connection_reconciliation_required",
                )
                retained = credential_store.get("biohub-esm")
                assert retained is not None
                self.assertEqual(retained["api_token"], "concurrent-secret")
                commands = lab_store.list_provider_connection_commands(
                    "provider-concurrent-reconciliation-session"
                )
                self.assertEqual(
                    commands[0]["result"],
                    {
                        "provider": "biohub-esm",
                        "status": "reconciliation_required",
                        "error_code": "provider_connection_reconciliation_required",
                    },
                )
                self.assertNotIn("secret", repr(commands))
            finally:
                service.close()

    def test_post_success_snapshot_failure_records_and_surfaces_reconciliation(
        self,
    ) -> None:
        class _FailOneReadKeyring(_Keyring):
            def __init__(self) -> None:
                super().__init__()
                self.get_calls = 0
                self.fail_on = 0

            def get_password(self, service: str, account: str) -> str | None:
                self.get_calls += 1
                if self.get_calls == self.fail_on:
                    raise OSError("synthetic post-command snapshot failure")
                return super().get_password(service, account)

        class _PaperclipClient:
            @staticmethod
            def search(*_args: object, **_kwargs: object) -> object:
                return SimpleNamespace(exit_code=0, result_data={"papers": []})

        with tempfile.TemporaryDirectory() as temporary:
            keyring = _FailOneReadKeyring()
            credential_store = OSKeyringProviderCredentialStore(keyring)
            credential_store.replace("paperclip", {"api_key": "gxl-secret"})
            keyring.get_calls = 0
            keyring.fail_on = 5
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-post-success-reconciliation-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=credential_store,
                paperclip_deployment_authorization=_authorization(),
                paperclip_patient_data_contract=_patient_data_contract(),
                paperclip_transport=GxlPaperclipTransport(
                    client_factory=lambda _secret: _PaperclipClient()
                ),
            )
            try:
                with self.assertRaises(LabError) as raised:
                    service.verify_integration("paperclip")
                self.assertEqual(
                    raised.exception.code,
                    "provider_connection_reconciliation_required",
                )
                paperclip = next(
                    item
                    for item in service.integrations()["integrations"]
                    if item["provider"] == "paperclip"
                )
                self.assertEqual(
                    paperclip["connection_state"], "reconciliation_required"
                )
                self.assertEqual(paperclip["investigation_operations"], [])
                self.assertEqual(paperclip["investigation_routes"], [])
                self.assertEqual(paperclip["investigation_purposes"], [])
                self.assertTrue(paperclip["verification_available"])
                self.assertEqual(
                    service.provider_connections.verified_paperclip_api_key(),
                    "",
                )
                command = lab_store.list_provider_connection_commands(
                    "provider-post-success-reconciliation-session"
                )[0]
                self.assertEqual(command["result"]["status"], "reconciliation_required")
                self.assertNotIn("gxl-secret", repr(command))

                recovered = service.verify_integration("paperclip")
                self.assertEqual(recovered["connection_state"], "ready")
                self.assertEqual(
                    lab_store.provider_connection_reconciliation_providers(), ()
                )
            finally:
                service.close()

    def test_restore_cas_race_preserves_newer_credential_as_indeterminate(self) -> None:
        class _ConcurrentRestoreKeyring(_Keyring):
            def __init__(self) -> None:
                super().__init__()
                self.get_calls = 0

            def get_password(self, service: str, account: str) -> str | None:
                self.get_calls += 1
                if self.get_calls == 2:
                    raise OSError("synthetic post-write read failure")
                if self.get_calls == 4:
                    self.values[(service, account)] = (
                        '{"api_token":"concurrent-secret"}'
                    )
                return super().get_password(service, account)

        with tempfile.TemporaryDirectory() as temporary:
            keyring = _ConcurrentRestoreKeyring()
            credential_store = OSKeyringProviderCredentialStore(keyring)
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-cas-reconciliation-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=credential_store,
            )
            try:
                with self.assertRaises(LabError) as raised:
                    service.connect_integration(
                        "biohub-esm", {"api_token": "command-secret"}
                    )
                self.assertEqual(
                    raised.exception.code,
                    "provider_connection_reconciliation_required",
                )
                retained = credential_store.get("biohub-esm")
                assert retained is not None
                self.assertEqual(retained["api_token"], "concurrent-secret")
                command = lab_store.list_provider_connection_commands(
                    "provider-cas-reconciliation-session"
                )[0]
                self.assertEqual(command["result"]["status"], "reconciliation_required")
            finally:
                service.close()

    def test_interrupted_global_intent_surfaces_until_explicit_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            credential_store = OSKeyringProviderCredentialStore(_Keyring())
            lab_store.begin_provider_connection_command(
                workspace_session_id="prior-process-session",
                provider="biohub-esm",
                action="connect",
            )
            credential_store.replace(
                "biohub-esm", {"api_token": "indeterminate-secret"}
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="restarted-process-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=credential_store,
            )
            try:
                before = next(
                    item
                    for item in service.integrations()["integrations"]
                    if item["provider"] == "biohub-esm"
                )
                self.assertEqual(before["connection_state"], "reconciliation_required")
                self.assertEqual(before["investigation_operations"], [])
                self.assertTrue(before["verification_available"])

                service.connect_integration(
                    "biohub-esm", {"api_token": "replacement-secret"}
                )
                after = next(
                    item
                    for item in service.integrations()["integrations"]
                    if item["provider"] == "biohub-esm"
                )
                self.assertEqual(after["connection_state"], "configured_unverified")
                self.assertEqual(
                    lab_store.provider_connection_reconciliation_providers(), ()
                )
            finally:
                service.close()

    def test_connection_reads_wait_for_durable_command_finalization(self) -> None:
        class _PaperclipClient:
            @staticmethod
            def search(*_args: object, **_kwargs: object) -> object:
                return SimpleNamespace(exit_code=0, result_data={"papers": []})

        with tempfile.TemporaryDirectory() as temporary:
            credential_store = OSKeyringProviderCredentialStore(_Keyring())
            credential_store.replace("paperclip", {"api_key": "gxl-secret"})
            lab_store = GenomiLabStore(
                Path(temporary) / "lab.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            service = GenomiLabService(
                store=lab_store,
                session_id="provider-read-serialization-session",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=credential_store,
                paperclip_deployment_authorization=_authorization(),
                paperclip_patient_data_contract=_patient_data_contract(),
                paperclip_transport=GxlPaperclipTransport(
                    client_factory=lambda _secret: _PaperclipClient()
                ),
            )
            entered_finalization = threading.Event()
            allow_finalization = threading.Event()
            reader_finished = threading.Event()
            original_finalize = lab_store.finalize_provider_connection_command

            def delayed_finalize(**kwargs: object) -> None:
                entered_finalization.set()
                if not allow_finalization.wait(2):
                    raise TimeoutError("test finalizer was not released")
                original_finalize(**kwargs)

            lab_store.finalize_provider_connection_command = delayed_finalize  # type: ignore[method-assign]
            verification_thread = threading.Thread(
                target=lambda: service.verify_integration("paperclip")
            )
            observed: dict[str, object] = {}

            def read_connections() -> None:
                observed["integrations"] = service.integrations()
                observed["secret"] = service._paperclip_secret()
                reader_finished.set()

            reader_thread = threading.Thread(target=read_connections)
            try:
                verification_thread.start()
                self.assertTrue(entered_finalization.wait(1))
                reader_thread.start()
                self.assertFalse(reader_finished.wait(0.05))
                allow_finalization.set()
                verification_thread.join(2)
                reader_thread.join(2)
                self.assertFalse(verification_thread.is_alive())
                self.assertFalse(reader_thread.is_alive())
                self.assertEqual(observed["secret"], "gxl-secret")
            finally:
                allow_finalization.set()
                verification_thread.join(2)
                reader_thread.join(2)
                service.close()

    def test_distinct_services_serialize_one_global_provider_account(self) -> None:
        class _BlockingFirstWriteKeyring(_Keyring):
            def __init__(self) -> None:
                super().__init__()
                self._calls_lock = threading.Lock()
                self.set_calls = 0
                self.first_write_entered = threading.Event()
                self.allow_first_write = threading.Event()
                self.second_write_entered = threading.Event()

            def set_password(self, service: str, account: str, value: str) -> None:
                with self._calls_lock:
                    self.set_calls += 1
                    call_number = self.set_calls
                if call_number == 1:
                    self.first_write_entered.set()
                    if not self.allow_first_write.wait(2):
                        raise TimeoutError("first provider write was not released")
                else:
                    self.second_write_entered.set()
                super().set_password(service, account, value)

        self.assertEqual(
            provider_credential_lock_path("biohub-esm"),
            provider_credential_lock_path("biohub-esm"),
        )
        self.assertNotEqual(
            provider_credential_lock_path("biohub-esm"),
            provider_credential_lock_path("paperclip"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            keyring = _BlockingFirstWriteKeyring()
            first_store = GenomiLabStore(
                Path(temporary) / "first.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            second_store = GenomiLabStore(
                Path(temporary) / "second.sqlite3",
                key_provider=TEST_LAB_KEY_PROVIDER,
            )
            first_service = GenomiLabService(
                store=first_store,
                session_id="provider-global-lock-first",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=OSKeyringProviderCredentialStore(keyring),
            )
            second_service = GenomiLabService(
                store=second_store,
                session_id="provider-global-lock-second",
                operation_call=lambda _operation, _params: {
                    "active_user_id": "synthetic-user"
                },
                provider_credential_store=OSKeyringProviderCredentialStore(keyring),
            )
            failures: list[BaseException] = []
            second_started = threading.Event()

            def connect_first() -> None:
                try:
                    first_service.connect_integration(
                        "biohub-esm", {"api_token": "first-secret"}
                    )
                except BaseException as exc:
                    failures.append(exc)

            def connect_second() -> None:
                second_started.set()
                try:
                    second_service.connect_integration(
                        "biohub-esm", {"api_token": "second-secret"}
                    )
                except BaseException as exc:
                    failures.append(exc)

            first_thread = threading.Thread(target=connect_first)
            second_thread = threading.Thread(target=connect_second)
            try:
                first_thread.start()
                self.assertTrue(keyring.first_write_entered.wait(1))
                second_thread.start()
                self.assertTrue(second_started.wait(1))
                self.assertFalse(keyring.second_write_entered.wait(0.1))
                keyring.allow_first_write.set()
                first_thread.join(3)
                second_thread.join(3)
                self.assertFalse(first_thread.is_alive())
                self.assertFalse(second_thread.is_alive())
                self.assertEqual(failures, [])
                retained = OSKeyringProviderCredentialStore(keyring).get("biohub-esm")
                assert retained is not None
                self.assertEqual(retained["api_token"], "second-secret")
                self.assertEqual(
                    first_store.provider_connection_reconciliation_providers(), ()
                )
                self.assertEqual(
                    second_store.provider_connection_reconciliation_providers(), ()
                )
            finally:
                keyring.allow_first_write.set()
                first_thread.join(3)
                second_thread.join(3)
                first_service.close()
                second_service.close()


if __name__ == "__main__":
    unittest.main()
