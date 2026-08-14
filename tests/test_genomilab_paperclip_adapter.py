from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from genomi.lab.paperclip_adapter import PaperclipAdapter, PaperclipOperation
from genomi.lab.evidence_types import EvidenceStatus
from genomi.lab.provider_policy import (
    AuthorizationBasis,
    DeploymentAuthorization,
    EvidenceDataClass,
    EvidenceRequest,
    PAPERCLIP_PROVIDER,
    PatientDataContract,
    SourceFamily,
    disclosure_fingerprint,
)


POLICY_EFFECTIVE_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)
POLICY_EXPIRES_AT = datetime(2100, 1, 1, tzinfo=timezone.utc)
ADAPTER_PURPOSES = frozenset({"Build an evidence packet", "Patient investigation"})
ADAPTER_OPERATIONS = frozenset({"search", "lookup", "read_extract"})


def _deployment_authorization(
    permitted_source_families: frozenset[SourceFamily],
    *,
    authorization_id: str = "written-authorization-1",
) -> DeploymentAuthorization:
    return DeploymentAuthorization(
        provider=PAPERCLIP_PROVIDER,
        authorization_id=authorization_id,
        basis=AuthorizationBasis.WRITTEN_PROVIDER_AUTHORIZATION,
        permitted_source_families=permitted_source_families,
        permitted_operations=ADAPTER_OPERATIONS,
        permitted_purposes=ADAPTER_PURPOSES,
        permitted_data_classes=frozenset(EvidenceDataClass),
        effective_at=POLICY_EFFECTIVE_AT,
        expires_at=POLICY_EXPIRES_AT,
        revoked_at=None,
        policy_version_id="paperclip-policy-2026-08",
        terms_version_id="paperclip-terms-2026-08",
        privacy_version_id="paperclip-privacy-2026-08",
        aup_version_id="paperclip-aup-2026-08",
        live_use_authorized=True,
    )


def _patient_data_contract(
    permitted_source_families: frozenset[SourceFamily],
    *,
    contract_id: str = "independent-patient-contract-1",
    authorized: bool = True,
) -> PatientDataContract:
    return PatientDataContract(
        provider=PAPERCLIP_PROVIDER,
        contract_id=contract_id,
        permitted_source_families=permitted_source_families,
        permitted_operations=ADAPTER_OPERATIONS,
        permitted_purposes=ADAPTER_PURPOSES,
        permitted_data_classes=frozenset(EvidenceDataClass),
        effective_at=POLICY_EFFECTIVE_AT,
        expires_at=POLICY_EXPIRES_AT,
        revoked_at=None,
        policy_version_id="patient-data-policy-2026-08",
        terms_version_id="patient-data-terms-2026-08",
        privacy_version_id="patient-data-privacy-2026-08",
        aup_version_id="patient-data-aup-2026-08",
        patient_influenced_data_authorized=authorized,
    )


class PaperclipAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = EvidenceRequest(
            query="synthetic disease mechanism",
            source_family=SourceFamily.LITERATURE,
            purpose="Build an evidence packet",
            operation="search",
        )
        self.response = {
            "status": "data_returned",
            "source_family": "literature",
            "records": [
                {
                    "source_id": "PMID:123",
                    "title": "Synthetic source",
                    "source_document_state": "abstract_only",
                }
            ],
        }

    def test_default_live_state_is_hard_disabled_and_exposes_no_escape_hatch(
        self,
    ) -> None:
        manifest = PaperclipAdapter().capability_manifest().to_dict()
        self.assertEqual(manifest["live_state"], "hard_disabled")
        self.assertEqual(manifest["operations"], [])
        self.assertEqual(manifest["source_families"], [])
        self.assertFalse(manifest["arbitrary_execute_available"])
        self.assertFalse(manifest["ambient_credentials_allowed"])

    def test_blocked_live_path_never_reads_a_secret_or_invokes_transport(self) -> None:
        calls: list[str] = []

        adapter = PaperclipAdapter(
            secret_provider=lambda: calls.append("secret") or "credential",
            live_transport=lambda *_: calls.append("network") or self.response,
        )
        result = adapter.retrieve(
            operation=PaperclipOperation.SEARCH, request=self.request
        )
        self.assertEqual(result.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(calls, [])

    def test_manifest_reports_only_deployed_operations_and_actual_key_state(
        self,
    ) -> None:
        adapter = PaperclipAdapter(
            deployment_authorization=_deployment_authorization(
                frozenset({SourceFamily.LITERATURE})
            ),
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.LITERATURE})
            ),
            secret_provider=lambda: "credential",
            credential_configured=lambda: False,
            live_transport=lambda *_: self.response,
            live_routes={
                SourceFamily.LITERATURE: (
                    PaperclipOperation.SEARCH,
                    PaperclipOperation.LOOKUP,
                )
            },
        )
        manifest = adapter.capability_manifest().to_dict()
        self.assertEqual(manifest["live_state"], "authorized_unavailable")
        self.assertEqual(manifest["operations"], ["search", "lookup"])
        self.assertEqual(manifest["source_families"], ["literature"])

        unavailable = adapter.retrieve(
            operation=PaperclipOperation.READ_EXTRACT,
            request=replace(self.request, operation="read_extract"),
        )
        self.assertEqual(unavailable.status, EvidenceStatus.OUT_OF_SCOPE_FOR_INPUT)

    def test_stored_key_is_not_an_authorized_route_until_connection_is_ready(
        self,
    ) -> None:
        deployment = _deployment_authorization(frozenset({SourceFamily.LITERATURE}))
        adapter = PaperclipAdapter(
            deployment_authorization=deployment,
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.LITERATURE})
            ),
            secret_provider=lambda: "credential",
            credential_configured=lambda: True,
            connection_ready=lambda: False,
            live_transport=lambda *_: self.response,
            live_routes={SourceFamily.LITERATURE: (PaperclipOperation.SEARCH,)},
        )
        self.assertEqual(
            adapter.capability_manifest().live_state, "authorized_unavailable"
        )

    def test_injected_transport_without_explicit_routes_or_readiness_stays_closed(
        self,
    ) -> None:
        calls: list[str] = []
        adapter = PaperclipAdapter(
            deployment_authorization=_deployment_authorization(
                frozenset({SourceFamily.LITERATURE})
            ),
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.LITERATURE})
            ),
            secret_provider=lambda: calls.append("secret") or "credential",
            live_transport=lambda *_: calls.append("network") or self.response,
        )

        result = adapter.retrieve(
            operation=PaperclipOperation.SEARCH,
            request=self.request,
        )

        self.assertEqual(result.status, EvidenceStatus.OUT_OF_SCOPE_FOR_INPUT)
        self.assertEqual(adapter.capability_manifest().operations, ())
        self.assertEqual(calls, [])

    def test_patient_manifest_has_no_routes_without_an_independent_contract(
        self,
    ) -> None:
        deployment = _deployment_authorization(frozenset({SourceFamily.LITERATURE}))
        invalid_contracts = (
            None,
            _patient_data_contract(
                frozenset({SourceFamily.LITERATURE}),
                contract_id=deployment.authorization_id,
            ),
            _patient_data_contract(
                frozenset({SourceFamily.LITERATURE}),
                contract_id="disabled-patient-contract",
                authorized=False,
            ),
        )
        for contract in invalid_contracts:
            with self.subTest(contract=contract):
                adapter = PaperclipAdapter(
                    deployment_authorization=deployment,
                    patient_data_contract=contract,
                    secret_provider=lambda: "credential",
                    credential_configured=lambda: True,
                    connection_ready=lambda: True,
                    live_transport=lambda *_: self.response,
                    live_routes={SourceFamily.LITERATURE: (PaperclipOperation.SEARCH,)},
                )

                manifest = adapter.capability_manifest().to_dict()
                self.assertEqual(manifest["live_state"], "authorized_unavailable")
                self.assertEqual(manifest["operations"], [])
                self.assertEqual(manifest["source_families"], [])
                self.assertEqual(manifest["routes"], [])
                self.assertEqual(manifest["purposes"], [])

    def test_patient_manifest_intersects_narrow_contract_and_deployment_routes(
        self,
    ) -> None:
        adapter = PaperclipAdapter(
            deployment_authorization=_deployment_authorization(
                frozenset(
                    {
                        SourceFamily.LITERATURE,
                        SourceFamily.REGULATORY,
                        SourceFamily.TRIAL_REGISTRY,
                    }
                )
            ),
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.REGULATORY})
            ),
            secret_provider=lambda: "credential",
            credential_configured=lambda: True,
            connection_ready=lambda: True,
            live_transport=lambda *_: self.response,
            live_routes={
                SourceFamily.LITERATURE: (
                    PaperclipOperation.SEARCH,
                    PaperclipOperation.LOOKUP,
                ),
                SourceFamily.REGULATORY: (PaperclipOperation.SEARCH,),
                SourceFamily.TRIAL_REGISTRY: (PaperclipOperation.SEARCH,),
            },
        )

        manifest = adapter.capability_manifest().to_dict()
        self.assertEqual(manifest["live_state"], "authorized")
        self.assertEqual(manifest["operations"], ["search"])
        self.assertEqual(manifest["source_families"], ["regulatory"])
        self.assertEqual(
            manifest["routes"],
            [{"source_family": "regulatory", "operations": ["search"]}],
        )

    def test_patient_manifest_intersects_exact_operation_scopes(self) -> None:
        search_only = frozenset({"search"})
        adapter = PaperclipAdapter(
            deployment_authorization=replace(
                _deployment_authorization(frozenset({SourceFamily.LITERATURE})),
                permitted_operations=search_only,
                permitted_purposes=frozenset(
                    {"Build an evidence packet", "Deployment-only purpose"}
                ),
            ),
            patient_data_contract=replace(
                _patient_data_contract(frozenset({SourceFamily.LITERATURE})),
                permitted_operations=search_only,
                permitted_purposes=frozenset(
                    {"Build an evidence packet", "Contract-only purpose"}
                ),
            ),
            secret_provider=lambda: "credential",
            credential_configured=lambda: True,
            connection_ready=lambda: True,
            live_transport=lambda *_: self.response,
            live_routes={
                SourceFamily.LITERATURE: (
                    PaperclipOperation.SEARCH,
                    PaperclipOperation.LOOKUP,
                )
            },
        )

        manifest = adapter.capability_manifest().to_dict()

        self.assertEqual(manifest["operations"], ["search"])
        self.assertEqual(
            manifest["routes"],
            [{"source_family": "literature", "operations": ["search"]}],
        )
        self.assertEqual(manifest["purposes"], ["Build an evidence packet"])

    def test_patient_manifest_requires_current_exact_full_policy_scope(self) -> None:
        now = datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc)
        deployment = _deployment_authorization(frozenset({SourceFamily.LITERATURE}))
        contract = _patient_data_contract(frozenset({SourceFamily.LITERATURE}))
        blocked_policies = {
            "expired_deployment": (replace(deployment, expires_at=now), contract),
            "revoked_deployment": (replace(deployment, revoked_at=now), contract),
            "expired_contract": (deployment, replace(contract, expires_at=now)),
            "revoked_contract": (deployment, replace(contract, revoked_at=now)),
            "wrong_purpose": (
                replace(
                    deployment,
                    permitted_purposes=frozenset({"Build an evidence packet"}),
                ),
                replace(
                    contract,
                    permitted_purposes=frozenset({"Patient investigation"}),
                ),
            ),
            "wrong_data_class": (
                deployment,
                replace(
                    contract,
                    permitted_data_classes=frozenset({EvidenceDataClass.PUBLIC_QUERY}),
                ),
            ),
            "wrong_operation": (
                replace(
                    deployment,
                    permitted_operations=frozenset({"read_extract"}),
                ),
                contract,
            ),
        }
        for name, (blocked_deployment, blocked_contract) in blocked_policies.items():
            with self.subTest(name=name):
                manifest = (
                    PaperclipAdapter(
                        deployment_authorization=blocked_deployment,
                        patient_data_contract=blocked_contract,
                        secret_provider=lambda: "credential",
                        credential_configured=lambda: True,
                        connection_ready=lambda: True,
                        live_transport=lambda *_: self.response,
                        live_routes={
                            SourceFamily.LITERATURE: (
                                PaperclipOperation.SEARCH,
                                PaperclipOperation.LOOKUP,
                            )
                        },
                        clock=lambda: now,
                    )
                    .capability_manifest()
                    .to_dict()
                )

                self.assertEqual(manifest["operations"], [])
                self.assertEqual(manifest["source_families"], [])
                self.assertEqual(manifest["routes"], [])
                self.assertEqual(manifest["purposes"], [])

    def test_patient_manifest_respects_narrow_deployment_route_scope(self) -> None:
        adapter = PaperclipAdapter(
            deployment_authorization=_deployment_authorization(
                frozenset({SourceFamily.LITERATURE})
            ),
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.LITERATURE, SourceFamily.REGULATORY})
            ),
            secret_provider=lambda: "credential",
            credential_configured=lambda: True,
            connection_ready=lambda: True,
            live_transport=lambda *_: self.response,
            live_routes={
                SourceFamily.LITERATURE: (
                    PaperclipOperation.SEARCH,
                    PaperclipOperation.LOOKUP,
                ),
                SourceFamily.REGULATORY: (PaperclipOperation.SEARCH,),
            },
        )

        manifest = adapter.capability_manifest().to_dict()
        self.assertEqual(manifest["operations"], ["search", "lookup"])
        self.assertEqual(manifest["source_families"], ["literature"])
        self.assertEqual(
            manifest["routes"],
            [
                {
                    "source_family": "literature",
                    "operations": ["search", "lookup"],
                }
            ],
        )

    def test_direct_source_and_fixture_are_typed_fallbacks(self) -> None:
        direct_calls: list[PaperclipOperation] = []
        direct = PaperclipAdapter().retrieve(
            operation=PaperclipOperation.LOOKUP,
            request=replace(self.request, operation="lookup"),
            direct_source_provider="pubmed",
            direct_source_transport=lambda operation, _request: (
                direct_calls.append(operation) or self.response
            ),
        )
        self.assertEqual(direct.status, EvidenceStatus.DATA_RETURNED)
        self.assertEqual(direct.provider, "pubmed")
        self.assertEqual(direct_calls, [PaperclipOperation.LOOKUP])

        fixture = PaperclipAdapter().retrieve(
            operation=PaperclipOperation.SEARCH,
            request=self.request,
            fixture=self.response,
        )
        self.assertEqual(fixture.status, EvidenceStatus.DATA_RETURNED)
        self.assertEqual(fixture.provider, "fixture")

    def test_operation_mismatch_never_reaches_any_route_or_job_transport(self) -> None:
        calls: list[object] = []
        adapter = PaperclipAdapter(
            deployment_authorization=_deployment_authorization(
                frozenset({SourceFamily.LITERATURE})
            ),
            patient_data_contract=_patient_data_contract(
                frozenset({SourceFamily.LITERATURE})
            ),
            secret_provider=lambda: calls.append("secret") or "credential",
            credential_configured=lambda: True,
            connection_ready=lambda: True,
            live_transport=lambda *args: calls.append(("live", args)) or self.response,
            live_job_transport=lambda *args: (
                calls.append(("job", args)) or self.response
            ),
            live_routes={SourceFamily.LITERATURE: (PaperclipOperation.LOOKUP,)},
        )

        result = adapter.retrieve(
            operation=PaperclipOperation.LOOKUP,
            request=self.request,
            direct_source_provider="pubmed",
            direct_source_transport=lambda *args: (
                calls.append(("direct", args)) or self.response
            ),
            fixture=self.response,
        )
        resumed = adapter.resume_live_job(
            operation=PaperclipOperation.LOOKUP,
            request=self.request,
            job_id="paperclip-job-1",
            resume_operation="paperclip.check_background_job",
            approved=True,
        )
        string_approval = adapter.resume_live_job(
            operation=PaperclipOperation.SEARCH,
            request=replace(self.request, patient_influenced=True),
            job_id="paperclip-job-2",
            resume_operation="paperclip.check_background_job",
            approved="false",  # type: ignore[arg-type]
        )

        self.assertEqual(result.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(
            result.policy.state.value, "blocked_request_operation_mismatch"
        )
        self.assertEqual(resumed.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(
            resumed.policy.state.value, "blocked_request_operation_mismatch"
        )
        self.assertEqual(string_approval.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(
            string_approval.policy.state.value,
            "blocked_missing_exact_disclosure_approval",
        )
        self.assertEqual(calls, [])

    def test_authorized_public_live_call_requires_an_explicit_route_and_ready_state(
        self,
    ) -> None:
        calls: list[object] = []
        deployment = _deployment_authorization(frozenset({SourceFamily.LITERATURE}))
        adapter = PaperclipAdapter(
            deployment_authorization=deployment,
            secret_provider=lambda: calls.append("secret") or "explicit-credential",
            credential_configured=lambda: True,
            connection_ready=lambda: True,
            live_transport=lambda operation, request, credential: (
                calls.append((operation, request, credential)) or self.response
            ),
            live_routes={SourceFamily.LITERATURE: (PaperclipOperation.SEARCH,)},
        )
        result = adapter.retrieve(
            operation=PaperclipOperation.SEARCH, request=self.request
        )
        self.assertEqual(result.status, EvidenceStatus.DATA_RETURNED)
        self.assertEqual(calls[0], "secret")
        self.assertEqual(calls[1][2], "explicit-credential")

        refused = adapter.retrieve(
            operation=PaperclipOperation.READ_EXTRACT,
            request=replace(self.request, operation="read_extract"),
        )
        self.assertEqual(refused.status, EvidenceStatus.OUT_OF_SCOPE_FOR_INPUT)

    def test_patient_query_does_not_fall_back_to_direct_network_without_egress_approval(
        self,
    ) -> None:
        patient_request = EvidenceRequest(
            query="patient finding and synthetic disease",
            source_family=SourceFamily.LITERATURE,
            purpose="Patient investigation",
            operation="search",
            patient_influenced=True,
        )
        direct_calls: list[object] = []
        result = PaperclipAdapter().retrieve(
            operation=PaperclipOperation.SEARCH,
            request=patient_request,
            direct_source_provider="pubmed",
            direct_source_transport=lambda *args: (
                direct_calls.append(args) or self.response
            ),
        )
        self.assertEqual(result.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(direct_calls, [])
        self.assertNotEqual(
            disclosure_fingerprint(PAPERCLIP_PROVIDER, patient_request),
            disclosure_fingerprint(PAPERCLIP_PROVIDER, self.request),
        )


if __name__ == "__main__":
    unittest.main()
