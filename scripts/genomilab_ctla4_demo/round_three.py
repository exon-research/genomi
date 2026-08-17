"""Final evidence round plus honest Genomi/ESM/Proto operation boundaries."""

from __future__ import annotations

from typing import Any, Protocol

from .constants import CTLA4_REFERENCE_PROTEIN, JsonObject
from .executors import esm_precomputed_fixture, proto_precomputed_fixture


class RoundThreeOwner(Protocol):
    service: Any
    investigation_id: str
    observation_ids: dict[str, str]
    hypothesis_ids: dict[str, str]
    operation_results: dict[str, JsonObject]

    def emit(self, stage: str, title: str, detail: str, **kwargs: Any) -> None: ...
    def _assignments(self, round_number: int, tasks: list[str]) -> list[JsonObject]: ...
    def _set_working(self, round_id: str, messages: list[str]) -> None: ...
    def _execute_requests(self, request_ids: list[str]) -> dict[str, JsonObject]: ...
    def _working_hypothesis_request(self, **kwargs: Any) -> JsonObject: ...
    def _focused_public_request(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _finding(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _gap(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _reports(self, round_id: str, reports: list[JsonObject]) -> None: ...


class RoundThreeMixin:
    def _round_three(self: RoundThreeOwner) -> None:
        catalog = self.service.investigation_capability_catalog(self.investigation_id)
        requests = [
            self._working_hypothesis_request(
                request_id="r3-hypothesis-unifying",
                label="checkpoint-pathway immune dysregulation",
                profile_key="ctla4_function",
                status="supported",
                supersedes=self.hypothesis_ids["unifying"],
            ),
            self._working_hypothesis_request(
                request_id="r3-hypothesis-antibody",
                label="antibody deficiency alternative",
                profile_key="low_ig_current",
                status="candidate",
                supersedes=self.hypothesis_ids["antibody"],
            ),
            self._working_hypothesis_request(
                request_id="r3-hypothesis-medication-only",
                label="medication-only explanation",
                profile_key="low_ig_before_rituximab",
                status="rejected",
                supersedes=self.hypothesis_ids["medication"],
            ),
            self._working_hypothesis_request(
                request_id="r3-hypothesis-medication-contributor",
                label="medication effect as a contributor",
                profile_key="medication",
                status="candidate",
                supersedes=self.hypothesis_ids["medication_contributor"],
            ),
            self._working_hypothesis_request(
                request_id="r3-hypothesis-separate",
                label="several independent processes",
                profile_key="mother_carrier",
                status="weakened",
                supersedes=self.hypothesis_ids["separate"],
            ),
            {
                "id": "r3-exact-q76h",
                "capability": "genomi.variant.resolve",
                "parameters": dict(catalog["genomi.variant.resolve"]["parameters"]),
            },
            {
                "id": "r3-paperclip-function-replay",
                "capability": "public_evidence.retrieve_perturbation",
                "parameters": self._focused_public_request(
                    catalog,
                    "public_evidence.retrieve_perturbation",
                    "CTLA4 Q76H classification function transendocytosis penetrance",
                    [
                        "CTLA4 Q76H",
                        "CTLA4 transendocytosis assay",
                        "CTLA4 incomplete penetrance",
                    ],
                    profile_key="q76h_report",
                ),
            },
            {
                "id": "r3-interpretation-gap",
                "capability": "investigation.register_gap",
                "parameters": {
                    "kind": "confirmation_requirement",
                    "statement": (
                        "Evidence gap: Clinical interpretation of rs2469719303 "
                        "remains an open requirement."
                    ),
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.observation_ids["q76h_report"]],
                    "status": "open",
                },
            },
        ]
        accepted = self.service.submit_agent_plan(
            self.investigation_id,
            focus_question=(
                "How should two reduced CTLA4 function repeats, normal abundance, "
                "an unchanged VUS, and an apparently healthy carrier be integrated?"
            ),
            specialist_assignments=self._assignments(
                3,
                [
                    "finalize the chronology and medication-only test",
                    "review exact sequence verification and the abundance-function conflict",
                    "weigh penetrance, alternatives, classification, and assay-method gaps",
                ],
            ),
            requests=requests,
        )
        round_id = str(accepted["investigation_round"]["round_id"])
        self._set_working(
            round_id,
            [
                "Testing medication-only against pretreatment records",
                "Running Genomi verification and reviewing illustrative ESM and Proto analyses",
                "Weighing repeated function, VUS status, and the healthy carrier",
            ],
        )
        self.emit(
            "round_3_started",
            "Round 3: mechanism and conflict resolution",
            "The panel integrates chronology, abundance, two function repeats, inheritance, and source-separated research outputs.",
            scroll_target="#specialist-board",
        )
        results = self._execute_requests([item["id"] for item in requests])
        for key, request_id in {
            "unifying": "r3-hypothesis-unifying",
            "antibody": "r3-hypothesis-antibody",
            "medication": "r3-hypothesis-medication-only",
            "medication_contributor": "r3-hypothesis-medication-contributor",
            "separate": "r3-hypothesis-separate",
        }.items():
            self.hypothesis_ids[key] = str(
                results[request_id]["hypothesis"]["hypothesis_id"]
            )
        self.operation_results["r3-gap"] = results["r3-interpretation-gap"][
            "hypothesis"
        ]
        exact = results["r3-exact-q76h"]["evidence_record"]
        public = results["r3-paperclip-function-replay"]["evidence_record"]
        self._run_research_operations(round_id)
        self._reports(round_id, self._round_three_reports(exact, public))
        self.emit(
            "round_3_complete",
            "Round 3 preserves a rejected medication-only branch and a bounded differential",
            "Checkpoint-pathway dysfunction is supported as a working research hypothesis; antibody deficiency, medication contribution, multiple causes, and Q76H interpretation remain open.",
            scroll_target="#hypothesis-list",
        )

    def _run_research_operations(self: RoundThreeOwner, round_id: str) -> None:
        verification = self.service.verify_agent_sequence_substitution(
            self.investigation_id,
            round_id=round_id,
            deduplication_key="ctla4-demo-genomi-q76h-verification",
            gene="CTLA4",
            transcript_accession="NM_005214.5",
            protein_accession="NP_005205.2",
            coding_change="c.228G>C",
            protein_substitution="Q76H",
            public_reference_protein_sequence=CTLA4_REFERENCE_PROTEIN,
            reference_source_label="NCBI RefSeq canonical CTLA4 protein",
            reference_source_version="NP_005205.2",
            reference_source_record_id="NP_005205.2",
        )
        verification_record = verification["research_artifact"]
        artifact_id = verification_record["research_artifact_id"]
        esm_unavailable = self.service.run_agent_esm_substitution_analysis(
            self.investigation_id,
            round_id=round_id,
            deduplication_key="ctla4-demo-esm-q76h-unavailable-check",
            sequence_verification_artifact_id=artifact_id,
            public_reference_protein_sequence=CTLA4_REFERENCE_PROTEIN,
        )
        proto_unavailable = self.service.run_agent_proto_blinded_experiment_design(
            self.investigation_id,
            round_id=round_id,
            deduplication_key="ctla4-demo-proto-q76h-unavailable-check",
            sequence_verification_artifact_id=artifact_id,
            objective="Separate CTLA4 abundance from CD80 and CD86 ligand-removal function.",
            required_arm_classes=[
                "wild_type_reference",
                "test_variant",
                "assay_negative_control",
                "functional_loss_control",
            ],
            readouts=["ctla4_abundance", "cd80_cd86_ligand_removal"],
        )
        if esm_unavailable.get("status") != "unavailable" or proto_unavailable.get(
            "status"
        ) != "unavailable":
            raise RuntimeError("this fixture harness requires ESM and Proto to be unavailable")
        sequence_input = dict(verification_record["artifact"]["input"])
        esm_fixture = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=round_id,
            deduplication_key="ctla4-demo-esm-q76h-precomputed-fixture",
            origin="precomputed_fixture",
            artifact=esm_precomputed_fixture(sequence_input),
        )
        proto_fixture = self.service.submit_agent_research_artifact(
            self.investigation_id,
            round_id=round_id,
            deduplication_key="ctla4-demo-proto-q76h-precomputed-fixture",
            origin="precomputed_fixture",
            artifact=proto_precomputed_fixture(sequence_input),
        )
        self.operation_results.update(
            {
                "r3-genomi-sequence-verification": verification,
                "r3-esm-scientific-operation": esm_unavailable,
                "r3-proto-scientific-operation": proto_unavailable,
                "r3-esm-precomputed-fixture": esm_fixture,
                "r3-proto-precomputed-fixture": proto_fixture,
            }
        )
        self.emit(
            "research_operations_complete",
            "Genomi sequence verification and illustrative molecular analyses are ready",
            "Genomi performed local sequence verification. The portal also presents clearly marked precomputed ESM and Proto demonstration results, which remain ineligible as case evidence.",
            scroll_target="#research-artifacts-heading",
        )

    def _round_three_reports(
        self: RoundThreeOwner, exact: JsonObject, public: JsonObject
    ) -> list[JsonObject]:
        exact_id = str(exact["evidence_record_id"])
        public_id = str(public["evidence_record_id"])
        return [
            {
                "findings": [
                    self._finding(
                        "Pretreatment pneumonia and low immunoglobulins weigh against medication-only causation while retaining medication as a contributor.",
                        "weighs_against",
                        profile_ids=[
                            self.observation_ids["pneumonia_before_biologic"],
                            self.observation_ids["low_ig_before_rituximab"],
                            self.observation_ids["medication"],
                        ],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Which parts of current infection risk remain medication-associated?",
                        profile_ids=[self.observation_ids["medication"]],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "Two reduced transendocytosis repeats support CTLA4-pathway dysfunction under the reported protocol, not Q76H causality.",
                        "supports",
                        evidence_ids=[exact_id],
                        profile_ids=[
                            self.observation_ids["q76h_report"],
                            self.observation_ids["ctla4_function"],
                        ],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Can the clinical laboratory and treating team reconcile the assay method with the unchanged VUS classification?",
                        evidence_ids=[exact_id],
                        profile_ids=[self.observation_ids["q76h_report"]],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "The apparently healthy carrier weighs against a simple fully penetrant explanation, while published CTLA4 cohorts document incomplete penetrance.",
                        "mixed",
                        evidence_ids=[public_id],
                        profile_ids=[self.observation_ids["mother_carrier"]],
                    )
                ],
                "gaps": [
                    self._gap(
                        "What classification, assay-method, and segregation review would resolve the remaining Q76H uncertainty?",
                        evidence_ids=[public_id],
                        profile_ids=[self.observation_ids["mother_carrier"]],
                    )
                ],
            },
        ]
