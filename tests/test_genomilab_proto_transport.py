from __future__ import annotations

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from genomi.lab.evidence_types import EvidenceStatus, ProviderTransportError
from genomi.lab.proto_transport import (
    PROTO_MODAL_PROBE_TIMEOUT_SECONDS,
    PROTO_MODAL_PROBE_WORKER,
    PROTO_MODAL_SERVER_URL,
    ModalProtoTransport,
)


class ModalProtoTransportTests(unittest.TestCase):
    def test_rejects_invalid_credentials_without_worker_call(self) -> None:
        calls: list[object] = []
        transport = ModalProtoTransport(
            process_runner=lambda *_args, **_kwargs: calls.append("started")
        )

        with self.assertRaises(ProviderTransportError) as raised:
            transport.probe("", "modal-secret", "genomilab-research")

        self.assertEqual(raised.exception.status, EvidenceStatus.AUTHENTICATION_FAILED)
        self.assertEqual(calls, [])
        self.assertNotIn("modal-secret", str(raised.exception))

    def test_requires_an_absolute_python_runtime(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            ModalProtoTransport(python_executable="python")

    def test_uses_an_isolated_fixed_endpoint_worker(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []

        def run(
            command: object, **kwargs: object
        ) -> subprocess.CompletedProcess[bytes]:
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command, 0, stdout=b'{"status":"ready"}', stderr=b""
            )

        transport = ModalProtoTransport(
            process_runner=run,
            python_executable="/trusted/python",
        )
        ambient = {
            "MODAL_SERVER_URL": "https://attacker.invalid",
            "MODAL_TOKEN_SECRET": "ambient-secret",
            "HTTPS_PROXY": "https://attacker.invalid",
            "SSL_CERT_FILE": "/attacker/ca.pem",
        }
        with patch.dict(os.environ, ambient):
            transport.probe("modal-id", "modal-secret", "genomilab-research")

        self.assertTrue(transport.verification_available)
        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(
            command,
            ["/trusted/python", "-I", "-m", PROTO_MODAL_PROBE_WORKER],
        )
        self.assertEqual(
            json.loads(kwargs["input"]),
            {
                "environment": "genomilab-research",
                "token_id": "modal-id",
                "token_secret": "modal-secret",
            },
        )
        worker_environment = kwargs["env"]
        self.assertEqual(worker_environment["MODAL_SERVER_URL"], PROTO_MODAL_SERVER_URL)
        self.assertNotIn("MODAL_TOKEN_SECRET", worker_environment)
        self.assertNotIn("HTTPS_PROXY", worker_environment)
        self.assertNotIn("SSL_CERT_FILE", worker_environment)
        self.assertNotIn("PATH", worker_environment)
        self.assertEqual(kwargs["timeout"], PROTO_MODAL_PROBE_TIMEOUT_SECONDS)
        self.assertTrue(kwargs["close_fds"])
        self.assertFalse(kwargs["check"])
        self.assertFalse(os.path.exists(worker_environment["MODAL_CONFIG_PATH"]))

    def test_refuses_a_missing_environment(self) -> None:
        def run(
            command: object, **_kwargs: object
        ) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                command, 0, stdout=b'{"status":"not_found"}', stderr=b""
            )

        with self.assertRaises(ProviderTransportError) as raised:
            ModalProtoTransport(process_runner=run).probe(
                "modal-id", "modal-secret", "missing-environment"
            )

        self.assertEqual(raised.exception.status, EvidenceStatus.NOT_FOUND)

    def test_has_a_hard_total_timeout(self) -> None:
        def run(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(PROTO_MODAL_PROBE_WORKER, 1)

        with self.assertRaises(ProviderTransportError) as raised:
            ModalProtoTransport(process_runner=run, timeout_seconds=1).probe(
                "modal-id", "modal-secret", "genomilab-research"
            )

        self.assertEqual(raised.exception.status, EvidenceStatus.TIMEOUT)

    def test_rejects_untyped_worker_output(self) -> None:
        responses = (
            subprocess.CompletedProcess([], 1, stdout=b'{"status":"ready"}'),
            subprocess.CompletedProcess([], 0, stdout=b"not-json"),
            subprocess.CompletedProcess(
                [], 0, stdout=b'{"status":"ready","detail":"unexpected"}'
            ),
            subprocess.CompletedProcess([], 0, stdout=b'{"status":"data_returned"}'),
        )
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(ProviderTransportError) as raised:
                    ModalProtoTransport(
                        process_runner=lambda *_args, **_kwargs: response
                    ).probe("modal-id", "modal-secret", "genomilab-research")
                self.assertEqual(
                    raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE
                )


if __name__ == "__main__":
    unittest.main()
