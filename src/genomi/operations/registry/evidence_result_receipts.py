"""Opaque, process-local receipts for evidence-producing operation results.

Receipts let GenomiLab capture the exact presented result without accepting
agent-authored evidence JSON.  They intentionally live only in the current MCP
process and are bound to the current session.  Raw results are never written to
portal state, logs, environment variables, or an exportable receipt file.
"""

from __future__ import annotations

import copy
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


JsonObject = dict[str, Any]
_MAX_RECEIPTS = 512
_RECEIPT_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True, slots=True)
class EvidenceResultReceipt:
    receipt_id: str
    session_id: str
    operation: str
    result: JsonObject
    issued_at_monotonic: float


class EvidenceResultReceiptError(ValueError):
    """A receipt is unknown, expired, or outside the current session."""


class EvidenceResultReceiptIssuer:
    """Issue and resolve bounded in-memory result receipts."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._receipts: OrderedDict[str, EvidenceResultReceipt] = OrderedDict()

    def issue(
        self,
        *,
        session_id: str,
        operation: str,
        result: JsonObject,
    ) -> str:
        session = str(session_id or "").strip()
        operation_name = str(operation or "").strip()
        if not session or not operation_name or not isinstance(result, dict):
            raise EvidenceResultReceiptError(
                "evidence result receipts require a session, operation, and result"
            )
        receipt_id = f"result-receipt-{secrets.token_urlsafe(24)}"
        with self._lock:
            self._prune_locked()
            self._receipts[receipt_id] = EvidenceResultReceipt(
                receipt_id=receipt_id,
                session_id=session,
                operation=operation_name,
                result=copy.deepcopy(result),
                issued_at_monotonic=time.monotonic(),
            )
            while len(self._receipts) > _MAX_RECEIPTS:
                self._receipts.popitem(last=False)
        return receipt_id

    def resolve(self, receipt_id: object, *, session_id: str) -> JsonObject:
        identifier = str(receipt_id or "").strip()
        session = str(session_id or "").strip()
        if not identifier or not session:
            raise EvidenceResultReceiptError(
                "result_receipt_id and the current session are required"
            )
        with self._lock:
            self._prune_locked()
            receipt = self._receipts.get(identifier)
            if receipt is None:
                raise EvidenceResultReceiptError(
                    "the evidence result receipt is unknown or expired"
                )
            if receipt.session_id != session:
                raise EvidenceResultReceiptError(
                    "the evidence result receipt belongs to a different session"
                )
            return {
                "result_receipt_id": receipt.receipt_id,
                "operation": receipt.operation,
                "result": copy.deepcopy(receipt.result),
            }

    def clear(self) -> None:
        """Clear process-local receipts for deterministic tests."""

        with self._lock:
            self._receipts.clear()

    def _prune_locked(self) -> None:
        cutoff = time.monotonic() - _RECEIPT_TTL_SECONDS
        expired = [
            receipt_id
            for receipt_id, receipt in self._receipts.items()
            if receipt.issued_at_monotonic < cutoff
        ]
        for receipt_id in expired:
            self._receipts.pop(receipt_id, None)


EVIDENCE_RESULT_RECEIPTS = EvidenceResultReceiptIssuer()


__all__ = [
    "EVIDENCE_RESULT_RECEIPTS",
    "EvidenceResultReceiptError",
    "EvidenceResultReceiptIssuer",
]
