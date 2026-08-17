"""Three staged patient feedback/testing updates between panel passes."""

from __future__ import annotations

from typing import Any, Protocol

from .constants import JsonObject, approval


class FollowupOwner(Protocol):
    service: Any
    investigation_id: str
    observation_ids: dict[str, str]

    def emit(self, stage: str, title: str, detail: str, **kwargs: Any) -> None: ...
    def _source_artifact(self, title: str, source_type: str, issued_at: str) -> JsonObject: ...


class FollowupMixin:
    def _followup_a(self: FollowupOwner) -> None:
        """Return the chronology and broad immune workup requested in round 1."""

        older = self._source_artifact(
            "Older infection and immune laboratory records", "issued_report", "2018-02-03"
        )
        immune = self._source_artifact(
            "Clinician-ordered immune testing and pathology review",
            "laboratory_report",
            "2026-07-20",
        )
        rows = [
            (
                "pneumonia_before_biologic",
                "phenotype",
                "Pneumonia documented before the first biologic",
                older,
                {"original_wording": "I found a pneumonia record from before my first biologic"},
            ),
            (
                "low_ig_before_rituximab",
                "measurement",
                "Low immunoglobulins documented before rituximab",
                older,
                {"original_wording": "An old blood test showed low antibody levels before rituximab"},
            ),
            ("low_ig_current", "measurement", "Persistently low IgG and IgA", immune, {}),
            (
                "vaccine_response",
                "biomarker",
                "Inadequate pneumococcal antibody response",
                immune,
                {},
            ),
            ("b_cell", "biomarker", "Abnormal B-cell maturation", immune, {}),
            (
                "pathology",
                "pathology",
                "Bowel pathology raises immune-mediated enteropathy as a possibility",
                immune,
                {},
            ),
        ]
        self._record_followup(rows)
        self.emit(
            "patient_followup_a",
            "The patient returns with older records and a broad immune workup",
            "Pneumonia and low immunoglobulins predate major therapy; current immunoglobulins, vaccine response, B-cell maturation, and pathology sharpen the next questions.",
            scroll_target="#molecular-profile",
        )

    def _followup_b(self: FollowupOwner) -> None:
        """Return confirmation and abundance studies requested after round 2."""

        functional = self._source_artifact(
            "Clinical CTLA4 confirmation and abundance testing report",
            "laboratory_report",
            "2026-08-01",
        )
        specimen = self.service.add_specimen(
            {
                "artifact_id": functional["artifact_id"],
                "specimen_type": "blood",
                "tumor_normal_role": "germline",
                "collected_at": "2026-07-15",
            }
        )
        assay = self.service.add_assay(
            {
                "artifact_id": functional["artifact_id"],
                "specimen_id": specimen["specimen_id"],
                "assay_type": "focused_dna_panel",
                "laboratory": "Synthetic reference immunology laboratory",
                "genome_build": "GRCh38",
                "assay_scope": {"genes": ["CTLA4"]},
                "detection_limits": {"reporting_boundary": "synthetic demo fixture"},
            }
        )
        rows = [
            (
                "q76h_report",
                "reported_germline_finding",
                "Clinical laboratory confirmed CTLA4 Q76H as a variant of uncertain significance",
                functional,
                {
                    "original_wording": "The clinical lab confirmed Q76H and still called it uncertain",
                    "reported_variant": "rs2469719303",
                    "gene": "CTLA4",
                    "reported_classification": "variant of uncertain significance",
                    "specimen_id": specimen["specimen_id"],
                    "assay_id": assay["assay_id"],
                },
            ),
            (
                "ctla4_staining",
                "biomarker",
                "CTLA4 staining within the laboratory control range",
                functional,
                {},
            ),
            (
                "lrba_expression",
                "biomarker",
                "LRBA expression within the laboratory control range",
                functional,
                {},
            ),
        ]
        self._record_followup(rows)
        self.emit(
            "patient_followup_b",
            "Clinical confirmation and abundance studies arrive",
            "The clinical laboratory still classifies Q76H as a VUS; CTLA4 staining and LRBA expression are within the reported control ranges.",
            scroll_target="#molecular-profile",
        )

    def _request_followup_c(self: FollowupOwner) -> None:
        self.emit(
            "round_3_targeted_request",
            "Round 3 opens one last evidence gap",
            "The panel asks for two independently repeated ligand-removal assays and targeted family testing before final synthesis.",
            scroll_target="#specialist-board",
        )

    def _followup_c(self: FollowupOwner) -> None:
        """Return the final repeated function and segregation observations."""

        repeat = self._source_artifact(
            "Repeated CTLA4 functional assay and family testing report",
            "laboratory_report",
            "2026-08-12",
        )
        rows = [
            (
                "ctla4_function",
                "biomarker",
                "Two independent CTLA4 transendocytosis repeats showed reduced activity under the reported protocol",
                repeat,
                {},
            ),
            (
                "mother_carrier",
                "family_history",
                "Apparently healthy mother carrying CTLA4 Q76H",
                repeat,
                {"original_wording": "My mother carries Q76H and is apparently healthy"},
            ),
        ]
        self._record_followup(rows)
        self.emit(
            "patient_followup_c",
            "The patient returns with repeated function and family results",
            "Both reported repeats show reduced transendocytosis, while the mother carries Q76H and is apparently healthy; the conflict now becomes the focus of round 3.",
            scroll_target="#molecular-profile",
        )

    def _record_followup(
        self: FollowupOwner,
        rows: list[tuple[str, str, str, JsonObject, JsonObject]],
    ) -> None:
        observations = [
            {
                "modality": modality,
                "label": label,
                "artifact_id": artifact["artifact_id"],
                "assertion_status": "present",
                "verification_state": "user_confirmed",
                "source_class": "issued_record",
                **extras,
            }
            for _key, modality, label, artifact, extras in rows
        ]
        recorded = self.service.record_agent_patient_observations(
            self.investigation_id, observations
        )
        for (key, *_), observation in zip(
            rows, recorded["recorded_observations"], strict=True
        ):
            self.observation_ids[key] = str(observation["observation_revision_id"])
        self.service.authorize_investigation_context(
            self.investigation_id,
            approval(recorded["authorization"]["candidate"]),
        )
