"""Structural dependencies required by investigation capability orchestration."""

from __future__ import annotations

from typing import Protocol

from .models import JsonObject


class CapabilityStore(Protocol):
    def get_capability_execution(
        self, investigation_id: str, plan_version_id: str, request_id: str
    ) -> JsonObject | None: ...

    def finish_capability_execution(
        self,
        capability_execution_id: str,
        *,
        attempt_number: int,
        claimed_job_id: str,
        status: str,
        result: JsonObject,
        job_id: object = None,
        resume_operation: object = None,
        poll_after_seconds: object = None,
    ) -> JsonObject: ...

    def commit_disease_relation(
        self,
        investigation_id: str,
        params: JsonObject,
        *,
        expected_plan_version_id: str | None,
        expected_consent_receipt_id: str | None,
    ) -> JsonObject: ...

    def commit_hypothesis(
        self,
        investigation_id: str,
        *,
        kind: object,
        statement: object,
        evidence_record_ids: object,
        profile_revision_ids: object,
        status: object,
        supersedes_hypothesis_id: object,
        expected_plan_version_id: str | None,
        expected_consent_receipt_id: str | None,
    ) -> JsonObject: ...

    def get_profile_snapshot(self, snapshot_id: str) -> JsonObject: ...


class CapabilityApplication(Protocol):
    store: CapabilityStore

    def investigation(self, investigation_id: str) -> JsonObject: ...
    def _accepted_current_plan(self, investigation_id: str) -> JsonObject: ...
    def investigation_profile(self, investigation_id: str) -> JsonObject: ...
    def investigation_capability_catalog(
        self, investigation_id: str
    ) -> JsonObject: ...

    def require_capability_commit_authority(
        self,
        investigation_id: str,
        *,
        expected_plan_version_id: str | None,
        expected_consent_receipt_id: str | None,
    ) -> JsonObject: ...

    def invoke_investigation_genome(
        self,
        investigation_id: str,
        *,
        operation: str,
        params: JsonObject,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject: ...

    def _active_context_receipt(
        self, investigation: JsonObject, snapshot: JsonObject
    ) -> JsonObject: ...

    def evidence_capability_manifest(self) -> JsonObject: ...
    def evidence_disclosure_candidate(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...
    def approve_evidence_disclosure(
        self, investigation_id: str, payload: JsonObject
    ) -> JsonObject: ...

    def retrieve_public_evidence(
        self,
        investigation_id: str,
        payload: JsonObject,
        *,
        expected_plan_version_id: str | None = None,
        expected_consent_receipt_id: str | None = None,
    ) -> JsonObject: ...

    def resume_public_evidence_job(
        self,
        investigation_id: str,
        *,
        execution: JsonObject,
        job_id: str,
        resume_operation: str,
    ) -> JsonObject: ...

    def check_investigation_genome_job(
        self,
        investigation_id: str,
        *,
        job_id: str,
        resume_operation: str,
        expected_plan_version_id: str,
        expected_consent_receipt_id: str,
    ) -> JsonObject: ...


__all__ = ["CapabilityApplication", "CapabilityStore"]
