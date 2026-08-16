from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from genomi.capabilities.biohub import esmc as biohub_esmc
from genomi.capabilities.biohub.esmc import compare_protein_embeddings
from genomi.capabilities.paperclip.read import COLLECTIONS, retrieve_document_evidence
from genomi.capabilities.paperclip.search import SUPPORTED_SOURCES, search_biomedical
from genomi.capabilities.proto import tools as proto_tools
from genomi.capabilities.proto.tools import run_tool, search_tools
from genomi.evidence import envelope as evidence_envelope
from genomi.operations.registry.table import call_operation, list_operations
from genomi.runtime.external_credentials import external_credential_session
from tests.support.capabilities.paperclip_cli import (
    FDA_DISPLAY,
    PMC_ABSTRACTS_DISPLAY,
    PROTEINS_DISPLAY,
    TRIALS_JP_DISPLAY,
)


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

    def test_provider_scope_gates_are_discoverable_from_the_tool_definition(self) -> None:
        # The runtime accepts exactly one scope literal per provider and fails
        # closed on anything else. A host agent reads the tool definition, not
        # the handler, so the accepted literal has to be in the schema.
        cases = (
            (
                "biohub",
                "biohub.compare_protein_embeddings",
                "sequence_scope",
                biohub_esmc.PUBLIC_SEQUENCE_SCOPE,
            ),
            (
                "proto",
                "proto.run_tool",
                "input_scope",
                proto_tools.PUBLIC_INPUT_SCOPE,
            ),
        )
        for capability, name, field, accepted in cases:
            with self.subTest(operation=name):
                definition = next(
                    tool
                    for tool in list_operations(capability=capability)
                    if tool["name"] == name
                )
                schema = definition["inputSchema"]
                self.assertIn(field, schema["required"])
                self.assertEqual(schema["properties"][field]["enum"], [accepted])

    def _search_display(
        self, display: str, sources: list[str]
    ) -> dict[str, object]:
        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            self.assertNotIn("--json", command)
            return subprocess.CompletedProcess(command, 0, display, "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch(
                "genomi.capabilities.paperclip.search.shutil.which",
                return_value="paperclip",
            ):
                return search_biomedical(
                    query="public question", sources=sources, limit=2, runner=runner
                )

    def test_every_declared_source_resolves_a_readable_collection(self) -> None:
        for source in SUPPORTED_SOURCES:
            with self.subTest(source=source):
                record = self._search_display(TRIALS_JP_DISPLAY, [source])["records"][0]
                self.assertEqual(record["source"], source)
                # The `tri_` handle in this capture is read under /trials/
                # whichever declared source the host asked for, including the
                # `fda/jp` and `fda/eu` regulatory sources.
                self.assertEqual(record["collection"], "trials")
                self.assertIn(record["collection"], COLLECTIONS)

    def test_paperclip_uses_secret_only_in_child_environment(self) -> None:
        seen: dict[str, object] = {}

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen["command"] = command
            seen["env"] = kwargs["env"]
            return subprocess.CompletedProcess(command, 0, PMC_ABSTRACTS_DISPLAY, "")

        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch("genomi.capabilities.paperclip.search.shutil.which", return_value="paperclip"):
                result = search_biomedical(query="public question", runner=runner)
        self.assertEqual(result["records"][0]["record_id"], "PMC5435412")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))
        self.assertNotIn("paperclip-test-secret", seen["command"])
        self.assertEqual(seen["env"]["PAPERCLIP_API_KEY"], "paperclip-test-secret")

    def test_paperclip_parses_paper_display_entries(self) -> None:
        result = self._search_display(PMC_ABSTRACTS_DISPLAY, ["pmc", "abstracts"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result_ids"], ["s_6b726a6f"])
        first, second = result["records"]
        self.assertEqual(
            first,
            {
                "title": (
                    "Antibody-mediated neutralization of soluble MIC significantly "
                    "enhances CTLA4 blockade therapy"
                ),
                "authors": (
                    "Jingyu Zhang, Dai Liu, Guangfu Li, Kevin F. Staveley-O’Carroll, "
                    "Julie N. Graff, Zihai Li, Jennifer D..."
                ),
                "record_id": "PMC5435412",
                "journal": "Science Advances",
                "published": "2017-05-01",
                "url": "https://doi.org/10.1126/sciadv.1602133",
                "doi": "10.1126/sciadv.1602133",
                "abstract": (
                    "This study investigated the combined therapeutic effect of "
                    "anti-CTLA4 and anti-sMIC antibodies. Soluble MIC neutralization "
                    "significantly enhances CTLA4 blockade therapy."
                ),
                "collection": "papers",
                "source": "pmc",
            },
        )
        self.assertEqual(second["record_id"], "PMC3300183")
        self.assertEqual(second["authors"], "A Korman")
        self.assertEqual(second["journal"], "Breast Cancer Research : BCR")
        self.assertEqual(second["collection"], "papers")

    def test_paperclip_parses_regulatory_display_entries(self) -> None:
        result = self._search_display(FDA_DISPLAY, ["fda"])
        self.assertEqual(result["result_ids"], ["s_4561f9c3"])
        first, second = result["records"]
        self.assertEqual(first["title"], "Yervoy")
        self.assertEqual(first["record_id"], "fda_0100f40f7361")
        self.assertEqual(first["collection"], "fda")
        self.assertEqual(first["source"], "fda")
        self.assertEqual(first["external_id"], "BLA125377")
        self.assertEqual(first["journal"], "TOC Review")
        self.assertEqual(
            first["section"],
            "Study title: Biophysical characterization of protein reagents used in "
            "MDX-010 SPR experiments",
        )
        self.assertTrue(
            first["abstract"].startswith("Bristol-Myers Squibb submitted an original")
        )
        # One application number covers many documents, so the readable handle
        # is what separates them.
        self.assertEqual(second["external_id"], "BLA125377")
        self.assertEqual(second["record_id"], "fda_6b679bd504e9")
        self.assertEqual(second["section"], "Market approval status")

    def test_paperclip_parses_trial_registry_display_entries(self) -> None:
        result = self._search_display(TRIALS_JP_DISPLAY, ["trials/jp"])
        self.assertEqual(result["result_ids"], ["s_974f9f85"])
        first, second = result["records"]
        self.assertEqual(first["record_id"], "tri_316b07644307")
        self.assertEqual(first["external_id"], "UMIN000028085")
        self.assertEqual(first["journal"], "umin_registry")
        self.assertEqual(first["section"], "primary_outcomes")
        self.assertEqual(first["source"], "trials/jp")
        self.assertEqual(first["collection"], "trials")
        self.assertEqual(
            first["abstract"],
            "Malignant melanoma Patients with malignant melanoma None Disease "
            "specific survival",
        )
        self.assertEqual(second["record_id"], "tri_6e3c56bf266b")
        self.assertEqual(second["collection"], "trials")

    def test_paperclip_parses_protein_display_entries(self) -> None:
        result = self._search_display(PROTEINS_DISPLAY, ["proteins"])
        self.assertEqual(result["result_ids"], ["s_1818459d"])
        self.assertEqual(
            result["records"],
            [
                {
                    "title": "CTLA4 - Cytotoxic T-lymphocyte protein 4",
                    "record_id": "P16410",
                    "accession": "P16410",
                    "organism": "Homo sapiens",
                    "collection": "proteins",
                    "source": "proteins",
                },
                {
                    "title": "CTLA4 - Cytotoxic T-lymphocyte protein 4",
                    "record_id": "P42072",
                    "accession": "P42072",
                    "organism": "Oryctolagus cuniculus",
                    "collection": "proteins",
                    "source": "proteins",
                },
            ],
        )

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
        self.assertEqual(result["document"]["record_id"], "PMC1234567")
        self.assertEqual(result["excerpts"][0]["line_start"], 16)
        self.assertEqual(
            result["excerpts"][0]["citation_url"],
            "https://paperclip.gxl.ai/citations/papers/PMC1234567#L16",
        )
        self.assertEqual(seen[0][1], "cat")
        self.assertEqual(seen[1][1], "grep")
        self.assertNotIn("paperclip-test-secret", json.dumps(result))

    def test_paperclip_reads_the_handle_a_regulatory_search_returned(self) -> None:
        read_paths: list[str] = []

        def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            read_paths.append(next(part for part in command if part.startswith("/fda/")))
            if command[1] == "cat":
                payload = {
                    "document_id": "0100f40f-7361-5695-80fc-b480dcdb52d5",
                    "source_type": "toc_review",
                    "identifier": "BLA125377",
                    "tradename": "Yervoy",
                    "public_url": (
                        "https://www.accessdata.fda.gov/drugsatfda_docs/nda/2011/"
                        "125377Orig1s000PharmR.pdf"
                    ),
                    "total_pages": 131,
                }
                return subprocess.CompletedProcess(
                    command, 0, json.dumps(payload) + "\n[30ms]\n", ""
                )
            return subprocess.CompletedProcess(
                command, 0, "L14:Bristol Myers-Squibb Corp. (BMS) has submitted a BLA.\n", ""
            )

        record = self._search_display(FDA_DISPLAY, ["fda"])["records"][0]
        with external_credential_session({"PAPERCLIP_API_KEY": "paperclip-test-secret"}):
            with patch(
                "genomi.capabilities.paperclip.read.shutil.which", return_value="paperclip"
            ):
                result = retrieve_document_evidence(
                    document_id=record["record_id"],
                    collection=record["collection"],
                    patterns=["Bristol"],
                    runner=runner,
                )
        self.assertEqual(read_paths[0], "/fda/fda_0100f40f7361/meta.json")
        self.assertEqual(read_paths[1], "/fda/fda_0100f40f7361/content.lines")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["document"]["record_id"], "fda_0100f40f7361")
        self.assertEqual(result["document"]["external_id"], "BLA125377")
        self.assertEqual(result["document"]["title"], "Yervoy")
        self.assertEqual(result["document"]["collection"], "fda")
        self.assertEqual(
            result["excerpts"][0]["citation_url"],
            "https://paperclip.gxl.ai/citations/fda/fda_0100f40f7361#L14",
        )

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

    def test_paperclip_accession_identifies_the_biohub_reference_sequence(self) -> None:
        # Paperclip serves the accession and organism; the public reference
        # sequence for that accession is what BioHub compares.
        protein = self._search_display(PROTEINS_DISPLAY, ["proteins"])["records"][0]
        reference = self.CTLA4_REFERENCE_SEQUENCE
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

        with external_credential_session({"BIOHUB_API_KEY": "biohub-test-secret"}):
            comparison = compare_protein_embeddings(
                reference_sequence=reference,
                alternate_sequence=alternate,
                sequence_scope="public_reference_or_approved_research_artifact",
                external_transfer_approved=True,
                transport=biohub_transport,
            )

        self.assertEqual(protein["accession"], "P16410")
        self.assertEqual(protein["organism"], "Homo sapiens")
        self.assertEqual(comparison["status"], "completed")
        self.assertEqual(
            comparison["comparison"]["changed_positions"][0]["position"],
            changed_index + 1,
        )

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
