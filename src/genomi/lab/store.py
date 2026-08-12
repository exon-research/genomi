"""Durable, local-only state for GenomiLab patient research profiles.

The Genomi registry stays a small routing registry. Patient-entered health
context, consent receipts, jobs, and investigation briefs live in this
application-owned database.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..runtime.paths import genomi_data_root
from ..runtime.private_storage import ensure_private_directory, refuse_symlink
from .health_store import HealthRecordStoreMixin
from .models import (
    PROFILE_NAME_MAX,
    JsonObject,
    genome_view,
    investigation_view,
    profile_summary,
    required_text,
    row_dict,
    utc_now,
)
from .schema import SCHEMA_SQL
from .workflow_store import WorkflowStoreMixin


def lab_root(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "lab"


def default_store_path(root: str | Path | None = None) -> Path:
    return lab_root(root) / "genomilab.sqlite3"


class GenomiLabStore(HealthRecordStoreMixin, WorkflowStoreMixin):
    """SQLite-backed portal state with one connection per operation."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()
        ensure_private_directory(self.path.parent)
        refuse_symlink(self.path)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA_SQL)
        try:
            self.path.chmod(0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = self.path.with_name(f"{self.path.name}{suffix}")
                if sidecar.exists():
                    sidecar.chmod(0o600)
        except OSError:
            pass

    def create_profile(self, display_name: object) -> JsonObject:
        name = required_text(display_name, "display_name", PROFILE_NAME_MAX)
        profile_id = f"patient-{uuid.uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO profiles(profile_id, display_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (profile_id, name, now, now),
            )
        return self.get_profile(profile_id)

    def list_profiles(self) -> list[JsonObject]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*,
                       COUNT(DISTINCT hf.fact_id) AS health_fact_count,
                       COUNT(DISTINCT rf.finding_id) AS finding_count,
                       COUNT(DISTINCT i.investigation_id) AS investigation_count,
                       ga.agi_id, ga.genome_build, ga.readiness, ga.imported_at
                  FROM profiles p
             LEFT JOIN health_facts hf ON hf.profile_id = p.profile_id
             LEFT JOIN reported_findings rf ON rf.profile_id = p.profile_id
             LEFT JOIN investigations i ON i.profile_id = p.profile_id
             LEFT JOIN genome_assignments ga ON ga.profile_id = p.profile_id
              GROUP BY p.profile_id
              ORDER BY p.updated_at DESC
                """
            ).fetchall()
        return [profile_summary(row) for row in rows]

    def get_profile(self, profile_id: str) -> JsonObject:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.*, ga.agi_id, ga.genome_build, ga.readiness, ga.imported_at
                  FROM profiles p
             LEFT JOIN genome_assignments ga ON ga.profile_id = p.profile_id
                 WHERE p.profile_id = ?
                """,
                (profile_id,),
            ).fetchone()
            if row is None:
                raise KeyError(profile_id)
            facts = connection.execute(
                "SELECT * FROM health_facts WHERE profile_id = ? ORDER BY created_at DESC",
                (profile_id,),
            ).fetchall()
            findings = connection.execute(
                "SELECT * FROM reported_findings WHERE profile_id = ? ORDER BY created_at DESC",
                (profile_id,),
            ).fetchall()
            investigations = connection.execute(
                "SELECT * FROM investigations WHERE profile_id = ? ORDER BY created_at DESC",
                (profile_id,),
            ).fetchall()
        profile = row_dict(row)
        profile["genome"] = genome_view(row)
        for key in ("agi_id", "genome_build", "readiness", "imported_at"):
            profile.pop(key, None)
        profile["health_facts"] = [row_dict(item) for item in facts]
        profile["reported_findings"] = [row_dict(item) for item in findings]
        profile["investigations"] = [investigation_view(item) for item in investigations]
        return profile

    def set_active_profile(self, profile_id: str) -> None:
        self._require_profile(profile_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES ('active_profile_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (profile_id,),
            )

    def active_profile_id(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'active_profile_id'"
            ).fetchone()
        return str(row["value"]) if row else None

    def link_genomi_user(self, profile_id: str, genomi_user_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE profiles SET genomi_user_id = ?, updated_at = ? "
                "WHERE profile_id = ?",
                (genomi_user_id, now, profile_id),
            )
            if updated.rowcount != 1:
                raise KeyError(profile_id)

    def link_genome(
        self,
        profile_id: str,
        *,
        agi_id: str,
        genome_build: str | None,
        readiness: str,
    ) -> JsonObject:
        self._require_profile(profile_id)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO genome_assignments(
                    profile_id, agi_id, genome_build, readiness, imported_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    agi_id = excluded.agi_id,
                    genome_build = excluded.genome_build,
                    readiness = excluded.readiness,
                    imported_at = excluded.imported_at,
                    updated_at = excluded.updated_at
                """,
                (profile_id, agi_id, genome_build, readiness, now, now),
            )
            connection.execute(
                "UPDATE profiles SET updated_at = ? WHERE profile_id = ?",
                (now, profile_id),
            )
        return self.get_profile(profile_id)["genome"]

    def delete_profile(self, profile_id: str) -> None:
        with self._connect() as connection:
            removed = connection.execute(
                "DELETE FROM profiles WHERE profile_id = ?", (profile_id,)
            )
            if removed.rowcount != 1:
                raise KeyError(profile_id)
            connection.execute(
                "DELETE FROM settings WHERE key = 'active_profile_id' AND value = ?",
                (profile_id,),
            )

    def indexes_for(self, table: str) -> list[str]:
        allowed = {
            "health_facts",
            "reported_findings",
            "portal_jobs",
            "consent_receipts",
            "investigations",
        }
        if table not in allowed:
            raise ValueError("unsupported table")
        with self._connect() as connection:
            rows = connection.execute(f"PRAGMA index_list({table})").fetchall()
        return [str(row["name"]) for row in rows]

    def _require_profile(self, profile_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise KeyError(profile_id)
