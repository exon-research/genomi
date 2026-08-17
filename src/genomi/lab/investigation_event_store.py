"""Host-neutral, ordered investigation domain-event persistence."""

from __future__ import annotations

import math
import uuid
from typing import Any, ContextManager, Protocol

from .models import (
    JsonObject,
    compact_json,
    required_text,
    row_dict,
    utc_now,
    validate_private_payload,
)


INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES = 64 * 1024
_INVESTIGATION_EVENT_PAYLOAD_MAX_DEPTH = 32


class _StoreContract(Protocol):
    def _connect(self) -> ContextManager[Any]: ...


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > _INVESTIGATION_EVENT_PAYLOAD_MAX_DEPTH:
        raise ValueError("investigation event payload is nested too deeply")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("investigation event payload must contain finite numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("investigation event payload keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("investigation event payload must contain only JSON values")


def _encode_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("investigation event payload must be an object")
    validate_private_payload(payload)
    _validate_json_value(payload)
    try:
        encoded = compact_json(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("investigation event payload must be valid JSON") from exc
    if len(encoded.encode("utf-8")) > INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES:
        raise ValueError("investigation event payload is too large")
    return encoded


class InvestigationEventStoreMixin:
    """Append and replay safe domain events for portal monitoring."""

    def _append_investigation_event(
        self,
        connection: Any,
        investigation_id: str,
        *,
        event_type: object,
        payload: JsonObject,
    ) -> JsonObject:
        """Insert one event through an already-owned store connection."""

        event_type_value = required_text(event_type, "event_type", 100)
        encoded_payload = _encode_payload(payload)
        event_id = f"investigation-event-{uuid.uuid4().hex}"
        created_at = utc_now()
        investigation = connection.execute(
            "SELECT investigation_id FROM investigations WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        if investigation is None:
            raise KeyError(investigation_id)
        next_row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            "FROM investigation_events WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        sequence = int(next_row["next_sequence"])
        connection.execute(
            """
            INSERT INTO investigation_events(
                event_id, investigation_id, sequence, event_type,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                investigation_id,
                sequence,
                event_type_value,
                encoded_payload,
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM investigation_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return row_dict(row)

    def append_investigation_event(
        self: _StoreContract,
        investigation_id: str,
        *,
        event_type: object,
        payload: JsonObject,
    ) -> JsonObject:
        with self._connect() as connection:
            return self._append_investigation_event(
                connection,
                investigation_id,
                event_type=event_type,
                payload=payload,
            )

    def replay_investigation_events(
        self: _StoreContract,
        investigation_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[JsonObject]:
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int):
            raise ValueError("after_sequence must be an integer")
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        with self._connect() as connection:
            investigation = connection.execute(
                "SELECT investigation_id FROM investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            if investigation is None:
                raise KeyError(investigation_id)
            rows = connection.execute(
                "SELECT * FROM investigation_events "
                "WHERE investigation_id = ? AND sequence > ? ORDER BY sequence",
                (investigation_id, after_sequence),
            ).fetchall()
        return [row_dict(row) for row in rows]


__all__ = [
    "INVESTIGATION_EVENT_PAYLOAD_MAX_BYTES",
    "InvestigationEventStoreMixin",
]
