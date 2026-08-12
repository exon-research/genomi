"""Background-job, consent, and investigation persistence."""

from __future__ import annotations

import json
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    QUESTION_MAX,
    SOURCE_LABEL_MAX,
    JsonObject,
    investigation_view,
    required_text,
    row_dict,
    utc_now,
)


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_profile(self, profile_id: str) -> None: ...

    def get_finding(self, finding_id: str) -> JsonObject: ...


class WorkflowStoreMixin:
    """Methods mixed into ``GenomiLabStore`` for resumable work state."""

    def create_job(
        self: _StoreContract,
        profile_id: str,
        *,
        operation: str,
        status: str,
        staged_name: str | None,
        genomi_job_id: str | None = None,
    ) -> JsonObject:
        self._require_profile(profile_id)
        portal_job_id = f"job-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO portal_jobs(
                    portal_job_id, profile_id, genomi_job_id, operation, status,
                    staged_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    portal_job_id,
                    profile_id,
                    genomi_job_id,
                    operation,
                    status,
                    staged_name,
                    now,
                    now,
                ),
            )
        return self.get_job(portal_job_id)

    def update_job(
        self: _StoreContract,
        portal_job_id: str,
        *,
        status: str,
        genomi_job_id: str | None = None,
        error_code: str | None = None,
    ) -> JsonObject:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE portal_jobs
                   SET status = ?, genomi_job_id = COALESCE(?, genomi_job_id),
                       error_code = ?, updated_at = ?
                 WHERE portal_job_id = ?
                """,
                (status, genomi_job_id, error_code, utc_now(), portal_job_id),
            )
            if updated.rowcount != 1:
                raise KeyError(portal_job_id)
        return self.get_job(portal_job_id)

    def get_job(self: _StoreContract, portal_job_id: str) -> JsonObject:
        result = self.job_internal(portal_job_id)
        result.pop("staged_name", None)
        result.pop("genomi_job_id", None)
        return result

    def job_internal(self: _StoreContract, portal_job_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM portal_jobs WHERE portal_job_id = ?", (portal_job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(portal_job_id)
        return row_dict(row)

    def record_consent(
        self: _StoreContract,
        profile_id: str,
        *,
        agi_id: str,
        session_id: str,
        purpose: object,
    ) -> JsonObject:
        self._require_profile(profile_id)
        purpose_value = required_text(purpose, "purpose", QUESTION_MAX)
        consent_id = f"consent-{uuid.uuid4().hex}"
        approved_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO consent_receipts(
                    consent_id, profile_id, agi_id, session_id, purpose, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (consent_id, profile_id, agi_id, session_id, purpose_value, approved_at),
            )
        return {
            "consent_id": consent_id,
            "profile_id": profile_id,
            "agi_id": agi_id,
            "purpose": purpose_value,
            "approved_at": approved_at,
            "session_only": True,
        }

    def revoke_session_consents(self: _StoreContract, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE consent_receipts SET revoked_at = ? "
                "WHERE session_id = ? AND revoked_at IS NULL",
                (utc_now(), session_id),
            )

    def has_session_consent(
        self: _StoreContract, profile_id: str, session_id: str, agi_id: str
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM consent_receipts
                 WHERE profile_id = ? AND session_id = ? AND agi_id = ?
                   AND revoked_at IS NULL
                 LIMIT 1
                """,
                (profile_id, session_id, agi_id),
            ).fetchone()
        return row is not None

    def create_investigation(
        self: _StoreContract,
        profile_id: str,
        *,
        question: object,
        finding_id: object,
    ) -> JsonObject:
        self._require_profile(profile_id)
        question_value = required_text(question, "question", QUESTION_MAX)
        finding_value = required_text(finding_id, "finding_id", SOURCE_LABEL_MAX)
        finding = self.get_finding(finding_value)
        if finding["profile_id"] != profile_id:
            raise ValueError("finding_id must belong to this profile")
        investigation_id = f"investigation-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO investigations(
                    investigation_id, profile_id, finding_id, question,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (investigation_id, profile_id, finding_value, question_value, now, now),
            )
        return self.get_investigation(investigation_id)

    def complete_investigation(
        self: _StoreContract, investigation_id: str, brief: JsonObject
    ) -> JsonObject:
        return self._finish_investigation(
            investigation_id, status="completed", brief=brief
        )

    def fail_investigation(
        self: _StoreContract, investigation_id: str, code: str
    ) -> JsonObject:
        brief = {
            "status": "failed",
            "error": {
                "code": code,
                "message": "The investigation could not be completed.",
            },
        }
        return self._finish_investigation(
            investigation_id, status="failed", brief=brief
        )

    def _finish_investigation(
        self: _StoreContract,
        investigation_id: str,
        *,
        status: str,
        brief: JsonObject,
    ) -> JsonObject:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE investigations SET status = ?, brief_json = ?, updated_at = ?
                 WHERE investigation_id = ?
                """,
                (
                    status,
                    json.dumps(brief, separators=(",", ":")),
                    utc_now(),
                    investigation_id,
                ),
            )
            if updated.rowcount != 1:
                raise KeyError(investigation_id)
        return self.get_investigation(investigation_id)

    def get_investigation(
        self: _StoreContract, investigation_id: str
    ) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(investigation_id)
        return investigation_view(row)
