"""Patient-safe application errors shared by portal modules."""

from __future__ import annotations

from .models import JsonObject


class LabError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def to_json(self) -> JsonObject:
        return {"error": {"code": self.code, "message": self.message}}


def patient_safe_operation_message(code: str) -> str:
    messages = {
        "approval_required": "Explicit genome access approval is required for this session.",
        "missing_context": "The selected profile does not have a usable genome context.",
        "active_genome_index_incomplete": (
            "The genome index is still incomplete; finish intake before investigating it."
        ),
        "active_genome_index_needs_reparse": (
            "This genome index must be rebuilt with the current Genomi version."
        ),
        "active_genome_index_schema_too_new": (
            "This genome index was created by a newer Genomi version."
        ),
    }
    return messages.get(
        code, "The requested local evidence check could not be completed."
    )
