"""Initial hypotheses, candidate-gene AGI discovery, and evidence replay."""

from __future__ import annotations

from typing import Any, Protocol

from .constants import JsonObject


class RoundOneOwner(Protocol):
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
    def _finding(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _gap(self, *args: Any, **kwargs: Any) -> JsonObject: ...
    def _reports(self, round_id: str, reports: list[JsonObject]) -> None: ...


class RoundOneMixin:
    def _round_one(self: RoundOneOwner) -> None:
        catalog = self.service.investigation_capability_catalog(self.investigation_id)
        requests = [
            self._working_hypothesis_request(
                request_id="r1-hypothesis-medication",
                label="medication-related immune suppression",
                profile_key="medication",
            ),
            self._working_hypothesis_request(
                request_id="r1-hypothesis-unifying",
                label="unifying immune dysregulation",
                profile_key="platelets",
            ),
            self._working_hypothesis_request(
                request_id="r1-hypothesis-antibody",
                label="antibody deficiency alternative",
                profile_key="infections",
            ),
            self._working_hypothesis_request(
                request_id="r1-hypothesis-separate",
                label="several unrelated conditions",
                profile_key="crohn",
            ),
            {
                "id": "r1-profile",
                "capability": "investigation.project_profile",
                "parameters": {},
            },
            {
                "id": "r1-candidate-gene-scan",
                "capability": "genomi.variant.find_gene_variants",
                "parameters": self._candidate_scan_parameters(catalog),
            },
            {
                "id": "r1-paperclip-replay",
                "capability": "public_evidence.retrieve",
                "parameters": dict(catalog["public_evidence.retrieve"]["parameters"]),
            },
        ]
        accepted = self.service.submit_agent_plan(
            self.investigation_id,
            focus_question=(
                "Could medication, antibody deficiency, or one immune mechanism "
                "connect the reported history?"
            ),
            specialist_assignments=self._assignments(
                1,
                [
                    "align the initial clinical chronology",
                    "propose a focused candidate set and review chair-returned AGI evidence",
                    "review the grounded public evidence replay and challenge overinterpretation",
                ],
            ),
            requests=requests,
        )
        round_id = str(accepted["investigation_round"]["round_id"])
        self._set_working(
            round_id,
            [
                "Aligning infections and immune history with medication timing",
                "Comparing five immune candidates through the main investigator",
                "Reviewing dated public-source cards and variant-level gaps",
            ],
        )
        self.emit(
            "round_1_started",
            "Round 1: four hypotheses, three specialists",
            "The persistent panel is investigating chronology, the candidate set, and public evidence.",
            scroll_target="#specialist-board",
        )
        initial_results = self._execute_requests(
            [
                "r1-hypothesis-medication",
                "r1-hypothesis-unifying",
                "r1-hypothesis-antibody",
                "r1-hypothesis-separate",
                "r1-profile",
            ]
        )
        for key, request_id in {
            "medication": "r1-hypothesis-medication",
            "unifying": "r1-hypothesis-unifying",
            "antibody": "r1-hypothesis-antibody",
            "separate": "r1-hypothesis-separate",
        }.items():
            self.hypothesis_ids[key] = str(
                initial_results[request_id]["hypothesis"]["hypothesis_id"]
            )
        self.emit(
            "initial_hypotheses_formed",
            "Four initial explanations enter the working set",
            "Medication effect, one immune mechanism, antibody deficiency, and unrelated conditions remain open before genome and public-evidence review.",
            scroll_target="#hypothesis-list",
        )
        candidate_result = self._execute_requests(["r1-candidate-gene-scan"])
        candidate = candidate_result["r1-candidate-gene-scan"]["evidence_record"]
        variants = candidate["evidence"].get("variants") or []
        if not any(
            row.get("rsid") == "rs2469719303"
            and row.get("genotype") == "0/1"
            and "CTLA4" in (row.get("matched_candidate_genes") or [])
            for row in variants
        ):
            raise RuntimeError("the real candidate-gene AGI scan did not find CTLA4 Q76H")
        gene_results = candidate["evidence"].get("gene_results") or []
        if {
            row.get("gene") for row in gene_results if row.get("coverage_state")
        } != {"CTLA4", "LRBA", "NFKB1", "TNFRSF13B", "PIK3CD"} or any(
            row.get("coverage_state") == "out_of_scope_for_input"
            for row in gene_results
        ):
            raise RuntimeError("the five-gene fixture did not provide complete interval scope")
        self.emit(
            "q76h_found",
            "Genomi surfaces heterozygous CTLA4 rs2469719303",
            "The Main Investigator ran the actual bounded request against the synthetic recording-twin AGI; the portal shows the returned locus and genotype while specialists never access genome rows.",
            scroll_target="#evidence-heading",
        )
        public_result = self._execute_requests(["r1-paperclip-replay"])
        public = public_result["r1-paperclip-replay"]["evidence_record"]
        self.emit(
            "paperclip_replay_committed",
            "Public evidence maps rs2469719303 to Q76H and preserves VUS status",
            "The source-separated ledger adds the Q76H identity, phenotype overlap, and uncertain classification from the curated Paperclip replay.",
            scroll_target="#evidence-heading",
        )
        self._reports(round_id, self._round_one_reports(candidate, public))
        self.emit(
            "round_1_complete",
            "Round 1 reports identify the decisive missing evidence",
            "Q76H is a lead for investigation, not an answer; medication and antibody-deficiency branches remain open.",
            scroll_target="#specialist-board",
        )

    def _round_one_reports(
        self: RoundOneOwner, candidate: JsonObject, public: JsonObject
    ) -> list[JsonObject]:
        c_id = str(candidate["evidence_record_id"])
        p_id = str(public["evidence_record_id"])
        return [
            {
                "findings": [
                    self._finding(
                        "Medication timing remains unresolved because key immune abnormalities are not yet dated.",
                        "mixed",
                        profile_ids=[self.observation_ids["medication"]],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Did pneumonia or low immunoglobulins predate biologic or B-cell-depleting treatment?",
                        profile_ids=[self.observation_ids["infections"]],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "The bounded five-gene AGI scan found heterozygous CTLA4 rs2469719303 in the synthetic recording-twin genome fixture.",
                        "supports",
                        evidence_ids=[c_id],
                        profile_ids=[self.observation_ids["infections"]],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Can the exact Q76H allele be clinically confirmed and functionally evaluated?",
                        evidence_ids=[c_id],
                    )
                ],
            },
            {
                "findings": [
                    self._finding(
                        "The replayed sources support CTLA4 phenotype overlap but keep Q76H at uncertain significance.",
                        "mixed",
                        evidence_ids=[p_id],
                        profile_ids=[self.observation_ids["crohn"]],
                    )
                ],
                "gaps": [
                    self._gap(
                        "Do pretreatment immunoglobulins, vaccine responses, B-cell subsets, and pathology change the differential?",
                        evidence_ids=[p_id],
                        profile_ids=[self.observation_ids["crohn"]],
                    )
                ],
            },
        ]
