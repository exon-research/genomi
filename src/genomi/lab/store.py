"""Durable local state for the current Genomi user's research workspace."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Callable, Iterator

from ..runtime.paths import genomi_data_root
from .encrypted_sqlite import EncryptedSQLiteDatabase, EncryptionKeyProvider
from .approval_store import ApprovalStoreMixin
from .authorization_derivation_store import (
    InvestigationAuthorizationDerivationStoreMixin,
)
from .authorization_store import InvestigationAuthorizationStoreMixin
from .capability_store import CapabilityExecutionStoreMixin
from .disease_relations import DiseaseRelationStoreMixin
from .evidence_store import EvidenceStoreMixin
from .health_store import HealthRecordStoreMixin
from .investigation_store import InvestigationStoreMixin
from .investigation_cycle_store import InvestigationCycleStoreMixin
from .investigation_panel_store import InvestigationPanelStoreMixin
from .models import (
    DISPLAY_NAME_MAX,
    JsonObject,
    optional_text,
    row_dict,
    stable_id,
    utc_now,
)
from .profile_entities import ProfileEntityStoreMixin
from .report_store import ReportStoreMixin
from .schema_migrations import upgrade_lab_schema
from .snapshot_store import SnapshotStoreMixin


def lab_root(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "lab"


def default_store_path(root: str | Path | None = None) -> Path:
    return lab_root(root) / "genomilab.sqlite3"


class GenomiLabStore(
    InvestigationAuthorizationStoreMixin,
    InvestigationAuthorizationDerivationStoreMixin,
    ApprovalStoreMixin,
    HealthRecordStoreMixin,
    ProfileEntityStoreMixin,
    SnapshotStoreMixin,
    InvestigationStoreMixin,
    InvestigationCycleStoreMixin,
    InvestigationPanelStoreMixin,
    CapabilityExecutionStoreMixin,
    DiseaseRelationStoreMixin,
    EvidenceStoreMixin,
    ReportStoreMixin,
):
    """SQLite-backed GenomiLab domain state with one connection per operation."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        key_provider: EncryptionKeyProvider | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else default_store_path()
        self._database = EncryptedSQLiteDatabase(self.path, key_provider=key_provider)
        self._authority_local = threading.local()
        self._transaction_local = threading.local()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[object]:
        active = getattr(self._transaction_local, "connection", None)
        if active is not None:
            self._require_current_user_authority()
            yield active
            self._require_current_user_authority()
            return
        self._require_current_user_authority()
        with self._database.connect() as connection:
            yield connection
            # This check runs before EncryptedSQLiteDatabase serializes and
            # commits the transaction.  A user switch while a store call is
            # blocked therefore rolls the mutation back.
            self._require_current_user_authority()

    @contextmanager
    def atomic_write(self) -> Iterator[None]:
        """Commit a complete domain transition as one encrypted DB replacement.

        Store methods normally own one short transaction each. Application
        workflows that must update several aggregates can enter this boundary;
        their ordinary store calls then reuse the same SQLite connection. This
        keeps validation and persistence logic in the owning repositories while
        ensuring a late exception rolls back the complete transition.
        """

        if getattr(self._transaction_local, "connection", None) is not None:
            self._require_current_user_authority()
            yield
            self._require_current_user_authority()
            return
        self._require_current_user_authority()
        with self._database.connect() as connection:
            self._transaction_local.connection = connection
            try:
                yield
                self._require_current_user_authority()
            finally:
                self._transaction_local.connection = None

    @contextmanager
    def current_user_authority_guard(self, guard: Callable[[], None]) -> Iterator[None]:
        """Apply one service-owned authority check to this thread's store work."""

        if not callable(guard):
            raise TypeError("current-user authority guard must be callable")
        stack = list(getattr(self._authority_local, "guards", ()))
        stack.append(guard)
        self._authority_local.guards = tuple(stack)
        try:
            yield
        finally:
            remaining = list(getattr(self._authority_local, "guards", ()))
            if remaining:
                remaining.pop()
            self._authority_local.guards = tuple(remaining)

    def _require_current_user_authority(self) -> None:
        for guard in getattr(self._authority_local, "guards", ()):
            guard()

    def _initialize(self) -> None:
        with self._connect() as connection:
            legacy = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='profiles'"
            ).fetchone()
            if legacy:
                raise RuntimeError(
                    "This GenomiLab store uses the removed selectable-profile contract. "
                    "Move it aside and reopen GenomiLab to create the current user-keyed workspace."
                )
            upgrade_lab_schema(connection)
        self._harden_permissions()

    def _harden_permissions(self) -> None:
        try:
            self.path.chmod(0o600)
            for suffix in ("-wal", "-shm"):
                sidecar = self.path.with_name(f"{self.path.name}{suffix}")
                if sidecar.exists():
                    sidecar.chmod(0o600)
        except OSError:
            pass

    def open_workspace(
        self, user_id: object, display_name: object = None
    ) -> JsonObject:
        canonical_user_id = str(user_id or "").strip()
        if not canonical_user_id:
            raise ValueError("user_id is required")
        name = optional_text(display_name, "display_name", DISPLAY_NAME_MAX)
        workspace_id = stable_id("workspace", canonical_user_id)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workspaces(workspace_id, user_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, workspaces.display_name)
                """,
                (workspace_id, canonical_user_id, name, now, now),
            )
        return self.get_workspace(canonical_user_id)

    def get_workspace(self, user_id: str) -> JsonObject:
        with self._connect() as connection:
            workspace = connection.execute(
                "SELECT * FROM workspaces WHERE user_id = ?", (user_id,)
            ).fetchone()
            if workspace is None:
                raise KeyError(user_id)
            investigations = connection.execute(
                "SELECT * FROM investigations WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        result = row_dict(workspace)
        result["profile"] = {
            "user_id": user_id,
            "observations": self.list_profile_observations(user_id, current_only=True),
            "observation_history": self.list_profile_observations(
                user_id, current_only=False
            ),
            "modality_coverage": self.modality_coverage(user_id),
            **self.list_profile_entities(user_id),
            "genome": None,
        }
        result["investigations"] = [
            self._investigation_view(row) for row in investigations
        ]
        return result

    def list_workspace_user_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM workspaces ORDER BY created_at"
            ).fetchall()
        return [str(row["user_id"]) for row in rows]

    def _require_workspace(self, user_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM workspaces WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise KeyError(user_id)

    @staticmethod
    def _investigation_view(row: object) -> JsonObject:
        return row_dict(row)

    def indexes_for(self, table: str) -> list[str]:
        allowed = {
            "molecular_observations",
            "profile_snapshots",
            "consent_receipts",
            "investigations",
            "investigation_authorization_receipts",
            "investigation_authorization_derivations",
            "evidence_records",
        }
        if table not in allowed:
            raise ValueError("unsupported table")
        with self._connect() as connection:
            rows = connection.execute(f"PRAGMA index_list({table})").fetchall()
        return [str(row["name"]) for row in rows]
