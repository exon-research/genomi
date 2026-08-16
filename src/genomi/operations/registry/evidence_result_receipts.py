"""Private cross-process receipts for evidence-producing operation results.

Receipts let GenomiLab capture the exact presented result without accepting
agent-authored evidence JSON. Native specialists and the main host run separate
Genomi MCP processes, so receipts are short-lived plaintext files under the
private Genomi data root rather than process memory. The opaque receipt token
selects one exact payload, which is bound to the current session, integrity
checked, and removed only after its durable consumer succeeds.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # POSIX is the supported production boundary; tests retain a thread lock.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

from ...runtime.paths import genomi_data_root
from ...runtime.private_storage import (
    PRIVATE_FILE_MODE,
    atomic_write_private_json,
    ensure_private_directory,
    read_private_json,
    refuse_symlink,
)


JsonObject = dict[str, Any]
_MAX_RECEIPTS = 512
_RECEIPT_TTL_SECONDS = 6 * 60 * 60
_RECEIPT_STORE_NAME = "runtime/evidence-result-receipts"
_RECEIPT_VERSION = 1
_RECEIPT_ID_PATTERN = re.compile(r"result-receipt-[A-Za-z0-9_-]{24,128}\Z")
_RECEIPT_KEYS = frozenset(
    {
        "version",
        "receipt_id",
        "session_sha256",
        "operation",
        "params",
        "result",
        "issued_at",
        "payload_sha256",
    }
)


class EvidenceResultReceiptError(ValueError):
    """A receipt is unknown, expired, invalid, or outside the current session."""


class EvidenceResultReceiptIssuer:
    """Issue and atomically redeem bounded, private cross-process receipts."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def issue(
        self,
        *,
        session_id: str,
        operation: str,
        params: JsonObject,
        result: JsonObject,
    ) -> str:
        session = str(session_id or "").strip()
        operation_name = str(operation or "").strip()
        if (
            not session
            or not operation_name
            or not isinstance(params, dict)
            or not isinstance(result, dict)
        ):
            raise EvidenceResultReceiptError(
                "evidence result receipts require a session, operation, and result"
            )

        receipt_id = f"result-receipt-{secrets.token_urlsafe(24)}"
        payload: JsonObject = {
            "version": _RECEIPT_VERSION,
            "receipt_id": receipt_id,
            "session_sha256": _session_digest(session),
            "operation": operation_name,
            "params": copy.deepcopy(params),
            "result": copy.deepcopy(result),
            "issued_at": time.time(),
        }
        payload["payload_sha256"] = _payload_digest(payload)
        with self._store_lock():
            self._prune_locked()
            atomic_write_private_json(
                self._receipt_path(receipt_id),
                payload,
                private_root=genomi_data_root(),
            )
            self._enforce_bound_locked()
        return receipt_id

    def resolve(self, receipt_id: object, *, session_id: str) -> JsonObject:
        identifier, session = self._validated_lookup(receipt_id, session_id)
        with self._store_lock():
            receipt = self._load_locked(identifier)
            self._validate_session(receipt, session)
            return _presented_receipt(receipt)

    def redeem(
        self,
        receipt_id: object,
        *,
        session_id: str,
        consumer: Callable[[JsonObject], JsonObject],
    ) -> JsonObject:
        """Consume one exact receipt only after its durable consumer succeeds."""

        if not callable(consumer):
            raise TypeError("consumer must be callable")
        identifier, session = self._validated_lookup(receipt_id, session_id)
        with self._store_lock():
            receipt = self._load_locked(identifier)
            self._validate_session(receipt, session)
            result = consumer(_presented_receipt(receipt))
            if not isinstance(result, dict):
                raise EvidenceResultReceiptError(
                    "the evidence result receipt consumer returned an invalid result"
                )
            self._receipt_path(identifier).unlink()
            return result

    def clear(self) -> None:
        """Clear receipts under the current Genomi data root for tests."""

        with self._store_lock():
            for path in self._receipt_files_locked():
                path.unlink(missing_ok=True)

    def discard(self, receipt_id: object, *, session_id: str) -> bool:
        """Discard a receipt after a stronger host receipt replaces it."""

        try:
            identifier, session = self._validated_lookup(receipt_id, session_id)
        except EvidenceResultReceiptError:
            return False
        with self._store_lock():
            try:
                receipt = self._load_locked(identifier)
            except EvidenceResultReceiptError:
                return False
            if not hmac.compare_digest(
                str(receipt["session_sha256"]), _session_digest(session)
            ):
                return False
            self._receipt_path(identifier).unlink()
            return True

    def _validated_lookup(
        self, receipt_id: object, session_id: str
    ) -> tuple[str, str]:
        identifier = str(receipt_id or "").strip()
        session = str(session_id or "").strip()
        if not identifier or not session:
            raise EvidenceResultReceiptError(
                "result_receipt_id and the current session are required"
            )
        if _RECEIPT_ID_PATTERN.fullmatch(identifier) is None:
            raise EvidenceResultReceiptError(
                "the evidence result receipt is unknown or expired"
            )
        return identifier, session

    def _validate_session(self, receipt: JsonObject, session: str) -> None:
        if not hmac.compare_digest(
            str(receipt["session_sha256"]), _session_digest(session)
        ):
            raise EvidenceResultReceiptError(
                "the evidence result receipt belongs to a different session"
            )

    def _load_locked(self, receipt_id: str) -> JsonObject:
        path = self._receipt_path(receipt_id)
        try:
            metadata = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE
            ):
                raise EvidenceResultReceiptError(
                    "the evidence result receipt is not private runtime state"
                )
            payload = read_private_json(path)
        except FileNotFoundError as exc:
            raise EvidenceResultReceiptError(
                "the evidence result receipt is unknown or expired"
            ) from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceResultReceiptError(
                "the evidence result receipt is invalid or tampered"
            ) from exc
        if not isinstance(payload, dict) or frozenset(payload) != _RECEIPT_KEYS:
            raise EvidenceResultReceiptError(
                "the evidence result receipt is invalid or tampered"
            )
        expected_digest = payload.get("payload_sha256")
        if not isinstance(expected_digest, str) or not hmac.compare_digest(
            expected_digest, _payload_digest(payload)
        ):
            raise EvidenceResultReceiptError(
                "the evidence result receipt is invalid or tampered"
            )
        if (
            payload.get("version") != _RECEIPT_VERSION
            or payload.get("receipt_id") != receipt_id
            or not isinstance(payload.get("session_sha256"), str)
            or not isinstance(payload.get("operation"), str)
            or not isinstance(payload.get("params"), dict)
            or not isinstance(payload.get("result"), dict)
            or not isinstance(payload.get("issued_at"), (int, float))
        ):
            raise EvidenceResultReceiptError(
                "the evidence result receipt is invalid or tampered"
            )
        age = time.time() - float(payload["issued_at"])
        if age < -60 or age > _RECEIPT_TTL_SECONDS:
            path.unlink(missing_ok=True)
            raise EvidenceResultReceiptError(
                "the evidence result receipt is unknown or expired"
            )
        return payload

    def _prune_locked(self) -> None:
        for path in self._receipt_files_locked():
            receipt_id = path.name.removesuffix(".json")
            try:
                self._load_locked(receipt_id)
            except EvidenceResultReceiptError as exc:
                if "unknown or expired" in str(exc):
                    path.unlink(missing_ok=True)

    def _enforce_bound_locked(self) -> None:
        receipts = self._receipt_files_locked()
        excess = len(receipts) - _MAX_RECEIPTS
        if excess <= 0:
            return
        oldest = sorted(receipts, key=lambda path: path.stat().st_mtime_ns)[:excess]
        for path in oldest:
            path.unlink(missing_ok=True)

    def _receipt_files_locked(self) -> list[Path]:
        root = self._store_root()
        refuse_symlink(root)
        return [
            path
            for path in root.glob("result-receipt-*.json")
            if not path.is_symlink() and path.is_file()
        ]

    def _receipt_path(self, receipt_id: str) -> Path:
        return self._store_root() / f"{receipt_id}.json"

    def _store_root(self) -> Path:
        root = genomi_data_root() / _RECEIPT_STORE_NAME
        return ensure_private_directory(root, private_root=genomi_data_root())

    @contextmanager
    def _store_lock(self) -> Iterator[None]:
        with self._lock:
            root = self._store_root()
            lock_path = root / ".store.lock"
            refuse_symlink(lock_path)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(lock_path, flags, PRIVATE_FILE_MODE)
            try:
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)


def _session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _payload_digest(payload: JsonObject) -> str:
    protected = {key: value for key, value in payload.items() if key != "payload_sha256"}
    encoded = json.dumps(
        protected,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _presented_receipt(receipt: JsonObject) -> JsonObject:
    return {
        "result_receipt_id": receipt["receipt_id"],
        "operation": receipt["operation"],
        "params": copy.deepcopy(receipt["params"]),
        "result": copy.deepcopy(receipt["result"]),
    }


EVIDENCE_RESULT_RECEIPTS = EvidenceResultReceiptIssuer()


__all__ = [
    "EVIDENCE_RESULT_RECEIPTS",
    "EvidenceResultReceiptError",
    "EvidenceResultReceiptIssuer",
]
