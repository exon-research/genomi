from __future__ import annotations

import unittest

from genomi.lab.paperclip_adapter import PaperclipAdapter, PaperclipOperation
from genomi.lab.evidence_types import EvidenceStatus
from genomi.lab.provider_policy import (
    AuthorizationBasis,
    DeploymentAuthorization,
    EvidenceRequest,
    PAPERCLIP_PROVIDER,
    SourceFamily,
    disclosure_fingerprint,
)


class PaperclipAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = EvidenceRequest(
            query="synthetic disease mechanism",
            source_family=SourceFamily.LITERATURE,
            purpose="Build an evidence packet",
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

    def test_default_live_state_is_hard_disabled_and_exposes_no_escape_hatch(self) -> None:
        manifest = PaperclipAdapter().capability_manifest().to_dict()
        self.assertEqual(manifest["live_state"], "hard_disabled")
        self.assertEqual(
            set(manifest["operations"]),
            {operation.value for operation in PaperclipOperation},
        )
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

    def test_direct_source_and_fixture_are_typed_fallbacks(self) -> None:
        direct_calls: list[PaperclipOperation] = []
        direct = PaperclipAdapter().retrieve(
            operation=PaperclipOperation.LOOKUP,
            request=self.request,
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

    def test_authorized_public_live_call_uses_only_the_explicit_secret_provider(self) -> None:
        calls: list[object] = []
        deployment = DeploymentAuthorization(
            provider=PAPERCLIP_PROVIDER,
            authorization_id="written-authorization-1",
            basis=AuthorizationBasis.WRITTEN_PROVIDER_AUTHORIZATION,
            permitted_source_families=frozenset({SourceFamily.LITERATURE}),
        )
        adapter = PaperclipAdapter(
            deployment_authorization=deployment,
            secret_provider=lambda: calls.append("secret") or "explicit-credential",
            live_transport=lambda operation, request, credential: (
                calls.append((operation, request, credential)) or self.response
            ),
        )
        result = adapter.retrieve(
            operation=PaperclipOperation.READ_EXTRACT, request=self.request
        )
        self.assertEqual(result.status, EvidenceStatus.DATA_RETURNED)
        self.assertEqual(calls[0], "secret")
        self.assertEqual(calls[1][2], "explicit-credential")

    def test_patient_query_does_not_fall_back_to_direct_network_without_egress_approval(self) -> None:
        patient_request = EvidenceRequest(
            query="patient finding and synthetic disease",
            source_family=SourceFamily.LITERATURE,
            purpose="Patient investigation",
            patient_influenced=True,
        )
        direct_calls: list[object] = []
        result = PaperclipAdapter().retrieve(
            operation=PaperclipOperation.SEARCH,
            request=patient_request,
            direct_source_provider="pubmed",
            direct_source_transport=lambda *args: direct_calls.append(args) or self.response,
        )
        self.assertEqual(result.status, EvidenceStatus.BLOCKED_BY_POLICY)
        self.assertEqual(direct_calls, [])
        self.assertNotEqual(
            disclosure_fingerprint(PAPERCLIP_PROVIDER, patient_request),
            disclosure_fingerprint(PAPERCLIP_PROVIDER, self.request),
        )


if __name__ == "__main__":
    unittest.main()
