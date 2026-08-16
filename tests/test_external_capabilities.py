from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from genomi.capabilities.biohub.esmc import compare_protein_embeddings
from genomi.capabilities.paperclip.read import retrieve_document_evidence
from genomi.capabilities.paperclip.search import search_biomedical
from genomi.capabilities.proto.tools import run_tool, search_tools
from genomi.evidence import envelope as evidence_envelope
from genomi.operations.registry.table import call_operation, list_operations
from genomi.runtime.external_credentials import external_credential_session


class ExternalCapabilityTests(unittest.TestCase):
    CTLA4_REFERENCE_SEQUENCE = (
        "MACLGFQRHKAQLNLATRTWPCTLLFFLLFIPVFCKAMHVAQPAVVLASSRGIASFVCEY"
        "ASPGKATEVRVTVLRQADSQVTEVCAATYMMGNELTFLDDSICTGTSSGNQVNLTIQGLR"
        "AMDTGLYICKVELMYPPPYYLGIGNGTQIYVIDPEPCPDSDFLLWILAAVSSGLFFYSFL"
        "LTAVSLSKMLKKRSPLTTGVYVKMPPTEPECEKQFQPYFIPIN"
    )

    def test_capabilities_are_focused_and_dispatchable(self) -> None:
        self.assertEqual(
            [tool["name"] for tool in list_operations(capability="paperclip")],
            ["paperclip.search_biomedical", "paperclip.retrieve_document_evidence"],
        )
        with patch("genomi.capabilities.paperclip.search.shutil.which", return_value=None):
            result = call_operation(
                "genomi.invoke",
                {"tool": "paperclip.search_biomedical", "params": {"query": "immune deficiency"}},
            )
        self.assertEqual(result["dispatched_tool"], "paperclip.search_biomedical")
        self.assertIn(result["status"], {"source_unavailable", "completed", "in_scope_empty"})

    def test_paperclip_uses_secret_only_in_child_environment(self) -> None:
        seen: dict[str, object] = {}

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen["command"] = command
            seen["env"] = kwargs["env"]
            payload = {"results": [{"id": "PMC1", "title": "Public paper", "source": "pmc"}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.search.shutil.which", return_value="paperclip"):
                result = search_biomedical(query="public question", runner=runner)
        self.assertEqual(result["records"][0]["title"], "Public paper")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))
        self.assertNotIn("paperclip-test-secret", seen["command"])
        self.assertEqual(seen["env"]["PAPERCLIP_API_KEY"], "paperclip-test-secret")

    def test_paperclip_parses_current_cli_search_display(self) -> None:
        display = """Found 1 paper  [s_abc123]

  1. Public mechanism paper
     Ada Author, Ben Researcher
     PMC1234567 · Example Journal · 2024-04-02
     https://doi.org/10.1000/example
     \"A public evidence summary.\"

[20ms, saved to s_abc123]
"""

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            self.assertNotIn("--json", command)
            return subprocess.CompletedProcess(command, 0, display, "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.search.shutil.which", return_value="paperclip"):
                result = search_biomedical(query="public question", sources=["pmc"], runner=runner)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result_id"], "s_abc123")
        self.assertEqual(result["records"][0]["record_id"], "PMC1234567")
        self.assertEqual(result["records"][0]["collection"], "papers")
        self.assertEqual(result["records"][0]["doi"], "10.1000/example")

    def test_paperclip_reads_line_pinned_public_evidence(self) -> None:
        seen: list[list[str]] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen.append(command)
            self.assertEqual(kwargs["env"]["PAPERCLIP_API_KEY"], "paperclip-test-secret")
            if command[1] == "cat":
                payload = {
                    "document_id": "PMC1234567",
                    "title": "Public mechanism paper",
                    "authors": "Ada Author",
                    "doi": "10.1000/example",
                    "source": "pmc",
                }
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return subprocess.CompletedProcess(
                command,
                0,
                "L16:Mechanistic evidence from the public paper.\nL24:A second public observation.\n",
                "",
            )

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.read.shutil.which", return_value="paperclip"):
                result = retrieve_document_evidence(
                    document_id="PMC1234567",
                    collection="papers",
                    patterns=["mechanistic evidence", "public observation"],
                    runner=runner,
                )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["excerpts"][0]["line_start"], 16)
        self.assertEqual(
            result["excerpts"][0]["citation_url"],
            "https://paperclip.gxl.ai/citations/papers/PMC1234567#L16",
        )
        self.assertEqual(seen[0][1], "cat")
        self.assertEqual(seen[1][1], "grep")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))

    def test_biohub_returns_metrics_without_secret_or_embeddings(self) -> None:
        vectors = iter(([1.0, 0.0], [0.8, 0.2]))

        def transport(path: str, payload: dict[str, object], token: str) -> dict[str, object]:
            self.assertEqual(token, "biohub-test-secret")
            if path.endswith("encode"):
                return {"outputs": {"sequence": [1, 2, 3]}}
            return {"mean_embedding": [[list(next(vectors))]]}

        with external_credential_session({"BIOHUB_API_KEY": "biohub-test-secret"}):
            result = compare_protein_embeddings(
                reference_sequence="ACD",
                alternate_sequence="AED",
                sequence_scope="public_reference_or_approved_research_artifact",
                external_transfer_approved=True,
                transport=transport,
            )
        self.assertEqual(result["comparison"]["changed_positions"][0]["position"], 2)
        self.assertNotIn("biohub-test-secret", json.dumps(result))
        self.assertNotIn("mean_embedding", json.dumps(result))

    def test_biohub_refuses_unapproved_or_wrong_scope_without_provider_call(self) -> None:
        def transport(*_: object) -> dict[str, object]:
            self.fail("out-of-scope input must not reach BioHub")

        for sequence_scope, approved in (
            ("patient_sequence", True),
            ("public_reference_or_approved_research_artifact", False),
        ):
            with self.subTest(sequence_scope=sequence_scope, approved=approved):
                result = compare_protein_embeddings(
                    reference_sequence="not inspected",
                    alternate_sequence="not inspected",
                    sequence_scope=sequence_scope,
                    external_transfer_approved=approved,
                    transport=transport,
                )
                self.assertEqual(result["status"], "out_of_scope_for_input")
                self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
                envelope = result["evidence_envelope"]
                evidence_envelope.validate(envelope)
                self.assertEqual(envelope["finding_state"], "out_of_scope_for_input")
                self.assertFalse(envelope["negative_inference"]["allowed"])
                self.assertEqual(envelope["coverage"]["consulted_sources"], [])
                self.assertNotIn("not inspected", json.dumps(result))

    def test_invoke_returns_typed_out_of_scope_for_biohub_scope_and_approval(self) -> None:
        for sequence_scope, approved in (
            ("patient_sequence", True),
            ("public_reference_or_approved_research_artifact", False),
        ):
            with self.subTest(sequence_scope=sequence_scope, approved=approved):
                result = call_operation(
                    "genomi.invoke",
                    {
                        "tool": "biohub.compare_protein_embeddings",
                        "params": {
                            "reference_sequence": "not inspected",
                            "alternate_sequence": "not inspected",
                            "sequence_scope": sequence_scope,
                            "external_transfer_approved": approved,
                        },
                    },
                )
                self.assertEqual(result["dispatched_tool"], "biohub.compare_protein_embeddings")
                self.assertEqual(result["status"], "out_of_scope_for_input")
                self.assertEqual(
                    result["evidence_envelope"]["finding_state"],
                    "out_of_scope_for_input",
                )

    def test_public_paperclip_protein_sequence_can_feed_biohub(self) -> None:
        def paperclip_runner(
            command: list[str], **_: object
        ) -> subprocess.CompletedProcess[str]:
            self.assertEqual(command[1:4], ["search", "-s", "proteins"])
            payload = {
                "results": [
                    {
                        "document_id": "P16410",
                        "accession": "P16410",
                        "uniprot_id": "CTLA4_HUMAN",
                        "protein_name": "Cytotoxic T-lymphocyte protein 4",
                        "source": "uniprot",
                        "sequence": {
                            "value": self.CTLA4_REFERENCE_SEQUENCE,
                            "length": len(self.CTLA4_REFERENCE_SEQUENCE),
                        },
                    }
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with external_credential_session(
            {
                "PAPERCLIP_API_KEY": "paperclip-test-secret",
                "BIOHUB_API_KEY": "biohub-test-secret",
            }
        ):
            with patch(
                "genomi.capabilities.paperclip.search.shutil.which",
                return_value="paperclip",
            ):
                search_result = search_biomedical(
                    query="UniProt P16410",
                    sources=["proteins"],
                    limit=1,
                    runner=paperclip_runner,
                )

            protein = search_result["records"][0]
            reference = protein["reference_sequence"]
            changed_index = reference.index("Q")
            alternate = reference[:changed_index] + "H" + reference[changed_index + 1 :]
            vectors = iter(([1.0, 0.0], [0.9, 0.1]))

            def biohub_transport(
                path: str, payload: dict[str, object], token: str
            ) -> dict[str, object]:
                self.assertEqual(token, "biohub-test-secret")
                if path.endswith("encode"):
                    return {"outputs": {"sequence": [1, 2, 3]}}
                return {"mean_embedding": [[list(next(vectors))]]}

            comparison = compare_protein_embeddings(
                reference_sequence=reference,
                alternate_sequence=alternate,
                sequence_scope="public_reference_or_approved_research_artifact",
                external_transfer_approved=True,
                transport=biohub_transport,
            )

        self.assertEqual(protein["accession"], "P16410")
        self.assertEqual(reference, self.CTLA4_REFERENCE_SEQUENCE)
        self.assertEqual(search_result["status"], "completed")
        self.assertEqual(comparison["status"], "completed")
        self.assertEqual(
            comparison["comparison"]["changed_positions"][0]["position"],
            changed_index + 1,
        )
        self.assertNotIn("patient", json.dumps(search_result).lower())
        self.assertNotIn("agi", json.dumps(search_result).lower())

    def test_invalid_public_protein_sequence_is_omitted(self) -> None:
        payload = {
            "results": [
                {
                    "document_id": "P16410",
                    "accession": "P16410",
                    "source": "uniprot",
                    "sequence": {"value": "ACGT*"},
                },
                {
                    "document_id": "not-an-accession",
                    "accession": "not-an-accession",
                    "source": "uniprot",
                    "sequence": {"value": self.CTLA4_REFERENCE_SEQUENCE},
                },
            ]
        }

        def runner(
            command: list[str], **_: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with external_credential_session(
            {"PAPERCLIP_API_KEY": "paperclip-test-secret"}
        ):
            with patch(
                "genomi.capabilities.paperclip.search.shutil.which",
                return_value="paperclip",
            ):
                result = search_biomedical(
                    query="public protein accessions",
                    sources=["uniprot"],
                    runner=runner,
                )

        self.assertEqual(result["records"][0]["accession"], "P16410")
        self.assertNotIn("reference_sequence", result["records"][0])
        self.assertNotIn("accession", result["records"][1])
        self.assertNotIn("reference_sequence", result["records"][1])

    def test_proto_preserves_result_and_prunes_paths(self) -> None:
        class Native:
            @staticmethod
            def list_tools(**_: object) -> list[dict[str, object]]:
                return [{"tool_key": "example-tool", "deployed": True}]

            @staticmethod
            def run_tool(**_: object) -> dict[str, object]:
                return {
                    "ok": True,
                    "ran_on": "modal",
                    "score": 0.7,
                    "_saved_to": "/private/result.json",
                }

        with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
            with patch("genomi.capabilities.proto.tools._modal_client", return_value=(object(), object())):
                result = run_tool(
                    tool_key="example-tool",
                    inputs={"value": 1},
                    input_scope="public_or_approved_research_artifact",
                    external_transfer_approved=True,
                )
        self.assertEqual(result["result"]["score"], 0.7)
        self.assertEqual(result["result"]["artifact_state"], "materialized_not_presented")
        self.assertNotIn("/private/result.json", json.dumps(result))

    def test_proto_discovery_excludes_local_fallbacks(self) -> None:
        class Native:
            @staticmethod
            def search_tools(**_: object) -> dict[str, object]:
                return {
                    "tools": [
                        {
                            "tool_key": "local-tool",
                            "deployed": False,
                            "runs_in_process": True,
                        },
                        {"tool_key": "remote-tool", "deployed": True},
                    ]
                }

        with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
            with patch("genomi.capabilities.proto.tools._modal_client", return_value=(object(), object())):
                result = search_tools(query="public protein analysis", limit=1)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            [item["tool_key"] for item in result["tools"]], ["remote-tool"]
        )

    def test_proto_refuses_undeployed_tool_before_execution(self) -> None:
        class Native:
            @staticmethod
            def list_tools(**_: object) -> list[dict[str, object]]:
                return [
                    {
                        "tool_key": "local-tool",
                        "deployed": False,
                        "runs_in_process": True,
                    }
                ]

            @staticmethod
            def run_tool(**_: object) -> dict[str, object]:
                raise AssertionError("an undeployed tool must not execute locally")

        with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
            with patch("genomi.capabilities.proto.tools._modal_client", return_value=(object(), object())):
                result = run_tool(
                    tool_key="local-tool",
                    inputs={"value": 1},
                    input_scope="public_or_approved_research_artifact",
                    external_transfer_approved=True,
                )

        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["reason_code"], "remote_deployment_unavailable")
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")

    def test_proto_rejects_unexpected_local_execution_result(self) -> None:
        class Native:
            @staticmethod
            def list_tools(**_: object) -> list[dict[str, object]]:
                return [{"tool_key": "remote-tool", "deployed": True}]

            @staticmethod
            def run_tool(**_: object) -> dict[str, object]:
                return {"ok": True, "ran_on": "local", "score": 0.7}

        with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
            with patch("genomi.capabilities.proto.tools._modal_client", return_value=(object(), object())):
                result = run_tool(
                    tool_key="remote-tool",
                    inputs={"value": 1},
                    input_scope="public_or_approved_research_artifact",
                    external_transfer_approved=True,
                )

        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["reason_code"], "remote_execution_not_confirmed")
        self.assertNotIn("result", result)
        self.assertEqual(result["evidence_envelope"]["finding_state"], "not_assessed")

    def test_proto_refuses_unapproved_or_wrong_scope_without_provider_call(self) -> None:
        class Native:
            @staticmethod
            def run_tool(**_: object) -> dict[str, object]:
                raise AssertionError("out-of-scope input must not reach Proto")

        for input_scope, approved in (
            ("patient_inputs", True),
            ("public_or_approved_research_artifact", False),
        ):
            with self.subTest(input_scope=input_scope, approved=approved):
                with patch("genomi.capabilities.proto.tools._native_tools", return_value=Native()):
                    result = run_tool(
                        tool_key="example-tool",
                        inputs={"private": "not inspected"},
                        input_scope=input_scope,
                        external_transfer_approved=approved,
                    )
                self.assertEqual(result["status"], "out_of_scope_for_input")
                self.assertEqual(result["coverage_state"], "out_of_scope_for_input")
                envelope = result["evidence_envelope"]
                evidence_envelope.validate(envelope)
                self.assertEqual(envelope["finding_state"], "out_of_scope_for_input")
                self.assertFalse(envelope["negative_inference"]["allowed"])
                self.assertEqual(envelope["coverage"]["consulted_sources"], [])
                self.assertNotIn("not inspected", json.dumps(result))

    def test_invoke_returns_typed_out_of_scope_for_proto_scope_and_approval(self) -> None:
        for input_scope, approved in (
            ("patient_inputs", True),
            ("public_or_approved_research_artifact", False),
        ):
            with self.subTest(input_scope=input_scope, approved=approved):
                result = call_operation(
                    "genomi.invoke",
                    {
                        "tool": "proto.run_tool",
                        "params": {
                            "tool_key": "example-tool",
                            "inputs": {"private": "not inspected"},
                            "input_scope": input_scope,
                            "external_transfer_approved": approved,
                        },
                    },
                )
                self.assertEqual(result["dispatched_tool"], "proto.run_tool")
                self.assertEqual(result["status"], "out_of_scope_for_input")
                self.assertEqual(
                    result["evidence_envelope"]["finding_state"],
                    "out_of_scope_for_input",
                )


if __name__ == "__main__":
    unittest.main()
