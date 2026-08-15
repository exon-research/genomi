"""Explicit host-owned execution context for internal operation calls.

The public MCP/CLI contract remains only ``(operation, params)``.  An embedded
host may additionally supply this typed, process-local context when it has
already established a narrower authority than the ordinary chat-session
grant.  The dispatcher transports the context; it does not know which product
issued it or why.
"""

from __future__ import annotations

import contextvars
import copy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ...active_genome_index.active_genome_index import ActiveGenomeIndexReader


JsonObject = dict[str, Any]
RevalidateExecution = Callable[[], Mapping[str, object]]
IssueEvidenceResultReceipt = Callable[..., str]


class OperationExecutionContextError(RuntimeError):
    """Structured rejection of an internal execution context."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgiReadLease:
    """One verified AGI reader bound to a declared operation call."""

    reader: ActiveGenomeIndexReader
    agi_record: Mapping[str, object]
    selection: str = "execution_context"

    def __post_init__(self) -> None:
        record = dict(self.agi_record)
        agi_id = str(record.get("agi_id") or "")
        if not agi_id:
            raise ValueError("AgiReadLease requires an agi_id")
        record_path = str(record.get("agi_path") or "")
        if not record_path:
            raise ValueError("AgiReadLease requires an agi_path")
        if self.reader.agi_path.resolve(strict=False) != Path(
            record_path
        ).expanduser().resolve(strict=False):
            raise ValueError("AgiReadLease reader does not match its AGI record")
        record_digest = str(record.get("agi_artifact_sha256") or "")
        if (
            not record_digest
            or self.reader.verified_artifact_sha256 != record_digest
        ):
            raise ValueError("AgiReadLease requires a digest-verified AGI reader")
        record_snapshot = str(record.get("agi_snapshot_id") or "")
        if (
            not record_snapshot
            or self.reader.verified_snapshot_id != record_snapshot
        ):
            raise ValueError("AgiReadLease reader does not match its AGI snapshot")
        object.__setattr__(
            self,
            "agi_record",
            MappingProxyType(copy.deepcopy(record)),
        )


@dataclass(frozen=True)
class OperationExecutionContext:
    """Exact call scope plus optional host-provided resources.

    ``revalidate`` is called immediately before execution and again before the
    result is disclosed.  It returns safe result annotations (often an audit
    binding) and may raise :class:`OperationExecutionContextError` if the host
    authority was revoked or its live binding changed.
    """

    operation: str
    params: Mapping[str, object]
    agi_read_lease: AgiReadLease | None = None
    revalidate: RevalidateExecution | None = field(default=None, repr=False)
    evidence_result_receipt_issuer: IssueEvidenceResultReceipt | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        operation = str(self.operation or "").strip()
        if not operation:
            raise ValueError("OperationExecutionContext requires an operation")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self,
            "params",
            MappingProxyType(copy.deepcopy(dict(self.params))),
        )

    def validate_call(
        self, operation: str, params: Mapping[str, object]
    ) -> JsonObject:
        if operation != self.operation or dict(params) != dict(self.params):
            raise OperationExecutionContextError(
                "operation_execution_context_scope_mismatch",
                "The internal execution context does not match this exact operation call.",
            )
        if self.revalidate is None:
            return {}
        return dict(self.revalidate())

    def issue_evidence_result_receipt(
        self,
        *,
        operation: str,
        params: Mapping[str, object],
        presented_result: Mapping[str, object],
    ) -> str | None:
        """Ask the embedding host to durably bind the exact presented result."""

        if self.evidence_result_receipt_issuer is None:
            return None
        try:
            receipt_id = self.evidence_result_receipt_issuer(
                operation=operation,
                params=copy.deepcopy(dict(params)),
                presented_result=copy.deepcopy(dict(presented_result)),
            )
        except OperationExecutionContextError:
            raise
        except (KeyError, ValueError) as exc:
            raise OperationExecutionContextError(
                "evidence_result_receipt_rejected",
                "The host rejected the evidence-result receipt binding.",
            ) from exc
        identifier = str(receipt_id or "").strip()
        if not identifier:
            raise OperationExecutionContextError(
                "invalid_evidence_result_receipt",
                "The host evidence-result receipt issuer returned no receipt identifier.",
            )
        return identifier


_CURRENT_EXECUTION_CONTEXT: contextvars.ContextVar[
    OperationExecutionContext | None
] = contextvars.ContextVar("genomi_operation_execution_context", default=None)


def activate_execution_context(
    execution_context: OperationExecutionContext | None,
) -> contextvars.Token[OperationExecutionContext | None]:
    """Bind (or deliberately clear) context for one dispatcher invocation."""

    return _CURRENT_EXECUTION_CONTEXT.set(execution_context)


def reset_execution_context(
    token: contextvars.Token[OperationExecutionContext | None],
) -> None:
    _CURRENT_EXECUTION_CONTEXT.reset(token)


def current_execution_context() -> OperationExecutionContext | None:
    return _CURRENT_EXECUTION_CONTEXT.get()


__all__ = [
    "AgiReadLease",
    "OperationExecutionContext",
    "OperationExecutionContextError",
    "activate_execution_context",
    "current_execution_context",
    "reset_execution_context",
]
