"""Case-specific clinician brief and machine-checkable demo report."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from .constants import JsonObject


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class BriefOwner(Protocol):
    service: Any
    investigation_id: str
    observation_ids: dict[str, str]
    operation_results: dict[str, JsonObject]

    def _observation_label(self, key: str) -> str: ...


class BriefMixin:
    def _publish_brief(self: BriefOwner) -> JsonObject:
        inspected = self.service.inspect_agent_investigation(self.investigation_id)
        properties = inspected["brief_authoring"]["brief_schema"]["properties"]
        hypothesis_ids = list(properties["hypothesis_ids"]["items"].get("enum", []))
        gap_ids = list(properties["gap_ids"]["items"].get("enum", []))
        confirmation_schema = properties["confirmation_needs"]
        confirmation_needs = (
            [confirmation_schema["items"]["enum"][0]]
            if confirmation_schema.get("minItems")
            else []
        )
        public_id = str(
            self.operation_results["r3-paperclip-function-replay"]["evidence_record"][
                "evidence_record_id"
            ]
        )
        q76h_profile_id = self.observation_ids["q76h_report"]
        timeline: list[JsonObject] = [
            {
                "statement": (
                    "Patient-reported observation: The profile records Very low "
                    "platelets during adolescence as patient-reported."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["platelets"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued record reports Pneumonia "
                    "documented before the first biologic as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["pneumonia_before_biologic"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued record reports Low "
                    "immunoglobulins documented before rituximab as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["low_ig_before_rituximab"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued laboratory record reports "
                    "Persistently low IgG and IgA as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["low_ig_current"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued laboratory record reports "
                    "Q76H as a research finding."
                ),
                "evidence_record_ids": [public_id],
                "profile_revision_ids": [q76h_profile_id],
            },
            {
                "statement": (
                    "Patient record observation: An issued laboratory record reports "
                    "CTLA4 staining within the laboratory control range as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["ctla4_staining"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued laboratory record reports Two "
                    "independent CTLA4 transendocytosis repeats showed reduced activity "
                    "under the reported protocol as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["ctla4_function"]],
            },
            {
                "statement": (
                    "Patient record observation: An issued laboratory record reports "
                    "Apparently healthy mother carrying CTLA4 Q76H as a research finding."
                ),
                "evidence_record_ids": [],
                "profile_revision_ids": [self.observation_ids["mother_carrier"]],
            },
        ]
        brief = {
            "title": inspected["brief_authoring"]["brief_title_fallback"],
            "summary": (
                "Patient observation: The profile records Q76H as a research observation. "
                "Model inference: The reported record Two independent CTLA4 "
                "transendocytosis repeats showed reduced activity under the reported "
                "protocol may support a possible candidate hypothesis. Evidence gap: "
                "Causality, mechanism, and clinical significance remain unestablished."
            ),
            "clinical_stage": properties["clinical_stage"]["enum"][0],
            "timeline": timeline,
            "claims": [
                {
                    "statement": "Patient observation: The profile records Q76H as a research observation.",
                    "claim_role": "observation",
                    "evidence_record_ids": [public_id],
                    "profile_revision_ids": [q76h_profile_id],
                },
                {
                    "statement": (
                        "Patient observation: The profile records Two independent CTLA4 "
                        "transendocytosis repeats showed reduced activity under the reported "
                        "protocol as a research observation."
                    ),
                    "claim_role": "observation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [self.observation_ids["ctla4_function"]],
                },
                {
                    "statement": (
                        "Evidence gap: Clinical interpretation of rs2469719303 "
                        "remains unresolved."
                    ),
                    "claim_role": "limitation",
                    "evidence_record_ids": [],
                    "profile_revision_ids": [q76h_profile_id],
                },
            ],
            "hypothesis_ids": hypothesis_ids,
            "gap_ids": gap_ids,
            "confirmation_needs": confirmation_needs,
            "clinician_questions": [
                {
                    "question": (
                        "How should the Q76H uncertain classification be interpreted in light "
                        "of two reduced transendocytosis repeats and the reported maternal "
                        "result?"
                    ),
                    "evidence_record_ids": [public_id],
                    "profile_revision_ids": [
                        q76h_profile_id,
                        self.observation_ids["ctla4_function"],
                        self.observation_ids["mother_carrier"],
                    ],
                    "hypothesis_ids": hypothesis_ids,
                    "gap_ids": gap_ids,
                },
                {
                    "question": (
                        "What assay method, controls, reference range, and repeatability "
                        "evidence support the reported reduction in CTLA4 "
                        "transendocytosis?"
                    ),
                    "evidence_record_ids": [public_id],
                    "profile_revision_ids": [self.observation_ids["ctla4_function"]],
                    "hypothesis_ids": hypothesis_ids,
                    "gap_ids": gap_ids,
                },
                {
                    "question": (
                        "What do CTLA4 staining within the laboratory control range and "
                        "LRBA expression within the laboratory control range narrow or "
                        "leave unresolved about pathway function?"
                    ),
                    "evidence_record_ids": [],
                    "profile_revision_ids": [
                        self.observation_ids["ctla4_staining"],
                        self.observation_ids["lrba_expression"],
                    ],
                    "hypothesis_ids": hypothesis_ids,
                    "gap_ids": gap_ids,
                },
                {
                    "question": (
                        "What evidence would help distinguish CTLA4-pathway dysfunction "
                        "from other immune or genetic mechanisms behind recurrent infections "
                        "and antibody deficiency?"
                    ),
                    "evidence_record_ids": [public_id],
                    "profile_revision_ids": [
                        self.observation_ids["infections"],
                        self.observation_ids["low_ig_current"],
                    ],
                    "hypothesis_ids": hypothesis_ids,
                    "gap_ids": gap_ids,
                },
            ],
            "clinical_boundary": properties["clinical_boundary"]["enum"][0],
            "change_summary": "Prepared a traceable Q76H research brief.",
        }
        return self.service.submit_agent_brief(self.investigation_id, brief)[
            "brief_version"
        ]

    def _final_report(self: BriefOwner, brief: JsonObject) -> JsonObject:
        investigation = self.service.investigation(self.investigation_id)
        artifacts = self.service.list_agent_research_artifacts(self.investigation_id)
        rounds = investigation.get("rounds") or []
        if len(rounds) != 3 or any(
            row.get("status") != "completed" or row.get("report_count") != 3
            for row in rounds
        ):
            raise RuntimeError("expected exactly three completed three-report rounds")
        board = investigation.get("specialist_board") or {}
        if len(board.get("members") or []) != 3:
            raise RuntimeError("expected exactly three persistent specialists")
        all_evidence = investigation.get("evidence_records") or []
        paperclip_modes = sorted(
            {
                str(record.get("evidence", {}).get("access_mode"))
                for record in all_evidence
                if isinstance(record, dict)
                and record.get("source_family") == "literature"
                and isinstance(record.get("evidence"), dict)
            }
        )
        if paperclip_modes != ["fixture"]:
            raise RuntimeError(f"Paperclip must remain fixture replay: {paperclip_modes}")
        current_hypotheses = investigation.get("current_hypotheses") or []
        statuses = {str(item.get("status")) for item in current_hypotheses}
        if not {"supported", "weakened", "rejected", "candidate"}.issubset(statuses):
            raise RuntimeError(f"missing visible hypothesis transitions: {sorted(statuses)}")
        research_records = artifacts.get("research_artifacts") or []
        origins = {
            str(item.get("system")): str(item.get("origin"))
            for item in research_records
        }
        if origins.get("genomi") != "verified_scientific_operation":
            raise RuntimeError("Genomi sequence verification artifact is missing")
        if origins.get("esm") != "precomputed_fixture" or origins.get(
            "proto"
        ) != "precomputed_fixture":
            raise RuntimeError("ESM and Proto must remain precomputed fixtures")
        return {
            "status": "completed",
            "completed_at": _now(),
            "synthetic_patient": True,
            "fixture_mode": True,
            "genome_fixture_scope": "one-variant synthetic recording twin; not whole genome",
            "orchestration": "scripted fixture walkthrough; no live specialist agents",
            "investigation_id": self.investigation_id,
            "round_count": len(rounds),
            "rounds": [
                {
                    "round_number": row.get("round_number"),
                    "status": row.get("status"),
                    "report_count": row.get("report_count"),
                    "focus_question": row.get("focus_question"),
                }
                for row in rounds
            ],
            "specialist_count": 3,
            "hypothesis_statuses": sorted(statuses),
            "paperclip_evidence": {
                "route": "fixture_replay",
                "access_modes": paperclip_modes,
                "live_provider_execution_claimed": False,
            },
            "research_artifacts": [
                {
                    "system": row.get("system"),
                    "artifact_kind": row.get("artifact_kind"),
                    "round_number": row.get("round_number"),
                    "origin": row.get("origin"),
                    "scientific_execution_status": (
                        row.get("research_envelope") or {}
                    ).get("scientific_execution_status"),
                }
                for row in research_records
            ],
            "scientific_operations": {
                "genomi_sequence_verification": "verified_local_execution",
                "esm": "precomputed illustrative fixture only",
                "proto": "precomputed illustrative fixture only",
                "connection_check_used_as_execution": False,
            },
            "brief": {
                "version": brief.get("version"),
                "timeline_entries": len(brief["brief"].get("timeline") or []),
                "clinician_questions": len(
                    brief["brief"].get("clinician_questions") or []
                ),
                "clinical_boundary": brief["brief"].get("clinical_boundary"),
                "q76h_classification": "variant of uncertain significance",
            },
        }
