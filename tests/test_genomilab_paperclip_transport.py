from __future__ import annotations

import unittest
import os
import sys
from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest import mock

from genomi.lab import paperclip_transport as paperclip_transport_module
from genomi.lab.evidence_normalization import normalize_evidence_response
from genomi.lab.evidence_types import EvidenceStatus, ProviderTransportError
from genomi.lab.paperclip_adapter import PaperclipOperation
from genomi.lab.paperclip_transport import GxlPaperclipTransport
from genomi.lab.provider_policy import AccessMode, EvidenceRequest, SourceFamily


@dataclass(frozen=True)
class _Result:
    papers: tuple[dict[str, object], ...]
    result_id: str = "s_synthetic"
    exit_code: int = 0

    @property
    def result_data(self) -> dict[str, object]:
        return {"papers": list(self.papers)}


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def search(self, query: str, **kwargs: object) -> _Result:
        self.calls.append(("search", (query, kwargs)))
        return _Result(
            (
                {
                    "document_id": "PMC123",
                    "title": "Synthetic evidence record",
                    "doi": "10.1000/synthetic",
                    "pmid": "123",
                    "url": "https://example.org/PMC123",
                    "source": "pmc",
                    "publication_date": "2026-01-02",
                },
            )
        )

    def lookup(self, field: str, value: str, **kwargs: object) -> _Result:
        self.calls.append(("lookup", (field, value, kwargs)))
        return _Result(
            (
                {
                    "document_id": "PMC456",
                    "title": "Canonical lookup evidence record",
                    "doi": "10.1000/synthetic",
                    "pmid": "456",
                    "url": "https://example.org/PMC456",
                    "source": "pmc",
                    "publication_date": "2026-02-03",
                },
            ),
            result_id="l_synthetic",
        )


class PaperclipTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _Client()
        self.secrets: list[str] = []
        self.transport = GxlPaperclipTransport(
            client_factory=lambda secret: self.secrets.append(secret) or self.client
        )
        self.request = EvidenceRequest(
            query="synthetic disease mechanism",
            source_family=SourceFamily.LITERATURE,
            purpose="Build an evidence packet",
            operation="search",
        )

    def test_probe_and_search_use_explicit_secret_and_structured_papers(self) -> None:
        self.transport.probe("explicit-key")
        raw = self.transport(PaperclipOperation.SEARCH, self.request, "explicit-key")

        self.assertEqual(self.secrets, ["explicit-key", "explicit-key"])
        probe_call = self.client.calls[0][1]
        self.assertEqual(probe_call[0], "TP53")
        self.assertEqual(probe_call[1]["source"], "pmc")
        self.assertEqual(probe_call[1]["limit"], 1)
        self.assertEqual(probe_call[1]["timeout"], 15.0)
        search_call = self.client.calls[1][1]
        self.assertEqual(search_call[1]["source"], "pmc,biorxiv,medrxiv,arxiv")
        self.assertEqual(raw["status"], "data_returned")
        self.assertEqual(
            raw["process_provenance"]["provider_result_ids"], ["s_synthetic"]
        )
        self.assertEqual(raw["process_provenance"]["provider_version"], "0.4.2")
        self.assertEqual(
            raw["process_provenance"]["provider_repository"],
            "https://github.com/GXL-ai/paperclip",
        )
        self.assertEqual(
            raw["process_provenance"]["provider_commit"],
            "b5571365f0b36847dce42c5d66d2b158a0f871f9",
        )
        self.assertTrue(raw["process_provenance"]["retrieved_at"].endswith("Z"))
        self.assertEqual(
            raw["coverage"]["consulted"],
            ["pmc", "biorxiv", "medrxiv", "arxiv"],
        )
        record = raw["records"][0]
        self.assertEqual(record["source_id"], "PMC123")
        self.assertEqual(record["title"], "Synthetic evidence record")
        self.assertNotIn("excerpt", record)
        self.assertNotIn("output", raw)

    def test_no_hit_preserves_every_query_result_id_and_consulted_corpus(
        self,
    ) -> None:
        class EmptyClient:
            def search(self, query: str, **_kwargs: object) -> _Result:
                return _Result((), result_id=f"result-{query.replace(' ', '-')}")

        request = EvidenceRequest(
            query="first no hit",
            query_terms=("first no hit", "second no hit"),
            source_family=SourceFamily.LITERATURE,
            purpose="Audit a no-hit literature search",
            operation="search",
        )
        raw = GxlPaperclipTransport(client_factory=lambda _secret: EmptyClient())(
            PaperclipOperation.SEARCH, request, "explicit-key"
        )
        normalized_result = normalize_evidence_response(
            provider="paperclip",
            access_mode=AccessMode.LIVE_PROVIDER,
            request=request,
            raw=raw,
        )
        normalized = normalized_result.to_dict()

        self.assertEqual(normalized["status"], "in_scope_empty")
        self.assertEqual(
            normalized["coverage"]["consulted"],
            ["pmc", "biorxiv", "medrxiv", "arxiv"],
        )
        self.assertEqual(
            normalized["coverage"]["misses"],
            ["first no hit", "second no hit"],
        )
        self.assertEqual(
            normalized["process_provenance"]["provider_result_ids"],
            ["result-first-no-hit", "result-second-no-hit"],
        )
        self.assertEqual(normalized["process_provenance"]["provider_version"], "0.4.2")
        self.assertTrue(normalized["process_provenance"]["retrieved_at"].endswith("Z"))
        self.assertEqual(
            normalized_result.attempt().to_dict()["process_provenance"][
                "provider_result_ids"
            ],
            ["result-first-no-hit", "result-second-no-hit"],
        )

    def test_non_literature_no_hit_reports_the_exact_provider_corpus(self) -> None:
        class EmptyClient:
            def search(self, *_args: object, **_kwargs: object) -> _Result:
                return _Result((), result_id="result-empty")

        transport = GxlPaperclipTransport(client_factory=lambda _secret: EmptyClient())
        expected = {
            SourceFamily.REGULATORY: ["fda"],
            SourceFamily.TRIAL_REGISTRY: ["trials"],
        }
        for family, corpora in expected.items():
            with self.subTest(family=family):
                request = EvidenceRequest(
                    query="synthetic no hit",
                    source_family=family,
                    purpose="Audit the source scope",
                    operation="search",
                )
                raw = transport(PaperclipOperation.SEARCH, request, "explicit-key")
                self.assertEqual(raw["status"], "in_scope_empty")
                self.assertEqual(raw["coverage"]["consulted"], corpora)

    def test_lookup_requires_an_allowlisted_typed_field(self) -> None:
        unsupported = self.transport(
            PaperclipOperation.LOOKUP,
            replace(self.request, operation="lookup"),
            "explicit-key",
        )
        self.assertEqual(unsupported["status"], "out_of_scope_for_input")
        self.assertEqual(self.client.calls, [])

        typed = EvidenceRequest(
            query="10.1000/synthetic",
            source_family=SourceFamily.LITERATURE,
            purpose="Resolve a publication",
            operation="lookup",
            filters={"lookup_field": "doi"},
        )
        raw = self.transport(PaperclipOperation.LOOKUP, typed, "explicit-key")
        self.assertEqual(raw["status"], "data_returned")
        self.assertEqual(raw["records"][0]["source_id"], "PMC456")
        self.assertEqual(raw["records"][0]["provider_result_id"], "l_synthetic")
        normalized = normalize_evidence_response(
            provider="paperclip",
            access_mode=AccessMode.LIVE_PROVIDER,
            request=typed,
            raw=raw,
        )
        self.assertEqual(
            normalized.records[0].provenance.original_source_id,
            "PMC456",
        )
        self.assertEqual(self.client.calls[0][0], "lookup")

    def test_lookup_and_search_refuse_source_families_the_sdk_cannot_scope(
        self,
    ) -> None:
        for family in (SourceFamily.UNIPROT, SourceFamily.PDB, SourceFamily.CHEMBL):
            with self.subTest(family=family):
                request = EvidenceRequest(
                    query="synthetic record",
                    source_family=family,
                    purpose="Check a structured source",
                    operation="search",
                )
                raw = self.transport(PaperclipOperation.SEARCH, request, "explicit-key")
                self.assertEqual(raw["status"], "out_of_scope_for_input")
        trial_lookup = EvidenceRequest(
            query="NCT00000000",
            source_family=SourceFamily.TRIAL_REGISTRY,
            purpose="Resolve a trial",
            operation="lookup",
            filters={"lookup_field": "title"},
        )
        raw = self.transport(PaperclipOperation.LOOKUP, trial_lookup, "explicit-key")
        self.assertEqual(raw["status"], "out_of_scope_for_input")
        self.assertEqual(self.client.calls, [])

    def test_structured_rows_require_document_id_and_matching_source_family(
        self,
    ) -> None:
        invalid_rows = (
            {
                "id": "PMC123",
                "title": "Legacy alias must not be treated as the upstream ID",
                "source": "pmc",
            },
            {
                "document_id": "FDA123",
                "title": "Regulatory row in a literature response",
                "source": "fda",
            },
        )

        for row in invalid_rows:
            with self.subTest(row=row):
                result = SimpleNamespace(
                    exit_code=0,
                    result_id="s_invalid",
                    result_data={"papers": [row]},
                )

                class Client:
                    def search(self, *_args: object, **_kwargs: object) -> object:
                        return result

                transport = GxlPaperclipTransport(
                    client_factory=lambda _secret: Client()
                )
                with self.assertRaises(ProviderTransportError) as raised:
                    transport(
                        PaperclipOperation.SEARCH,
                        self.request,
                        "explicit-key",
                    )
                self.assertEqual(raised.exception.status, EvidenceStatus.SERVER_ERROR)

    def test_probe_requires_a_structured_authenticated_search_result(self) -> None:
        class Client:
            def search(self, *_args: object, **_kwargs: object) -> object:
                return object()

        transport = GxlPaperclipTransport(client_factory=lambda _secret: Client())
        with self.assertRaises(ProviderTransportError) as raised:
            transport.probe("explicit-key")
        self.assertEqual(raised.exception.status, EvidenceStatus.SERVER_ERROR)

    def test_failed_or_unstructured_execute_result_is_never_an_empty_search(
        self,
    ) -> None:
        class Client:
            def __init__(self, result: object) -> None:
                self.result = result

            def search(self, *_args: object, **_kwargs: object) -> object:
                return self.result

        failures = (
            SimpleNamespace(exit_code=1, result_data={"papers": []}),
            SimpleNamespace(exit_code=0, result_data=None, papers=[]),
            SimpleNamespace(exit_code=0, result_data={}),
        )
        for failure in failures:
            with self.subTest(failure=failure):
                transport = GxlPaperclipTransport(
                    client_factory=lambda _secret, result=failure: Client(result)
                )
                with self.assertRaises(ProviderTransportError) as raised:
                    transport(PaperclipOperation.SEARCH, self.request, "explicit-key")
                self.assertEqual(raised.exception.status, EvidenceStatus.SERVER_ERROR)

    def test_search_applies_allowlisted_filters_and_consults_every_query_term(
        self,
    ) -> None:
        class Client(_Client):
            def search(self, query: str, **kwargs: object) -> _Result:
                self.calls.append(("search", (query, kwargs)))
                return (
                    _Result(())
                    if query == "second term"
                    else super().search(query, **kwargs)
                )

        client = Client()
        transport = GxlPaperclipTransport(client_factory=lambda _secret: client)
        request = EvidenceRequest(
            query="first term",
            query_terms=("first term", "second term"),
            source_family=SourceFamily.LITERATURE,
            purpose="Build an evidence packet",
            operation="search",
            filters={"year": "2026", "exact": "true"},
        )

        raw = transport(PaperclipOperation.SEARCH, request, "explicit-key")

        search_calls = [call[1] for call in client.calls if call[0] == "search"]
        self.assertEqual(
            [call[0] for call in search_calls],
            ["first term", "first term", "second term"],
        )
        self.assertEqual(search_calls[0][1]["year"], "2026")
        self.assertIs(search_calls[0][1]["exact"], True)
        self.assertEqual(raw["coverage"]["misses"], ["second term"])

    def test_unsupported_filter_is_out_of_scope_before_client_creation(self) -> None:
        request = EvidenceRequest(
            query="synthetic disease mechanism",
            source_family=SourceFamily.LITERATURE,
            purpose="Build an evidence packet",
            operation="search",
            filters={"publication_type": "review"},
        )
        raw = self.transport(PaperclipOperation.SEARCH, request, "explicit-key")
        self.assertEqual(raw["status"], "out_of_scope_for_input")
        self.assertEqual(self.secrets, [])

    def test_official_client_pins_endpoint_despite_ambient_override(self) -> None:
        calls: list[dict[str, object]] = []

        class APIKeyAuth:
            def __init__(self, secret: str) -> None:
                self.secret = secret

        def client(**kwargs: object) -> object:
            calls.append(kwargs)
            return object()

        module = SimpleNamespace(APIKeyAuth=APIKeyAuth, PaperclipClient=client)
        with (
            mock.patch.dict(sys.modules, {"gxl_paperclip": module}),
            mock.patch.dict(
                os.environ,
                {"PAPERCLIP_BASE_URL": "https://attacker.invalid"},
            ),
        ):
            paperclip_transport_module._official_client("explicit-key")

        self.assertEqual(calls[0]["base_url"], "https://paperclip.gxl.ai")

    def test_non_typed_paperclip_operations_are_refused_before_client_creation(
        self,
    ) -> None:
        for operation in (
            PaperclipOperation.READ_EXTRACT,
            PaperclipOperation.INSPECT_FIGURE,
            PaperclipOperation.VERIFY_CLAIM,
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "not allowlisted"):
                    self.transport(
                        operation,
                        replace(self.request, operation=operation.value),
                        "explicit-key",
                    )
        self.assertEqual(self.secrets, [])

    def test_provider_errors_are_reduced_without_secret_or_body_leakage(self) -> None:
        class AuthError(Exception):
            pass

        def fail(_secret: str) -> object:
            raise AuthError("provider body contains explicit-key")

        transport = GxlPaperclipTransport(client_factory=fail)
        with self.assertRaises(ProviderTransportError) as raised:
            transport.probe("explicit-key")
        self.assertEqual(raised.exception.status, EvidenceStatus.AUTHENTICATION_FAILED)
        self.assertNotIn("explicit-key", str(raised.exception))
        self.assertNotIn("provider body", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
