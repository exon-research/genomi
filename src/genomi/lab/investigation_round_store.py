"""Immutable investigation-round and specialist-report persistence."""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from .models import JsonObject, compact_json, row_dict, stable_id, utc_now


class _RoundStore(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


class InvestigationRoundStoreMixin:
    """Persist one specialist round for each accepted plan version."""

    def create_investigation_round(
        self: _RoundStore,
        investigation_id: str,
        *,
        plan_version_id: str,
        focus_question: str,
        specialist_assignments: list[JsonObject],
    ) -> JsonObject:
        with self._connect() as connection:
            plan = connection.execute(
                "SELECT plan_version_id, investigation_id, "
                "patient_molecular_snapshot_id, version FROM plan_versions "
                "WHERE plan_version_id = ? AND investigation_id = ?",
                (plan_version_id, investigation_id),
            ).fetchone()
            if plan is None:
                raise ValueError("the investigation plan version does not exist")
            snapshot_id = str(plan["patient_molecular_snapshot_id"] or "")
            if not snapshot_id:
                raise ValueError(
                    "an investigation round requires an approved profile snapshot"
                )
            existing = connection.execute(
                "SELECT * FROM investigation_rounds WHERE plan_version_id = ?",
                (plan_version_id,),
            ).fetchone()
            if existing is not None:
                current = self._investigation_round_view(connection, existing)
                saved_assignments = [
                    {
                        "specialist_id": item.get("specialist_id"),
                        "task": item.get("task"),
                    }
                    for item in current.get("specialist_assignments") or []
                    if isinstance(item, dict)
                ]
                if (
                    current.get("focus_question") != focus_question
                    or saved_assignments != specialist_assignments
                ):
                    raise ValueError(
                        "the saved investigation round does not match this plan"
                    )
                return current

            prior = connection.execute(
                "SELECT * FROM investigation_rounds WHERE investigation_id = ? "
                "ORDER BY round_number DESC LIMIT 1",
                (investigation_id,),
            ).fetchone()
            round_number = int(plan["version"])
            if prior is not None and int(prior["round_number"]) >= round_number:
                raise ValueError("investigation rounds must follow plan-version order")
            round_id = stable_id(
                "investigation-round", investigation_id, plan_version_id
            )
            created_at = utc_now()
            connection.execute(
                "INSERT INTO investigation_rounds("
                "round_id, investigation_id, plan_version_id, "
                "patient_molecular_snapshot_id, round_number, prior_round_id, "
                "focus_question, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    round_id,
                    investigation_id,
                    plan_version_id,
                    snapshot_id,
                    round_number,
                    str(prior["round_id"]) if prior is not None else None,
                    focus_question,
                    created_at,
                ),
            )
            for assignment in specialist_assignments:
                specialist_id = str(assignment["specialist_id"])
                connection.execute(
                    "INSERT INTO specialist_round_assignments("
                    "assignment_id, round_id, specialist_id, task, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        stable_id(
                            "specialist-round-assignment",
                            round_id,
                            specialist_id,
                        ),
                        round_id,
                        specialist_id,
                        str(assignment["task"]),
                        created_at,
                    ),
                )
            row = connection.execute(
                "SELECT * FROM investigation_rounds WHERE round_id = ?",
                (round_id,),
            ).fetchone()
            return self._investigation_round_view(connection, row)

    def get_investigation_round(
        self: _RoundStore, investigation_id: str, round_id: str
    ) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_rounds "
                "WHERE round_id = ? AND investigation_id = ?",
                (round_id, investigation_id),
            ).fetchone()
            if row is None:
                raise KeyError(round_id)
            return self._investigation_round_view(connection, row)

    def list_investigation_rounds(
        self: _RoundStore, investigation_id: str
    ) -> list[JsonObject]:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(investigation_id)
            rows = connection.execute(
                "SELECT * FROM investigation_rounds WHERE investigation_id = ? "
                "ORDER BY round_number",
                (investigation_id,),
            ).fetchall()
            return [self._investigation_round_view(connection, row) for row in rows]

    def commit_specialist_round_report(
        self: _RoundStore,
        investigation_id: str,
        *,
        round_id: str,
        specialist_id: str,
        report: JsonObject,
    ) -> tuple[JsonObject, bool]:
        """Commit the one immutable report for a round assignment."""

        with self._connect() as connection:
            round_row = connection.execute(
                "SELECT * FROM investigation_rounds "
                "WHERE round_id = ? AND investigation_id = ?",
                (round_id, investigation_id),
            ).fetchone()
            if round_row is None:
                raise KeyError(round_id)
            assignment = connection.execute(
                "SELECT 1 FROM specialist_round_assignments "
                "WHERE round_id = ? AND specialist_id = ?",
                (round_id, specialist_id),
            ).fetchone()
            if assignment is None:
                raise ValueError(
                    "the specialist is not assigned to this investigation round"
                )
            self._validate_round_report_anchors(
                connection,
                investigation_id=investigation_id,
                patient_molecular_snapshot_id=str(
                    round_row["patient_molecular_snapshot_id"]
                ),
                report=report,
            )
            existing = connection.execute(
                "SELECT * FROM specialist_round_reports "
                "WHERE round_id = ? AND specialist_id = ?",
                (round_id, specialist_id),
            ).fetchone()
            if existing is not None:
                saved = row_dict(existing)
                if saved.get("report") != report:
                    raise ValueError(
                        "a different specialist report is already committed for this round"
                    )
                return saved, True
            report_id = stable_id("specialist-round-report", round_id, specialist_id)
            connection.execute(
                "INSERT INTO specialist_round_reports("
                "report_id, round_id, specialist_id, report_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    report_id,
                    round_id,
                    specialist_id,
                    compact_json(report),
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE investigations SET domain_revision = domain_revision + 1, "
                "updated_at = ? WHERE investigation_id = ?",
                (utc_now(), investigation_id),
            )
            row = connection.execute(
                "SELECT * FROM specialist_round_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            return row_dict(row), False

    @staticmethod
    def _validate_round_report_anchors(
        connection: Any,
        *,
        investigation_id: str,
        patient_molecular_snapshot_id: str,
        report: JsonObject,
    ) -> None:
        evidence_ids: set[str] = set()
        profile_ids: set[str] = set()
        for collection in (report.get("findings"), report.get("gaps")):
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict):
                    continue
                evidence_ids.update(
                    str(value) for value in item.get("evidence_record_ids") or []
                )
                profile_ids.update(
                    str(value) for value in item.get("profile_revision_ids") or []
                )

        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            rows = connection.execute(
                f"SELECT evidence_record_id FROM evidence_records "
                f"WHERE investigation_id = ? "
                f"AND patient_molecular_snapshot_id = ? "
                f"AND evidence_record_id IN ({placeholders})",
                (
                    investigation_id,
                    patient_molecular_snapshot_id,
                    *sorted(evidence_ids),
                ),
            ).fetchall()
            found = {str(row["evidence_record_id"]) for row in rows}
            if found != evidence_ids:
                raise ValueError(
                    "specialist report evidence must belong to the round's approved profile snapshot"
                )

        snapshot = connection.execute(
            "SELECT observation_revision_ids_json FROM profile_snapshots "
            "WHERE patient_molecular_snapshot_id = ? AND investigation_id = ?",
            (patient_molecular_snapshot_id, investigation_id),
        ).fetchone()
        if snapshot is None:
            raise ValueError("the investigation round profile snapshot is unavailable")
        available_profile_ids = set(
            row_dict(snapshot).get("observation_revision_ids") or []
        )
        if not profile_ids.issubset(available_profile_ids):
            raise ValueError(
                "specialist report profile anchors must belong to the round's approved profile snapshot"
            )

    @staticmethod
    def _investigation_round_view(connection: Any, row: Any) -> JsonObject:
        view = row_dict(row)
        assignments = connection.execute(
            "SELECT specialist_id, task, created_at "
            "FROM specialist_round_assignments WHERE round_id = ? "
            "ORDER BY specialist_id",
            (view["round_id"],),
        ).fetchall()
        reports = connection.execute(
            "SELECT * FROM specialist_round_reports WHERE round_id = ? "
            "ORDER BY specialist_id",
            (view["round_id"],),
        ).fetchall()
        view["specialist_assignments"] = [row_dict(item) for item in assignments]
        view["specialist_reports"] = [row_dict(item) for item in reports]
        return view


__all__ = ["InvestigationRoundStoreMixin"]
