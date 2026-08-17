"""Chronology and abundance-versus-function investigation round."""

from __future__ import annotations

from typing import Any, Protocol

from .constants import JsonObject


class RoundTwoOwner(Protocol):
    service: Any
    investigation_id: str
    observation_ids: dict[str, str]
    hypothesis_ids: dict[str, str]

    def emit(self, stage: str, title: str, detail: str, **kwargs: Any) -> None: ...
    def _assignments(self, round_number: int, tasks: list[str]) -> list[JsonObject]: ...
    def _set_working(self, round_id: str, messages: list[str]) -> None: ...
    def _execute_requests(self, request_ids: list[str]) -> dict[str, JsonObject]: ...
    def _working_hypothesis_request(self, **kwargs: Any) -> JsonObject: ...
    def _candidate_scan_parameters(self, catalog: JsonObject) -> JsonObject: ...
    def _focused_public_request(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _finding(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _gap(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _reports(self, round_id: str, reports: list[JsonObject]) -> None: ...


class RoundTwoMixin:
    def _round_two(self: RoundTwoOwner) -> None:
        catalog = self.service.investigation_capability_catalog(self.investigation_id)
        requests = [
            self._working_hypothesis_request(
                request_id="r2-hypothesis-medication",
                label="medication-only explanation",
                profile_key="low_ig_before_rituximab",
                status="rejected",
                supersedes=self.hypothesis_ids["medication"],
            ),
            self._working_hypothesis_request(
                request_id="r2-hypothesis-medication-contributor",
                label="medication effect as a contributor",
                profile_key="medication",
                status="candidate",
            ),
            self._working_hypothesis_request(
                request_id="r2-hypothesis-unifying",
                label="checkpoint-pathway immune dysregulation",
                profile_key="pathology",
                status="supported",
                supersedes=self.hypothesis_ids["unifying"],
            ),
            self._working_hypothesis_request(
                request_id="r2-hypothesis-antibody",
                label="antibody deficiency alternative",
                profile_key="low_ig_current",
                status="supported",
                supersedes=self.hypothesis_ids["antibody"],
            ),
            self._working_hypothesis_request(
                request_id="r2-hypothesis-separate",
                label="several independent processes",
                profile_key="pneumonia_before_biologic",
                status="weakened",
                supersedes=self.hypothesis_ids["separate"],
            ),
            {
                "id": "r2-candidate-gene-rescan",
                "capability": "genomi.variant.find_gene_variants",
                "parameters": self._candidate_scan_parameters(catalog),
            },
            {
                "id": "r2-paperclip-function-replay",
                "capability": "public_evidence.retrieve_perturbation",
                "parameters": self._focused_public_request(
                    catalog,
                    "public_evidence.retrieve_perturbation",
                    "CTLA4 normal staining impaired transendocytosis functional assay Q76H",
                    [
                        "CTLA4 abundance versus function",
                        "CTLA4 transendocytosis assay",
                        "Q76H functional evidence",
                    ],
                    profile_key="pathology",
                ),
            },
        ]
        accepted = self.service.submit_agent_plan(
            self.investigation_id,
            focus_question=(
                "Do the new chronology and immune studies favor medication-only, "
                "one immune pathway, or another antibody disorder, and which exact tests come next?"
            ),
            specialist_assignments=self._assignments(
                2,
                [
                    "test medication-only timing against pretreatment records",
                    "review the five-gene result alongside the immune phenotype",
                    "review functional precedent and define confirmation and abundance gaps",
                ],
            ),
            requests=requests,
        )
        round_id = str(accepted["investigation_round"]["round_id"])
        self._set_working(
            round_id,
            [
                "Comparing pneumonia and low immunoglobulins with treatment dates",
                "Reviewing the synthetic AGI lead against the new immune profile",
                "Checking what clinical confirmation and abundance studies are still missing",
            ],
        )
        self.emit(
            "round_2_started",
            "Round 2: the patient evidence changes the differential",
            "Pretreatment pneumonia and low immunoglobulins reject medication-only causation while retaining medication as a possible contributor. The panel now asks whether the genome lead and immune phenotype justify targeted confirmation and abundance studies.",
            scroll_target="#specialist-board",
        )
        results = self._execute_requests([item["id"] for item in requests])
        for key, request_id in {
            "medication": "r2-hypothesis-medication",
            "unifying": "r2-hypothesis-unifying",
            "antibody": "r2-hypothesis-antibody",
            "separate": "r2-hypothesis-separate",
            "medication_contributor": "r2-hypothesis-medication-contributor",
        }.items():
            self.hypothesis_ids[key] = str(
                results[request_id]["hypothesis"]["hypothesis_id"]
            )
        exact = results["r2-candidate-gene-rescan"]["evidence_record"]
        public = results["r2-paperclip-function-replay"]["evidence_record"]
        self._reports(round_id, self._round_two_reports(exact, public))
        self.emit(
            "round_2_complete",
            "Round 2 defines the next targeted tests",
            "The panel asks for clinical Q76H confirmation, CTLA4 staining, and LRBA expression before it considers ligand-removal function.",
            scroll_target="#hypothesis-list",
        )

    def _round_two_reports(
        self: RoundTwoOwner, exact: JsonObject, public: JsonObject
    ) -> list[JsonObject]:
        exact_id = str(exact["evidence_record_id"])
        public_id = str(public["evidence_record_id"])
        return [
            {
                "findings": [
                    self._finding(
                        "Pneumonia and low immunoglobulins before major immune therapy weigh against a medication-only explanation.",
                        "weighs_against",
                        profile_ids=[
                            self.observation_ids["pneumonia_before_biologic"],
                            self.observation_ids["low_ig_before_rituximab"],
                        ],
                    )
                ],
                "gaps": [
                    self._gap(
                        "How much do current medicines still contribute to infection risk?",
                        profile_ids=[self.observation_ids["medication"]],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "The synthetic AGI Q76H lead and the immune phenotype keep a checkpoint-pathway mechanism open without establishing causality.",
                        "supports",
                        evidence_ids=[exact_id],
                        profile_ids=[
                            self.observation_ids["low_ig_current"],
                            self.observation_ids["pathology"],
                        ],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Can a clinical laboratory confirm the exact allele and report CTLA4 and LRBA abundance controls?",
                        evidence_ids=[exact_id],
                        profile_ids=[self.observation_ids["pathology"]],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "Published variants show that abundance and ligand-removal function can diverge, but the replay does not establish Q76H function.",
                        "mixed",
                        evidence_ids=[public_id],
                        profile_ids=[self.observation_ids["pathology"]],
                    )
                ],
                "gaps": [
                    self._gap(
                        "If abundance controls are unrevealing, should ligand-removal function be tested with blinded controls?",
                        evidence_ids=[public_id],
                        profile_ids=[self.observation_ids["pathology"]],
                    )
                ],
            },
        ]
