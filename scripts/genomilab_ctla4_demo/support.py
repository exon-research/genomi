"""Shared typed operations used by the three demo rounds."""

from __future__ import annotations

import time
from typing import Any, Protocol

from .constants import SPECIALISTS, JsonObject, sha256_text


class FlowOwner(Protocol):
    service: Any
    investigation_id: str
    step_delay: float
    observation_ids: dict[str, str]
    hypothesis_ids: dict[str, str]
    operation_results: dict[str, JsonObject]


class FlowSupportMixin:
    def _assignments(
        self: FlowOwner, round_number: int, tasks: list[str]
    ) -> list[JsonObject]:
        return [
            {
                "specialist_id": specialist["specialist_id"],
                "task": f"Round {round_number}: {task}",
            }
            for specialist, task in zip(SPECIALISTS, tasks, strict=True)
        ]

    def _set_working(
        self: FlowOwner, round_id: str, messages: list[str]
    ) -> None:
        for specialist, message in zip(SPECIALISTS, messages, strict=True):
            self.service.report_agent_specialist_progress(
                self.investigation_id,
                round_id=round_id,
                specialist_id=specialist["specialist_id"],
                status="working",
                current_work=message,
            )

    def _execute_requests(
        self: FlowOwner, request_ids: list[str]
    ) -> dict[str, JsonObject]:
        results = {}
        for request_id in request_ids:
            response = self.service.execute_agent_request(
                self.investigation_id, request_id
            )
            if response.get("status") != "completed":
                raise RuntimeError(f"request {request_id} did not complete: {response}")
            results[request_id] = response["result"]
            self.operation_results[request_id] = response["result"]
        return results

    def _working_hypothesis_request(
        self: FlowOwner,
        *,
        request_id: str,
        label: str,
        profile_key: str,
        status: str = "candidate",
        supersedes: str | None = None,
    ) -> JsonObject:
        anchor = self._observation_label(profile_key)
        parameters: JsonObject = {
            "kind": "working_hypothesis",
            "statement": (
                f"Working hypothesis: {label}. Model inference: The reported "
                f"record {anchor} may support this possible candidate hypothesis."
            ),
            "evidence_record_ids": [],
            "profile_revision_ids": [self.observation_ids[profile_key]],
            "status": status,
        }
        if supersedes:
            parameters["supersedes_hypothesis_id"] = supersedes
        return {
            "id": request_id,
            "capability": "investigation.register_hypothesis",
            "parameters": parameters,
        }

    def _observation_label(self: FlowOwner, key: str) -> str:
        observation_id = self.observation_ids[key]
        for row in self.service.molecular_profile().get("observations") or []:
            if row.get("observation_revision_id") == observation_id:
                return str(row["label"])
        raise KeyError(observation_id)

    def _candidate_scan_parameters(
        self: FlowOwner, catalog: JsonObject
    ) -> JsonObject:
        fields = catalog["genomi.variant.find_gene_variants"]["request_contract"][
            "fields"
        ]
        return {
            "genes": ["CTLA4", "LRBA", "NFKB1", "TNFRSF13B", "PIK3CD"],
            "agi_id": fields["agi_id"]["fixed_value"],
            "agi_snapshot_id": fields["agi_snapshot_id"]["fixed_value"],
            "genome_build": fields["genome_build"]["fixed_value"],
            "per_gene_limit": fields["per_gene_limit"]["fixed_value"],
            "candidate_set_lineage": {
                "specialist_id": "specialist-immune-genetics",
                "profile_revision_ids": [self.observation_ids["infections"]],
                "evidence_record_ids": [],
            },
        }

    def _focused_public_request(
        self: FlowOwner,
        catalog: JsonObject,
        capability: str,
        query: str,
        terms: list[str],
        *,
        profile_key: str = "q76h_report",
    ) -> JsonObject:
        operations = catalog[capability]["request_contract"]["fields"]["operation"][
            "allowed_values"
        ]
        return {
            "profile_revision_ids": [self.observation_ids[profile_key]],
            "operation": "search" if "search" in operations else operations[0],
            "query": query,
            "query_terms": terms,
            "filters": {},
            "purpose": "Investigate disease relevance against the selected molecular profile",
        }

    @staticmethod
    def _finding(
        statement: str,
        stance: str,
        *,
        evidence_ids: list[str] | None = None,
        profile_ids: list[str] | None = None,
    ) -> JsonObject:
        return {
            "statement": statement,
            "stance": stance,
            "evidence_record_ids": evidence_ids or [],
            "profile_revision_ids": profile_ids or [],
        }

    @staticmethod
    def _gap(
        question: str,
        *,
        evidence_ids: list[str] | None = None,
        profile_ids: list[str] | None = None,
    ) -> JsonObject:
        return {
            "question": question,
            "evidence_record_ids": evidence_ids or [],
            "profile_revision_ids": profile_ids or [],
        }

    def _reports(
        self: FlowOwner, round_id: str, reports: list[JsonObject]
    ) -> None:
        for specialist, report in zip(SPECIALISTS, reports, strict=True):
            self.service.record_agent_specialist_report(
                self.investigation_id,
                round_id=round_id,
                specialist_id=specialist["specialist_id"],
                report=report,
            )
            if self.step_delay > 0:
                time.sleep(self.step_delay / 2)

    def _source_artifact(
        self: FlowOwner, title: str, source_type: str, issued_at: str
    ) -> JsonObject:
        return self.service.add_source_artifact(
            {
                "content_sha256": sha256_text(f"synthetic-demo:{title}:{issued_at}"),
                "source_type": source_type,
                "title": title,
                "source_identifier": f"SYNTH-{sha256_text(title)[:12]}",
                "issued_at": issued_at,
            }
        )
