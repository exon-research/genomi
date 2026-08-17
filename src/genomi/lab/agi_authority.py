"""Process-local, investigation-bound Active Genome Index authorization.

This is an internal Python authority, not an MCP operation.  A trusted
GenomiLab application service may mint an opaque handle after it has recorded
the user's consent receipt.  The handle is useful only in this Python process,
for one exact variant target or one bounded candidate-gene policy, and while
the bound Genomi user and AGI revision still match the live registry and
on-disk index.

Ordinary chat-session AGI grants deliberately live in ``agi_access.py``.  They
do not mint, replace, or satisfy this stronger investigation authorization.
"""

from __future__ import annotations

import os
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from ..active_genome_index.revisions import (
    ActiveGenomeIndexArtifactIntegrityError,
    verify_immutable_agi_revision,
)
from ..active_genome_index.active_genome_index import (
    ActiveGenomeIndexNeed,
    open_reader,
)
from ..operations.registry.execution import (
    AgiReadLease,
    OperationExecutionContext,
    OperationExecutionContextError,
)
from ..runtime.paths import expand_user_path
from ..runtime.context.storage import load_context, load_registry
from .genomic_scope import (
    InvestigationAgiAuthorizationError,
    normalize_investigation_genomic_scope,
    validate_investigation_genome_request,
)


JsonObject = dict[str, Any]

_PROCESS_EPOCH = secrets.token_urlsafe(32)
_PROCESS_ID = os.getpid()
_CONSTRUCTOR_KEY = object()
_LOCK = threading.RLock()


class AgiAuthorizationHandle:
    """Opaque bearer handle for one process-local authorization record.

    The claims are retained only by the authority below.  The object cannot be
    directly constructed, copied, or serialized; its repr never includes its
    bearer token.
    """

    __slots__ = ("__weakref__",)

    def __init__(self, constructor_key: object) -> None:
        if constructor_key is not _CONSTRUCTOR_KEY:
            raise TypeError(
                "AgiAuthorizationHandle objects are issued only by the trusted Python authority"
            )

    def __repr__(self) -> str:
        return "<AgiAuthorizationHandle opaque>"

    def __copy__(self) -> object:
        raise TypeError("AgiAuthorizationHandle cannot be copied")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("AgiAuthorizationHandle cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("AgiAuthorizationHandle cannot be serialized")


@dataclass(frozen=True)
class _AuthorizationRecord:
    token: str
    epoch: str
    issuing_process_id: int
    workspace_session_id: str
    user_id: str
    investigation_id: str
    patient_molecular_snapshot_id: str
    consent_receipt_id: str
    agi_id: str
    agi_snapshot_id: str
    agi_artifact_sha256: str
    purpose: str
    genomic_scope: JsonObject
    revoked: bool = False


@dataclass(frozen=True)
class _ValidatedAuthorization:
    record: _AuthorizationRecord
    agi_record: JsonObject
    agi_path: Path


_AUTHORIZATIONS: dict[str, _AuthorizationRecord] = {}
_HANDLE_IDENTITIES: weakref.WeakKeyDictionary[
    AgiAuthorizationHandle, tuple[str, str]
] = weakref.WeakKeyDictionary()


def issue_investigation_agi_authorization(
    *,
    workspace_session_id: str,
    user_id: str,
    investigation_id: str,
    patient_molecular_snapshot_id: str,
    consent_receipt_id: str,
    agi_id: str,
    agi_snapshot_id: str,
    purpose: str,
    genomic_scope: Mapping[str, object],
) -> AgiAuthorizationHandle:
    """Mint an opaque handle after validating the exact live AGI revision.

    This function is intentionally keyword-only and is not registered in the
    operation catalog.  Its caller is trusted to have validated the referenced
    GenomiLab consent receipt and molecular-profile snapshot.
    """

    claims = {
        "workspace_session_id": _required_text(
            workspace_session_id, "workspace_session_id"
        ),
        "user_id": _required_text(user_id, "user_id"),
        "investigation_id": _required_text(investigation_id, "investigation_id"),
        "patient_molecular_snapshot_id": _required_text(
            patient_molecular_snapshot_id, "patient_molecular_snapshot_id"
        ),
        "consent_receipt_id": _required_text(
            consent_receipt_id, "consent_receipt_id"
        ),
        "agi_id": _required_text(agi_id, "agi_id"),
        "agi_snapshot_id": _required_text(agi_snapshot_id, "agi_snapshot_id"),
        "purpose": _required_text(purpose, "purpose", maximum=4000),
    }
    agi_record, agi_path = _validate_live_agi_binding(
        user_id=claims["user_id"],
        agi_id=claims["agi_id"],
        agi_snapshot_id=claims["agi_snapshot_id"],
    )
    normalized_scope = normalize_investigation_genomic_scope(
        genomic_scope,
        default_genome_build=str(agi_record.get("genome_build") or "GRCh38"),
    )
    if normalized_scope["genome_build"] != str(
        agi_record.get("genome_build") or "GRCh38"
    ):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization_scope",
            "genomic_scope genome_build must match the authorized Active Genome Index.",
        )
    token = secrets.token_urlsafe(48)
    record = _AuthorizationRecord(
        token=token,
        epoch=_PROCESS_EPOCH,
        issuing_process_id=_PROCESS_ID,
        genomic_scope=normalized_scope,
        agi_artifact_sha256=str(agi_record["agi_artifact_sha256"]),
        **claims,
    )
    # Keep this local validation variable intentionally used: issuance must
    # prove the on-disk snapshot before the bearer handle becomes live.
    if not agi_path.is_file():
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorized Active Genome Index is no longer available.",
        )
    with _LOCK:
        _AUTHORIZATIONS[token] = record
        handle = AgiAuthorizationHandle(_CONSTRUCTOR_KEY)
        _HANDLE_IDENTITIES[handle] = (token, _PROCESS_EPOCH)
    return handle


def revoke_investigation_agi_authorization(
    handle: AgiAuthorizationHandle,
) -> bool:
    """Revoke one handle.  Repeated revocation is safe and returns ``False``."""

    token, epoch = _handle_identity(handle)
    with _LOCK:
        record = _AUTHORIZATIONS.get(token)
        if record is None or epoch != _PROCESS_EPOCH:
            return False
        if record.revoked:
            return False
        _AUTHORIZATIONS[token] = replace(record, revoked=True)
    return True


def revoke_investigation_agi_authorizations_for_session(
    workspace_session_id: str,
) -> int:
    """Revoke every live handle for a GenomiLab workspace session."""

    session_id = _required_text(workspace_session_id, "workspace_session_id")
    revoked = 0
    with _LOCK:
        for token, record in list(_AUTHORIZATIONS.items()):
            if record.workspace_session_id != session_id or record.revoked:
                continue
            _AUTHORIZATIONS[token] = replace(record, revoked=True)
            revoked += 1
    return revoked


def revoke_investigation_agi_authorizations_for_investigation(
    *,
    user_id: str,
    investigation_id: str,
    except_handle: AgiAuthorizationHandle | None = None,
) -> int:
    """Revoke prior process-local bearers for one user's investigation.

    A newly committed molecular snapshot supersedes consent-bound handles from
    every open GenomiLab service in this process, not only the service that
    approved the refresh.  ``except_handle`` preserves the freshly staged
    bearer when the new snapshot still includes an AGI scope.
    """

    canonical_user_id = _required_text(user_id, "user_id")
    canonical_investigation_id = _required_text(
        investigation_id, "investigation_id"
    )
    except_token: str | None = None
    if except_handle is not None:
        except_token, except_epoch = _handle_identity(except_handle)
        if except_epoch != _PROCESS_EPOCH:
            raise InvestigationAgiAuthorizationError(
                "investigation_agi_authorization_process_mismatch",
                "The preserved investigation authorization belongs to a different process epoch.",
            )
    revoked = 0
    with _LOCK:
        if except_token is not None:
            preserved = _AUTHORIZATIONS.get(except_token)
            if (
                preserved is None
                or preserved.revoked
                or preserved.user_id != canonical_user_id
                or preserved.investigation_id != canonical_investigation_id
            ):
                raise InvestigationAgiAuthorizationError(
                    "invalid_investigation_agi_authorization",
                    "The preserved authorization does not match this investigation.",
                )
        for token, record in list(_AUTHORIZATIONS.items()):
            if (
                token == except_token
                or record.user_id != canonical_user_id
                or record.investigation_id != canonical_investigation_id
                or record.revoked
            ):
                continue
            _AUTHORIZATIONS[token] = replace(record, revoked=True)
            revoked += 1
    return revoked


def validate_investigation_agi_authorization_binding(
    handle: AgiAuthorizationHandle,
) -> JsonObject:
    """Validate one opaque handle and return only its safe binding claims.

    GenomiLab uses this immediately before an investigation genome invocation
    to prove that the process-local bearer still names the exact molecular
    snapshot, consent receipt, AGI revision, and scope currently pinned by the
    application domain. Validation rechecks current user and immutable
    registry claims; the read-context constructor performs the one full
    artifact verification immediately before data access.
    """

    return _safe_binding(
        _validate_handle(handle, verify_artifact=False).record
    )


def execution_context_for_investigation_authorization(
    handle: AgiAuthorizationHandle,
    *,
    operation: str,
    params: Mapping[str, object],
) -> OperationExecutionContext:
    """Translate a Lab authorization into the host-neutral operation boundary.

    Scope and live registry claims are checked before opening the reader.  The
    immutable artifact is then hashed exactly once by ``open_reader`` for this
    execution context; ordinary reader methods reuse that verification.
    """

    exact_params = dict(params)
    validated = _validate_handle(
        handle,
        operation=operation,
        params=exact_params,
        verify_artifact=False,
    )
    record = validated.record
    try:
        reader = open_reader(
            validated.agi_path,
            need=ActiveGenomeIndexNeed.VARIANT,
            genome_build=str(validated.agi_record.get("genome_build") or "GRCh38"),
            expected_artifact_sha256=record.agi_artifact_sha256,
            expected_snapshot_id=record.agi_snapshot_id,
        )
    except ActiveGenomeIndexArtifactIntegrityError as exc:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The on-disk Active Genome Index revision failed its integrity check.",
        ) from exc

    def revalidate() -> Mapping[str, object]:
        try:
            current = _validate_handle(
                handle,
                operation=operation,
                params=exact_params,
                verify_artifact=False,
            )
        except InvestigationAgiAuthorizationError as exc:
            raise OperationExecutionContextError(exc.code, str(exc)) from exc
        return {"authorization_binding": _safe_binding(current.record)}

    return OperationExecutionContext(
        operation=operation,
        params=exact_params,
        agi_read_lease=AgiReadLease(
            reader=reader,
            agi_record=validated.agi_record,
            selection="investigation_authorization",
        ),
        revalidate=revalidate,
    )


def _validate_handle(
    handle: AgiAuthorizationHandle,
    *,
    operation: str | None = None,
    params: Mapping[str, object] | None = None,
    verify_artifact: bool = True,
) -> _ValidatedAuthorization:
    token, epoch = _handle_identity(handle)
    if os.getpid() != _PROCESS_ID or epoch != _PROCESS_EPOCH:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_process_mismatch",
            "The investigation authorization belongs to a different process epoch.",
        )
    with _LOCK:
        record = _AUTHORIZATIONS.get(token)
    if record is None:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization",
            "The investigation authorization is not recognized by this process.",
        )
    if record.revoked:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_revoked",
            "The investigation authorization has been revoked.",
        )
    if record.epoch != _PROCESS_EPOCH or record.issuing_process_id != os.getpid():
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_process_mismatch",
            "The investigation authorization belongs to a different process epoch.",
        )
    if operation is not None:
        validate_investigation_genome_request(
            approved_scope=record.genomic_scope,
            approved_agi_id=record.agi_id,
            operation=operation,
            params=params or {},
        )
    agi_record, agi_path = _validate_live_agi_binding(
        user_id=record.user_id,
        agi_id=record.agi_id,
        agi_snapshot_id=record.agi_snapshot_id,
        expected_artifact_sha256=record.agi_artifact_sha256,
        verify_artifact=verify_artifact,
    )
    return _ValidatedAuthorization(record, agi_record, agi_path)


def _validate_live_agi_binding(
    *,
    user_id: str,
    agi_id: str,
    agi_snapshot_id: str,
    expected_artifact_sha256: str | None = None,
    verify_artifact: bool = True,
) -> tuple[JsonObject, Path]:
    context = load_context()
    if str(context.get("active_user_id") or "") != user_id:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorization user is not the current Genomi user.",
        )
    registry = load_registry()
    user = registry.get("users", {}).get(user_id)
    if not isinstance(user, dict) or agi_id not in {
        str(value) for value in user.get("agi_ids", [])
    }:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorized Active Genome Index does not belong to the current user.",
        )
    current_agi_record = registry.get("agis", {}).get(agi_id)
    if not isinstance(current_agi_record, dict):
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorized Active Genome Index is not registered.",
        )
    revision = registry.get("agi_revisions", {}).get(agi_snapshot_id)
    if (
        not isinstance(revision, dict)
        or str(revision.get("agi_id") or "") != agi_id
    ):
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorized Active Genome Index revision is not registered.",
        )
    raw_path = revision.get("agi_path")
    if not raw_path:
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The authorized Active Genome Index has no readable index artifact.",
        )
    agi_path = expand_user_path(str(raw_path)).resolve(strict=False)
    registered_artifact_sha256 = str(
        revision.get("agi_artifact_sha256") or ""
    )
    if (
        expected_artifact_sha256 is not None
        and registered_artifact_sha256 != expected_artifact_sha256
    ):
        raise InvestigationAgiAuthorizationError(
            "investigation_agi_authorization_context_mismatch",
            "The registered Active Genome Index artifact digest changed after authorization.",
        )
    if verify_artifact:
        try:
            identity = verify_immutable_agi_revision(
                agi_path,
                expected_artifact_sha256=registered_artifact_sha256,
                expected_snapshot_id=agi_snapshot_id,
            )
        except ActiveGenomeIndexArtifactIntegrityError as exc:
            raise InvestigationAgiAuthorizationError(
                "investigation_agi_authorization_context_mismatch",
                "The on-disk Active Genome Index revision failed its integrity check.",
            ) from exc
        if str(identity.get("agi_snapshot_id") or "") != agi_snapshot_id:
            raise InvestigationAgiAuthorizationError(
                "investigation_agi_authorization_context_mismatch",
                "The on-disk Active Genome Index revision does not match the authorization.",
            )
        for key in (
            "agi_build_revision",
            "source_content_sha256",
            "genome_build",
        ):
            expected = revision.get(key)
            if expected not in (None, "") and str(identity.get(key) or "") != str(
                expected
            ):
                raise InvestigationAgiAuthorizationError(
                    "investigation_agi_authorization_context_mismatch",
                    "The on-disk Active Genome Index identity does not match its registered revision.",
                )
        registered_schema = revision.get("agi_schema_version")
        if registered_schema not in (None, "") and int(
            identity.get("schema_version") or -1
        ) != int(registered_schema):
            raise InvestigationAgiAuthorizationError(
                "investigation_agi_authorization_context_mismatch",
                "The on-disk Active Genome Index schema does not match its registered revision.",
            )
    resolved_record = {
        **current_agi_record,
        **revision,
        "agi_path": str(agi_path),
    }
    return resolved_record, agi_path


def _safe_binding(record: _AuthorizationRecord) -> JsonObject:
    return {
        "authorization_kind": "investigation_bound_active_genome_index",
        "workspace_session_id": record.workspace_session_id,
        "user_id": record.user_id,
        "investigation_id": record.investigation_id,
        "patient_molecular_snapshot_id": record.patient_molecular_snapshot_id,
        "consent_receipt_id": record.consent_receipt_id,
        "agi_id": record.agi_id,
        "agi_snapshot_id": record.agi_snapshot_id,
        "purpose": record.purpose,
        "genomic_scope": dict(record.genomic_scope),
    }


def _handle_identity(handle: AgiAuthorizationHandle) -> tuple[str, str]:
    if not isinstance(handle, AgiAuthorizationHandle):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization",
            "authorization must be an AgiAuthorizationHandle issued by this process.",
        )
    with _LOCK:
        identity = _HANDLE_IDENTITIES.get(handle)
    if identity is None:
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization",
            "authorization was not issued by this process.",
        )
    return identity


def _required_text(value: object, field: str, *, maximum: int = 500) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise InvestigationAgiAuthorizationError(
            "invalid_investigation_agi_authorization",
            f"{field} must be a non-empty bounded string.",
        )
    return text


def _reset_investigation_agi_authorization_epoch_for_testing() -> None:
    """Simulate a process restart.  Test-only; old handles become unusable."""

    global _PROCESS_EPOCH
    with _LOCK:
        _AUTHORIZATIONS.clear()
        _PROCESS_EPOCH = secrets.token_urlsafe(32)


__all__ = [
    "AgiAuthorizationHandle",
    "InvestigationAgiAuthorizationError",
    "execution_context_for_investigation_authorization",
    "issue_investigation_agi_authorization",
    "revoke_investigation_agi_authorization",
    "revoke_investigation_agi_authorizations_for_investigation",
    "revoke_investigation_agi_authorizations_for_session",
    "validate_investigation_agi_authorization_binding",
]
