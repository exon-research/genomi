from __future__ import annotations

from collections.abc import Callable
from typing import Any

JsonObject = dict[str, Any]
OperationHandler = Callable[[JsonObject], JsonObject]


class OperationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_json(self, *, operation: str | None = None) -> JsonObject:
        payload: JsonObject = {"error": self.code, "message": self.message}
        try:
            from ...evidence import envelope as _env

            status = str(self.code or "error").lower()
            payload["status"] = status
            payload["evidence_envelope"] = _env.derive_default_envelope(
                operation or "operation_error",
                {
                    "status": status,
                    "ok": False,
                    "error": {"code": self.code, "message": self.message},
                    "message": self.message,
                },
            )
        except Exception:
            # Error rendering must never obscure the original operation error.
            pass
        return payload
