from __future__ import annotations

import builtins
import socket
import unittest
from unittest.mock import patch

from genomi.lab.esm_transport import BiohubESMTransport
from genomi.lab.evidence_types import EvidenceStatus, ProviderTransportError
from genomi.lab.proto_transport import ModalProtoTransport


class ScientificModelTransportTests(unittest.TestCase):
    def test_biohub_probe_rejects_invalid_credentials_without_runtime_access(
        self,
    ) -> None:
        transport = BiohubESMTransport()

        for token in ("", " \t\n"):
            with self.subTest(token=token):
                with self.assertRaises(ProviderTransportError) as raised:
                    transport.probe(token)

                self.assertEqual(
                    raised.exception.status,
                    EvidenceStatus.AUTHENTICATION_FAILED,
                )

    def test_biohub_probe_is_fail_closed_without_import_or_network_access(self) -> None:
        transport = BiohubESMTransport()

        with self.assertRaises(ProviderTransportError) as raised:
            with (
                patch.object(
                    builtins,
                    "__import__",
                    side_effect=AssertionError("probe imported a runtime"),
                ),
                patch.object(
                    socket.socket,
                    "connect",
                    side_effect=AssertionError("probe opened a network connection"),
                ),
                patch.object(
                    socket.socket,
                    "connect_ex",
                    side_effect=AssertionError("probe opened a network connection"),
                ),
            ):
                transport.probe("explicit-biohub-token")

        self.assertEqual(raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE)
        self.assertFalse(transport.verification_available)

    def test_biohub_exposes_no_sequence_or_factory_execution_path(self) -> None:
        factory_calls: list[str] = []

        def forbidden_factory(_token: str) -> object:
            factory_calls.append("called")
            raise AssertionError("factory must not run")

        with self.assertRaises(TypeError):
            BiohubESMTransport(client_factory=forbidden_factory)  # type: ignore[call-arg]

        transport = BiohubESMTransport()
        self.assertFalse(hasattr(transport, "analyze_sequence"))
        self.assertEqual(factory_calls, [])

    def test_proto_probe_rejects_invalid_credentials_without_network(self) -> None:
        transport = ModalProtoTransport()
        with self.assertRaises(ProviderTransportError) as raised:
            transport.probe("", "modal-secret", "genomilab-research")
        self.assertEqual(raised.exception.status, EvidenceStatus.AUTHENTICATION_FAILED)
        self.assertNotIn("modal-secret", str(raised.exception))

    def test_modal_credentials_cannot_trigger_proto_or_ambient_network_verification(
        self,
    ) -> None:
        transport = ModalProtoTransport()
        self.assertFalse(transport.verification_available)
        with self.assertRaises(ProviderTransportError) as raised:
            transport.probe("modal-id", "modal-secret", "genomilab-research")
        self.assertEqual(raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
