"""Isolated fixed-endpoint worker for the Modal prerequisite probe."""

from __future__ import annotations

import json
import os
import socket
import sys
import warnings
from collections.abc import Iterable, Mapping
from typing import Final

from .proto_transport import PROTO_MODAL_SERVER_URL


_MAX_INPUT_BYTES: Final = 8_192
_READY: Final = "ready"
_SOURCE_UNAVAILABLE: Final = "source_unavailable"


def main() -> int:
    try:
        payload = _payload()
        if os.environ.get("MODAL_SERVER_URL") != PROTO_MODAL_SERVER_URL:
            return _emit(_SOURCE_UNAVAILABLE)
        import modal
        from modal.config import config

        if config.get("server_url") != PROTO_MODAL_SERVER_URL:
            return _emit(_SOURCE_UNAVAILABLE)
        client = modal.Client.from_credentials(
            payload["token_id"], payload["token_secret"]
        )
        client.hello()
        environments = modal.Environment.objects.list(client=client)
        found = _contains_environment(environments, payload["environment"])
    except (TimeoutError, socket.timeout) as exc:
        return _emit(_failure_status(exc))
    except Exception as exc:
        return _emit(_failure_status(exc))
    return _emit(_READY if found else "not_found")


def _payload() -> dict[str, str]:
    encoded = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(encoded) > _MAX_INPUT_BYTES:
        raise ValueError("invalid worker request")
    value = json.loads(encoded.decode("utf-8"))
    if not isinstance(value, Mapping) or set(value) != {
        "environment",
        "token_id",
        "token_secret",
    }:
        raise ValueError("invalid worker request")
    resolved: dict[str, str] = {}
    for field, maximum in (
        ("environment", 200),
        ("token_id", 500),
        ("token_secret", 4_096),
    ):
        item = value.get(field)
        if not isinstance(item, str) or not item or len(item) > maximum:
            raise ValueError("invalid worker request")
        resolved[field] = item
    return resolved


def _contains_environment(environments: object, expected: str) -> bool:
    if not isinstance(environments, Iterable) or isinstance(environments, (str, bytes)):
        raise ValueError("invalid environment response")
    return any(
        getattr(environment, "name", None) == expected for environment in environments
    )


def _failure_status(exc: Exception) -> str:
    try:
        from modal import exception as modal_error
    except ImportError:
        return _SOURCE_UNAVAILABLE
    if isinstance(exc, (modal_error.AuthError, modal_error.PermissionDeniedError)):
        return "authentication_failed"
    if isinstance(exc, modal_error.NotFoundError):
        return "not_found"
    if isinstance(exc, modal_error.ResourceExhaustedError):
        return "quota_exceeded"
    if isinstance(exc, (modal_error.TimeoutError, TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, (modal_error.ConnectionError, ConnectionError, OSError)):
        return "network_error"
    if isinstance(exc, modal_error.ServiceError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            status = getattr(exc, "status", None)
        status_name = getattr(status, "name", "")
        if status_name == "DEADLINE_EXCEEDED":
            return "timeout"
        if status_name == "RESOURCE_EXHAUSTED":
            return "quota_exceeded"
        if status_name in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
            return "authentication_failed"
        return "server_error"
    if isinstance(
        exc,
        (
            modal_error.DataLossError,
            modal_error.InternalError,
            modal_error.RemoteError,
        ),
    ):
        return "server_error"
    return _SOURCE_UNAVAILABLE


def _emit(status: str) -> int:
    sys.stdout.write(json.dumps({"status": status}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
