"""Canonical investigations and approved molecular-profile projection."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    QUESTION_MAX,
    JsonObject,
    compact_json,
    optional_text,
    required_text,
    row_dict,
    utc_now,
)
from .investigation_rounds import project_investigation_rounds
from .research_artifact_contract import research_artifact_view
from .specialist_board import project_specialist_board


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...

    def _require_workspace(self, user_id: str) -> None: ...

    def get_investigation(self, investigation_id: str) -> JsonObject: ...

    def get_profile_snapshot(self, snapshot_id: str) -> JsonObject: ...

    def list_investigation_rounds(
        self, investigation_id: str
    ) -> list[JsonObject]: ...


class InvestigationStoreMixin:
    """Investigation lifecycle and pinned-profile projection persistence."""

    def create_investigation(
        self: _StoreContract,
        user_id: str,
        *,
        question: object,
        disease_scope: object = None,
    ) -> JsonObject:
        self._require_workspace(user_id)
        question_value = required_text(question, "question", QUESTION_MAX)
        investigation_id = f"investigation-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO investigations(
                    investigation_id, user_id, question, disease_scope, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'awaiting_plan', ?, ?)
                """,
                (
                    investigation_id,
                    user_id,
                    question_value,
                    optional_text(disease_scope, "disease_scope", QUESTION_MAX),
                    now,
                    now,
                ),
            )
        return self.get_investigation(investigation_id)

    def get_investigation(self: _StoreContract, investigation_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(investigation_id)
            evidence = connection.execute(
                "SELECT * FROM evidence_records WHERE investigation_id = ? ORDER BY created_at",
                (investigation_id,),
            ).fetchall()
            research_artifacts = connection.execute(
                "SELECT artifacts.*, rounds.round_number "
                "FROM research_artifacts AS artifacts "
                "JOIN investigation_rounds AS rounds "
                "ON rounds.round_id = artifacts.round_id "
                "WHERE artifacts.investigation_id = ? "
                "ORDER BY rounds.round_number, artifacts.created_at",
                (investigation_id,),
            ).fetchall()
            hypotheses = connection.execute(
                "SELECT * FROM hypotheses WHERE investigation_id = ? "
                "ORDER BY logical_hypothesis_id, version",
                (investigation_id,),
            ).fetchall()
            profile_snapshots = connection.execute(
                "SELECT * FROM profile_snapshots WHERE investigation_id = ? "
                "ORDER BY version",
                (investigation_id,),
            ).fetchall()
            evidence_snapshots = connection.execute(
                "SELECT * FROM evidence_snapshots WHERE investigation_id = ? "
                "ORDER BY version",
                (investigation_id,),
            ).fetchall()
            capability_executions = connection.execute(
                "SELECT * FROM capability_executions WHERE investigation_id = ? "
                "ORDER BY created_at",
                (investigation_id,),
            ).fetchall()
            capability_attempts = connection.execute(
                "SELECT attempts.* FROM capability_execution_attempts AS attempts "
                "JOIN capability_executions AS executions "
                "ON executions.capability_execution_id = attempts.capability_execution_id "
                "WHERE executions.investigation_id = ? "
                "ORDER BY attempts.capability_execution_id, attempts.attempt_number",
                (investigation_id,),
            ).fetchall()
            briefs = connection.execute(
                "SELECT * FROM brief_versions WHERE investigation_id = ? ORDER BY version",
                (investigation_id,),
            ).fetchall()
            plans = connection.execute(
                "SELECT * FROM plan_versions WHERE investigation_id = ? ORDER BY version",
                (investigation_id,),
            ).fetchall()
            plan_acceptances = connection.execute(
                "SELECT * FROM plan_acceptances WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchall()
            investigation_events = connection.execute(
                "SELECT * FROM investigation_events WHERE investigation_id = ? "
                "ORDER BY sequence",
                (investigation_id,),
            ).fetchall()
        result = row_dict(row)
        result["evidence_records"] = [row_dict(item) for item in evidence]
        result["research_artifacts"] = [
            research_artifact_view(row_dict(item)) for item in research_artifacts
        ]
        result["hypotheses"] = [row_dict(item) for item in hypotheses]
        active_profile_snapshot_id = result.get("patient_molecular_snapshot_id")
        result["current_research_artifacts"] = [
            item
            for item in result["research_artifacts"]
            if item["patient_molecular_snapshot_id"] == active_profile_snapshot_id
        ]
        current_evidence = [
            row_dict(item)
            for item in evidence
            if item["patient_molecular_snapshot_id"] == active_profile_snapshot_id
        ]
        current_hypothesis_rows = [
            item
            for item in hypotheses
            if item["patient_molecular_snapshot_id"] == active_profile_snapshot_id
        ]
        superseded = {
            str(item["supersedes_hypothesis_id"])
            for item in current_hypothesis_rows
            if item["supersedes_hypothesis_id"]
        }
        result["current_hypotheses"] = [
            row_dict(item)
            for item in current_hypothesis_rows
            if str(item["hypothesis_id"]) not in superseded
        ]
        result["current_evidence_records"] = current_evidence
        result["profile_snapshot_history"] = [
            row_dict(item) for item in profile_snapshots
        ]
        result["evidence_snapshots"] = [row_dict(item) for item in evidence_snapshots]
        current_evidence_snapshot = next(
            (
                row_dict(item)
                for item in reversed(evidence_snapshots)
                if str(item["evidence_snapshot_id"])
                == str(result.get("evidence_snapshot_id") or "")
                and item["patient_molecular_snapshot_id"] == active_profile_snapshot_id
            ),
            None,
        )
        result["current_evidence_snapshot"] = current_evidence_snapshot
        attempts_by_execution: dict[str, list[JsonObject]] = {}
        for item in capability_attempts:
            attempt = row_dict(item)
            attempts_by_execution.setdefault(
                str(attempt["capability_execution_id"]), []
            ).append(attempt)
        execution_views = []
        for item in capability_executions:
            execution = row_dict(item)
            execution["attempts"] = attempts_by_execution.get(
                str(execution["capability_execution_id"]), []
            )
            execution_views.append(execution)
        result["capability_executions"] = execution_views
        result["brief_versions"] = [row_dict(item) for item in briefs]
        acceptance_by_plan = {
            str(item["plan_version_id"]): row_dict(item) for item in plan_acceptances
        }
        plan_views: list[JsonObject] = []
        for item in plans:
            plan_view = row_dict(item)
            plan_view["plan_sha256"] = hashlib.sha256(
                compact_json(plan_view["plan"]).encode("utf-8")
            ).hexdigest()
            acceptance = acceptance_by_plan.get(str(plan_view["plan_version_id"]))
            plan_view["review_status"] = "accepted" if acceptance else "proposed"
            plan_view["acceptance"] = acceptance
            plan_views.append(plan_view)
        result["plan_versions"] = plan_views
        current_plan = next(
            (
                item
                for item in reversed(plan_views)
                if item["patient_molecular_snapshot_id"] == active_profile_snapshot_id
            ),
            None,
        )
        result["current_plan_version"] = current_plan
        result["plan"] = current_plan.get("plan") if current_plan else None
        current_plan_version_id = (
            current_plan.get("plan_version_id") if current_plan else None
        )
        result["current_capability_executions"] = (
            [
                item
                for item in execution_views
                if item["plan_version_id"] == current_plan_version_id
            ]
            if current_plan_version_id
            else []
        )
        current_evidence_ids = {
            str(item["evidence_record_id"]) for item in current_evidence
        }
        current_hypothesis_created = max(
            (str(item["created_at"]) for item in current_hypothesis_rows),
            default="",
        )
        current_plan_created = (
            str(current_plan.get("created_at") or "") if current_plan else ""
        )
        current_brief = None
        for item in reversed(briefs):
            if item["patient_molecular_snapshot_id"] != active_profile_snapshot_id:
                continue
            if str(item["evidence_snapshot_id"] or "") != str(
                result.get("evidence_snapshot_id") or ""
            ):
                continue
            pinned = current_evidence_snapshot or {}
            if set(pinned.get("evidence_record_ids") or []) != current_evidence_ids:
                continue
            if current_hypothesis_created and current_hypothesis_created > str(
                item["created_at"]
            ):
                continue
            if current_plan_created and current_plan_created > str(
                item["created_at"]
            ):
                continue
            current_brief = row_dict(item)
            break
        result["current_brief_version"] = current_brief
        result["brief"] = current_brief.get("brief") if current_brief else None
        result["refresh_lifecycle"] = self._refresh_lifecycle(
            profile_snapshots=result["profile_snapshot_history"],
            historical_evidence=result["evidence_records"],
            current_evidence=current_evidence,
            historical_hypotheses=result["hypotheses"],
            current_hypotheses=result["current_hypotheses"],
            historical_briefs=result["brief_versions"],
            current_brief=current_brief,
            current_plan=current_plan,
        )
        result["investigation_events"] = [
            row_dict(item) for item in investigation_events
        ]
        base_board = project_specialist_board(
            result["investigation_events"]
        )
        rounds = project_investigation_rounds(
            self.list_investigation_rounds(investigation_id),
            board=base_board,
            events=result["investigation_events"],
        )
        result["rounds"] = rounds
        current_round = next(
            (
                item
                for item in reversed(rounds)
                if item.get("plan_version_id") == current_plan_version_id
            ),
            None,
        )
        result["current_round"] = current_round
        if isinstance(base_board, dict) and isinstance(current_round, dict):
            result["specialist_board"] = {
                **base_board,
                "status": (
                    "formed"
                    if current_round.get("status") == "planned"
                    else current_round.get("status")
                ),
                "current_round_id": current_round.get("round_id"),
                "current_round_number": current_round.get("round_number"),
                "members": current_round.get("members") or [],
            }
        else:
            result["specialist_board"] = base_board
        return result

    @staticmethod
    def _refresh_lifecycle(
        *,
        profile_snapshots: list[JsonObject],
        historical_evidence: list[JsonObject],
        current_evidence: list[JsonObject],
        historical_hypotheses: list[JsonObject],
        current_hypotheses: list[JsonObject],
        historical_briefs: list[JsonObject],
        current_brief: JsonObject | None,
        current_plan: JsonObject | None,
    ) -> JsonObject:
        context_version = (
            int(profile_snapshots[-1]["version"]) if profile_snapshots else None
        )
        refreshed = bool(context_version and context_version > 1)
        requires_evidence_rerun = refreshed and not current_evidence
        latest_evidence_created = max(
            (str(item.get("created_at") or "") for item in current_evidence),
            default="",
        )
        latest_hypothesis_created = max(
            (str(item.get("created_at") or "") for item in current_hypotheses),
            default="",
        )
        requires_hypothesis_refresh = refreshed and (
            not current_hypotheses
            or latest_evidence_created > latest_hypothesis_created
        )
        current_plan_created = (
            str(current_plan.get("created_at") or "") if current_plan else ""
        )
        requires_replan = refreshed and (
            current_plan is None
            or (
                requires_hypothesis_refresh
                and latest_evidence_created > current_plan_created
            )
        )
        requires_new_brief = bool(
            profile_snapshots
            and current_brief is None
            and (
                refreshed or current_evidence or current_hypotheses or historical_briefs
            )
        )
        if not profile_snapshots:
            state = "context_not_approved"
        elif requires_replan:
            state = "replan_required"
        elif requires_evidence_rerun or requires_hypothesis_refresh:
            state = "evidence_and_hypothesis_rerun_required"
        elif requires_new_brief:
            state = "new_brief_required"
        elif current_brief is not None:
            state = "current"
        else:
            state = "investigation_in_progress"
        return {
            "state": state,
            "profile_context_version": context_version,
            "requires_replan": requires_replan,
            "requires_evidence_rerun": requires_evidence_rerun,
            "requires_hypothesis_refresh": requires_hypothesis_refresh,
            "requires_new_brief": requires_new_brief,
            "historical_evidence_record_count": len(historical_evidence)
            - len(current_evidence),
            "historical_hypothesis_count": len(historical_hypotheses)
            - len(current_hypotheses),
            "historical_brief_count": len(historical_briefs)
            - (1 if current_brief is not None else 0),
        }

    def list_investigations(self: _StoreContract, user_id: str) -> list[JsonObject]:
        self._require_workspace(user_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT investigation_id FROM investigations WHERE user_id = ? "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [self.get_investigation(str(row["investigation_id"])) for row in rows]

    def set_investigation_status(
        self: _StoreContract,
        investigation_id: str,
        status: object,
        *,
        expected_revision: int | None = None,
    ) -> JsonObject:
        allowed = {
            "awaiting_plan",
            "awaiting_plan_review",
            "awaiting_context_approval",
            "approved",
            "running",
            "needs_user_input",
            "paused_private_context",
            "completed",
            "cancelled",
            "failed",
        }
        status_value = required_text(status, "status", 80)
        if status_value not in allowed:
            raise ValueError("unsupported investigation status")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT domain_revision FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if current is None:
                raise KeyError(investigation_id)
            if expected_revision is not None and int(current["domain_revision"]) != int(
                expected_revision
            ):
                raise ValueError("investigation revision conflict")
            connection.execute(
                "UPDATE investigations SET status = ?, domain_revision = domain_revision + 1, "
                "updated_at = ? WHERE investigation_id = ?",
                (status_value, utc_now(), investigation_id),
            )
        return self.get_investigation(investigation_id)

    def project_investigation_profile(
        self: _StoreContract, investigation_id: str
    ) -> JsonObject:
        investigation = self.get_investigation(investigation_id)
        snapshot_id = investigation.get("patient_molecular_snapshot_id")
        if not snapshot_id:
            raise ValueError(
                "the investigation has no approved molecular-profile snapshot"
            )
        snapshot = self.get_profile_snapshot(str(snapshot_id))
        revision_ids = list(snapshot.get("observation_revision_ids") or [])
        artifact_ids = list(snapshot.get("artifact_ids") or [])
        specimen_ids = list(snapshot.get("specimen_ids") or [])
        assay_ids = list(snapshot.get("assay_ids") or [])
        with self._connect() as connection:
            rows = []
            if revision_ids:
                placeholders = ",".join("?" for _ in revision_ids)
                rows = connection.execute(
                    f"SELECT * FROM molecular_observations WHERE user_id = ? "
                    f"AND observation_revision_id IN ({placeholders})",
                    (investigation["user_id"], *revision_ids),
                ).fetchall()
            artifacts = self._rows_for_ids(
                connection,
                table="source_artifacts",
                identifier_column="artifact_id",
                identifiers=artifact_ids,
                user_id=str(investigation["user_id"]),
            )
            specimens = self._rows_for_ids(
                connection,
                table="specimens",
                identifier_column="specimen_id",
                identifiers=specimen_ids,
                user_id=str(investigation["user_id"]),
            )
            assays = self._rows_for_ids(
                connection,
                table="assays",
                identifier_column="assay_id",
                identifiers=assay_ids,
                user_id=str(investigation["user_id"]),
            )
        by_id = {str(row["observation_revision_id"]): row_dict(row) for row in rows}
        missing_revision_ids = sorted(set(revision_ids) - set(by_id))
        if missing_revision_ids:
            raise ValueError(
                "approved profile snapshot references missing observation revisions: "
                + ", ".join(missing_revision_ids)
            )
        return {
            "investigation_id": investigation_id,
            "patient_molecular_snapshot_id": snapshot_id,
            "user_id": investigation["user_id"],
            "agi_id": snapshot.get("agi_id"),
            "agi_snapshot_id": snapshot.get("agi_snapshot_id"),
            "observations": [by_id[revision_id] for revision_id in revision_ids],
            "source_artifacts": [row_dict(row) for row in artifacts],
            "specimens": [row_dict(row) for row in specimens],
            "assays": [row_dict(row) for row in assays],
            "modality_coverage": list(snapshot.get("modality_coverage") or []),
        }

    @staticmethod
    def _rows_for_ids(
        connection: Any,
        *,
        table: str,
        identifier_column: str,
        identifiers: list[str],
        user_id: str,
    ) -> list[Any]:
        allowed = {
            ("source_artifacts", "artifact_id"),
            ("specimens", "specimen_id"),
            ("assays", "assay_id"),
        }
        if (table, identifier_column) not in allowed:
            raise ValueError("unsupported profile projection entity")
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = list(
            connection.execute(
                f"SELECT * FROM {table} WHERE user_id = ? "
                f"AND {identifier_column} IN ({placeholders})",
                (user_id, *identifiers),
            ).fetchall()
        )
        returned_ids = {str(row[identifier_column]) for row in rows}
        missing_ids = sorted(set(identifiers) - returned_ids)
        if missing_ids:
            raise ValueError(
                f"approved profile snapshot references missing {table}: "
                + ", ".join(missing_ids)
            )
        by_id = {str(row[identifier_column]): row for row in rows}
        return [by_id[identifier] for identifier in identifiers]
