from __future__ import annotations

from collections.abc import Callable
from typing import Any

JsonObject = dict[str, Any]
OperationHandler = Callable[[JsonObject], JsonObject]


class OperationError(ValueError):
    """A typed operation failure.

    ``observations``, ``next_actions``, and ``guidance`` carry the
    case-specific facts a host agent needs to correct the call, so the failure
    reads as envelope state rather than as prose the host has to parse.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        observations: JsonObject | None = None,
        next_actions: list[JsonObject] | None = None,
        guidance: list[str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.observations = dict(observations or {})
        self.next_actions = [dict(action) for action in next_actions or []]
        self.guidance = list(guidance or [])

    def to_json(self, *, operation: str | None = None) -> JsonObject:
        payload: JsonObject = {"error": self.code, "message": self.message}
        try:
            from ...evidence import envelope as _env

            status = str(self.code or "error").lower()
            payload["status"] = status
            result: JsonObject = {
                "status": status,
                "error": {"code": self.code, "message": self.message},
                "message": self.message,
            }
            if self.observations:
                result["observations"] = dict(self.observations)
            if self.next_actions:
                result["next_actions"] = [dict(action) for action in self.next_actions]
            if self.guidance:
                result["guidance"] = list(self.guidance)
            payload["evidence_envelope"] = _env.derive_default_envelope(
                operation or "operation_error", result
            )
        except Exception:
            # Error rendering must never obscure the original operation error.
            pass
        return payload
