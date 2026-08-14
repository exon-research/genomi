"""Durable redacted command results for local provider setup."""

from __future__ import annotations

import uuid
from typing import Protocol

from .models import JsonObject, compact_json, required_text, row_dict, utc_now


_PROVIDER_ORDER = ("paperclip", "biohub-esm", "proto")
_PROVIDERS = frozenset(_PROVIDER_ORDER)
_ACTIONS = frozenset({"connect", "verify", "disconnect"})
_RESULT_STATUSES = frozenset({"requested", "failed", "reconciliation_required"})
_EVENT_TYPES = {action: f"provider_connection_{action}_recorded" for action in _ACTIONS}
_REQUEST_EVENT_TYPES = {
    action: f"provider_connection_{action}_requested" for action in _ACTIONS
}
_RESULT_FIELDS = frozenset(
    {
        "provider",
        "status",
        "error_code",
        "connection_state",
        "credential_state",
        "execution_location",
        "policy_state",
        "available_operations",
        "last_verified_at",
        "use_scope",
        "verification_kind",
        "verification_may_consume_credits",
        "verification_available",
    }
)


class _StoreContract(Protocol):
    def _connect(self): ...


class ProviderConnectionStoreMixin:
    """Persist only the already-redacted setup result, never credentials."""

    def begin_provider_connection_command(
        self: _StoreContract,
        *,
        workspace_session_id: object,
        provider: object,
        action: object,
    ) -> str:
        """Persist a write-ahead, redacted intent before touching the keyring."""

        session_id = required_text(workspace_session_id, "workspace_session_id", 300)
        provider_id = required_text(provider, "provider", 100)
        action_id = required_text(action, "action", 100)
        if provider_id not in _PROVIDERS or action_id not in _ACTIONS:
            raise ValueError("provider connection command is not allowlisted")
        command_id = f"provider-command-{uuid.uuid4().hex}"
        event_id = f"provider-event-{uuid.uuid4().hex}"
        created_at = utc_now()
        requested = compact_json({"provider": provider_id, "status": "requested"})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_connection_commands(
                    command_id, workspace_session_id, provider, action,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    session_id,
                    provider_id,
                    action_id,
                    requested,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO provider_connection_events(
                    event_id, command_id, workspace_session_id, provider,
                    event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    command_id,
                    session_id,
                    provider_id,
                    _REQUEST_EVENT_TYPES[action_id],
                    requested,
                    created_at,
                ),
            )
        return command_id

    def finalize_provider_connection_command(
        self: _StoreContract,
        *,
        command_id: object,
        workspace_session_id: object,
        provider: object,
        action: object,
        result: object,
    ) -> None:
        """Atomically replace one write-ahead intent with its redacted outcome."""

        resolved_command_id = required_text(command_id, "command_id", 300)
        session_id = required_text(workspace_session_id, "workspace_session_id", 300)
        provider_id = required_text(provider, "provider", 100)
        action_id = required_text(action, "action", 100)
        if provider_id not in _PROVIDERS or action_id not in _ACTIONS:
            raise ValueError("provider connection command is not allowlisted")
        if not isinstance(result, dict) or set(result) - _RESULT_FIELDS:
            raise ValueError("provider connection result is not redacted")
        if "status" in result and result["status"] not in _RESULT_STATUSES:
            raise ValueError("provider connection result status is invalid")
        if result.get("provider") != provider_id:
            raise ValueError("provider connection result changed provider")
        encoded = compact_json(result)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("provider connection result is too large")
        with self._connect() as connection:
            command = connection.execute(
                """
                SELECT command_id FROM provider_connection_commands
                WHERE command_id = ? AND workspace_session_id = ?
                  AND provider = ? AND action = ?
                """,
                (resolved_command_id, session_id, provider_id, action_id),
            ).fetchone()
            if command is None:
                raise ValueError("provider connection command intent was not found")
            connection.execute(
                """
                UPDATE provider_connection_commands
                SET result_json = ? WHERE command_id = ?
                """,
                (encoded, resolved_command_id),
            )
            connection.execute(
                """
                UPDATE provider_connection_events
                SET event_type = ?, payload_json = ? WHERE command_id = ?
                """,
                (_EVENT_TYPES[action_id], encoded, resolved_command_id),
            )

    def record_provider_connection_command(
        self: _StoreContract,
        *,
        workspace_session_id: object,
        provider: object,
        action: object,
        result: object,
    ) -> str:
        session_id = required_text(workspace_session_id, "workspace_session_id", 300)
        provider_id = required_text(provider, "provider", 100)
        action_id = required_text(action, "action", 100)
        if provider_id not in _PROVIDERS or action_id not in _ACTIONS:
            raise ValueError("provider connection command is not allowlisted")
        if not isinstance(result, dict) or set(result) - _RESULT_FIELDS:
            raise ValueError("provider connection result is not redacted")
        if "status" in result and result["status"] not in _RESULT_STATUSES:
            raise ValueError("provider connection result status is invalid")
        if result.get("provider") != provider_id:
            raise ValueError("provider connection result changed provider")
        encoded = compact_json(result)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("provider connection result is too large")
        command_id = f"provider-command-{uuid.uuid4().hex}"
        event_id = f"provider-event-{uuid.uuid4().hex}"
        created_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_connection_commands(
                    command_id, workspace_session_id, provider, action,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    session_id,
                    provider_id,
                    action_id,
                    encoded,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO provider_connection_events(
                    event_id, command_id, workspace_session_id, provider,
                    event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    command_id,
                    session_id,
                    provider_id,
                    _EVENT_TYPES[action_id],
                    encoded,
                    created_at,
                ),
            )
        return command_id

    def list_provider_connection_commands(
        self: _StoreContract, workspace_session_id: object
    ) -> list[JsonObject]:
        session_id = required_text(workspace_session_id, "workspace_session_id", 300)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM provider_connection_commands
                WHERE workspace_session_id = ?
                ORDER BY created_at, command_id
                """,
                (session_id,),
            ).fetchall()
        return [row_dict(row) for row in rows]

    def list_provider_connection_events(
        self: _StoreContract, workspace_session_id: object
    ) -> list[JsonObject]:
        session_id = required_text(workspace_session_id, "workspace_session_id", 300)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM provider_connection_events
                WHERE workspace_session_id = ?
                ORDER BY created_at, event_id
                """,
                (session_id,),
            ).fetchall()
        return [row_dict(row) for row in rows]

    def provider_connection_reconciliation_providers(
        self: _StoreContract,
    ) -> tuple[str, ...]:
        """Return providers whose latest command has no definitive outcome."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT provider, result_json FROM provider_connection_commands
                ORDER BY created_at DESC, rowid DESC
                """,
            ).fetchall()
        latest: dict[str, JsonObject] = {}
        for row in rows:
            decoded = row_dict(row)
            provider = str(decoded.get("provider") or "")
            if provider and provider not in latest:
                result = decoded.get("result")
                latest[provider] = result if isinstance(result, dict) else {}
        return tuple(
            provider
            for provider in _PROVIDER_ORDER
            if latest.get(provider, {}).get("status")
            in {"requested", "reconciliation_required"}
        )


__all__ = ["ProviderConnectionStoreMixin"]
