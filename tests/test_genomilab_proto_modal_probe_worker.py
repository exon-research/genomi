from __future__ import annotations

import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from genomi.lab import proto_modal_probe_worker as worker
from genomi.lab.proto_transport import PROTO_MODAL_SERVER_URL


_PAYLOAD = {
    "token_id": "explicit-modal-id",
    "token_secret": "explicit-modal-secret",
    "environment": "genomilab-research",
}


class _ModalError(Exception):
    pass


class _AuthError(_ModalError):
    pass


class _PermissionDeniedError(_ModalError):
    pass


class _NotFoundError(_ModalError):
    pass


class _ResourceExhaustedError(_ModalError):
    pass


class _ModalTimeoutError(_ModalError):
    pass


class _ModalConnectionError(_ModalError):
    pass


class _ServiceError(_ModalError):
    def __init__(self, status_name: str) -> None:
        super().__init__(status_name)
        self.status = SimpleNamespace(name=status_name)


class _DataLossError(_ModalError):
    pass


class _InternalError(_ModalError):
    pass


class _RemoteError(_ModalError):
    pass


_MODAL_ERRORS = SimpleNamespace(
    AuthError=_AuthError,
    PermissionDeniedError=_PermissionDeniedError,
    NotFoundError=_NotFoundError,
    ResourceExhaustedError=_ResourceExhaustedError,
    TimeoutError=_ModalTimeoutError,
    ConnectionError=_ModalConnectionError,
    ServiceError=_ServiceError,
    DataLossError=_DataLossError,
    InternalError=_InternalError,
    RemoteError=_RemoteError,
)


class _FakeClient:
    def __init__(self, calls: list[object], hello_error: Exception | None) -> None:
        self._calls = calls
        self._hello_error = hello_error

    def hello(self) -> None:
        self._calls.append("hello")
        if self._hello_error is not None:
            raise self._hello_error


def _fake_modal_modules(
    *,
    config_url: str = PROTO_MODAL_SERVER_URL,
    environments: object = (),
    credential_error: Exception | None = None,
    hello_error: Exception | None = None,
    list_error: Exception | None = None,
) -> tuple[dict[str, types.ModuleType], list[object]]:
    calls: list[object] = []
    client = _FakeClient(calls, hello_error)

    class Client:
        @classmethod
        def from_credentials(cls, token_id: str, token_secret: str) -> _FakeClient:
            calls.append(("credentials", token_id, token_secret))
            if credential_error is not None:
                raise credential_error
            return client

    def list_environments(*, client: object | None = None) -> object:
        calls.append(("list", client))
        if list_error is not None:
            raise list_error
        return environments

    modal = types.ModuleType("modal")
    modal.Client = Client
    modal.Environment = SimpleNamespace(objects=SimpleNamespace(list=list_environments))
    modal.exception = _MODAL_ERRORS
    modal_config = types.ModuleType("modal.config")
    modal_config.config = SimpleNamespace(
        get=lambda field: config_url if field == "server_url" else None
    )
    modal.config = modal_config
    return {"modal": modal, "modal.config": modal_config}, calls


class ProtoModalProbeWorkerTests(unittest.TestCase):
    def _run(
        self,
        modules: dict[str, types.ModuleType],
        *,
        server_url: str = PROTO_MODAL_SERVER_URL,
    ) -> str:
        output = io.StringIO()
        with (
            patch.object(worker, "_payload", return_value=dict(_PAYLOAD)),
            patch.dict(os.environ, {"MODAL_SERVER_URL": server_url}, clear=True),
            patch.dict(sys.modules, modules),
            redirect_stdout(output),
        ):
            self.assertEqual(worker.main(), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(set(payload), {"status"})
        return payload["status"]

    def test_rejects_environment_endpoint_drift_before_credentials(self) -> None:
        modules, calls = _fake_modal_modules()

        status = self._run(modules, server_url="https://attacker.invalid")

        self.assertEqual(status, "source_unavailable")
        self.assertEqual(calls, [])

    def test_rejects_sdk_config_endpoint_drift_before_credentials(self) -> None:
        modules, calls = _fake_modal_modules(config_url="https://attacker.invalid")

        status = self._run(modules)

        self.assertEqual(status, "source_unavailable")
        self.assertEqual(calls, [])

    def test_binds_explicit_client_and_finds_only_the_exact_environment(self) -> None:
        modules, calls = _fake_modal_modules(
            environments=[SimpleNamespace(name="genomilab-research")]
        )

        status = self._run(modules)

        self.assertEqual(status, "ready")
        self.assertEqual(
            calls[0],
            ("credentials", "explicit-modal-id", "explicit-modal-secret"),
        )
        self.assertEqual(calls[1], "hello")
        self.assertEqual(calls[2][0], "list")
        self.assertIsInstance(calls[2][1], _FakeClient)

    def test_empty_environment_list_is_not_found(self) -> None:
        modules, calls = _fake_modal_modules(environments=[])

        status = self._run(modules)

        self.assertEqual(status, "not_found")
        self.assertEqual(calls[-1][0], "list")

    def test_emits_typed_modal_failures_without_details(self) -> None:
        cases = (
            (
                {"credential_error": _AuthError("secret auth detail")},
                "authentication_failed",
            ),
            (
                {"hello_error": _ResourceExhaustedError("secret quota detail")},
                "quota_exceeded",
            ),
            ({"list_error": _ModalTimeoutError("secret timeout detail")}, "timeout"),
            (
                {"list_error": _ModalConnectionError("secret network detail")},
                "network_error",
            ),
            ({"list_error": _ServiceError("DEADLINE_EXCEEDED")}, "timeout"),
            ({"list_error": _InternalError("secret server detail")}, "server_error"),
        )
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                modules, _calls = _fake_modal_modules(**kwargs)
                status = self._run(modules)
                self.assertEqual(status, expected)
                self.assertNotIn("secret", status)


if __name__ == "__main__":
    unittest.main()
