from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import genomi.lab.esm_transport as esm_transport
from genomi.lab.esm_transport import (
    BIOHUB_ESM_API_URL,
    BIOHUB_ESM_MAX_RESPONSE_BYTES,
    BIOHUB_ESM_MODEL,
    BIOHUB_ESM_PROBE_SEQUENCE,
    BIOHUB_ESM_PROBE_TOKENS,
    BiohubESMTransport,
)
from genomi.lab.evidence_types import EvidenceStatus, ProviderTransportError


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        content_type: str = "application/json; charset=utf-8",
        content_encoding: str = "",
    ) -> None:
        self.headers = {
            "Content-Type": content_type,
            "Content-Encoding": content_encoding,
        }
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._body[:size]


def _sdk_derived_nextjs_encode_response() -> dict[str, object]:
    """Strict wrapper documented by the pinned Biohub SDK; not a live capture."""

    return {
        "data": {
            "outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)},
            "potential_sequence_of_concern": False,
        }
    }


class BiohubESMTransportTests(unittest.TestCase):
    def test_biohub_probe_uses_only_the_fixed_synthetic_json_request(self) -> None:
        captured: dict[str, object] = {}

        def open_request(request: object, *, timeout: float) -> _Response:
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                {
                    "outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)},
                    "potential_sequence_of_concern": False,
                }
            )

        transport = BiohubESMTransport(open_request=open_request)
        transport.probe(" explicit-biohub-token ")

        request = captured["request"]
        self.assertEqual(request.full_url, BIOHUB_ESM_API_URL)
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.get_header("Authorization"), "Bearer explicit-biohub-token"
        )
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        body = json.loads(request.data)
        self.assertEqual(body["model"], BIOHUB_ESM_MODEL)
        self.assertEqual(body["inputs"], {"sequence": BIOHUB_ESM_PROBE_SEQUENCE})
        self.assertFalse(body["potential_sequence_of_concern"])
        self.assertTrue(transport.verification_available)

    def test_biohub_probe_ignores_ambient_tokens_and_makes_one_request(self) -> None:
        requests: list[object] = []

        def open_request(request: object, **_kwargs: object) -> _Response:
            requests.append(request)
            return _Response(
                {
                    "outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)},
                    "potential_sequence_of_concern": False,
                }
            )

        with patch.dict(os.environ, {"ESM_API_KEY": "ambient-secret"}):
            BiohubESMTransport(open_request=open_request).probe("explicit-token")

        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].get_header("Authorization"), "Bearer explicit-token"
        )

    def test_biohub_probe_accepts_only_the_sdk_documented_nextjs_wrapper(
        self,
    ) -> None:
        BiohubESMTransport(
            open_request=lambda *_args, **_kwargs: _Response(
                _sdk_derived_nextjs_encode_response()
            )
        ).probe("biohub-token")

        wrapped = _sdk_derived_nextjs_encode_response()
        wrapped["request_id"] = "unexpected-sibling"
        with self.assertRaises(ProviderTransportError) as raised:
            BiohubESMTransport(
                open_request=lambda *_args, **_kwargs: _Response(wrapped)
            ).probe("biohub-token")
        self.assertEqual(raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE)

    def test_biohub_default_opener_installs_a_redirect_rejector(self) -> None:
        opened: list[object] = []

        sentinel_response = object()

        class Opener:
            def open(self, request: object, *, timeout: float) -> object:
                opened.append((request, timeout))
                return sentinel_response

        captured_handlers: list[object] = []

        def build_opener(*handlers: object) -> Opener:
            captured_handlers.extend(handlers)
            return Opener()

        request = urllib.request.Request(BIOHUB_ESM_API_URL)
        with patch.object(urllib.request, "build_opener", side_effect=build_opener):
            response = esm_transport._open_request_without_redirects(
                request, timeout=3.0
            )

        self.assertIs(response, sentinel_response)
        self.assertEqual(len(opened), 1)
        self.assertEqual(len(captured_handlers), 1)
        handler = captured_handlers[0]
        self.assertIsInstance(handler, urllib.request.HTTPRedirectHandler)
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "", {}, BIOHUB_ESM_API_URL)
        )

    def test_biohub_probe_rejects_invalid_credentials_before_network(self) -> None:
        calls: list[object] = []
        transport = BiohubESMTransport(
            open_request=lambda request, **_kwargs: calls.append(request)
        )

        for token in ("", " \t\n"):
            with self.subTest(token=token):
                with self.assertRaises(ProviderTransportError) as raised:
                    transport.probe(token)
                self.assertEqual(
                    raised.exception.status, EvidenceStatus.AUTHENTICATION_FAILED
                )
        self.assertEqual(calls, [])

    def test_biohub_probe_maps_authentication_without_leaking_response(self) -> None:
        def rejected(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.HTTPError(
                BIOHUB_ESM_API_URL,
                401,
                "secret provider response",
                {},
                io.BytesIO(b'{"detail":"secret provider response"}'),
            )

        with self.assertRaises(ProviderTransportError) as raised:
            BiohubESMTransport(open_request=rejected).probe("biohub-token")

        self.assertEqual(raised.exception.status, EvidenceStatus.AUTHENTICATION_FAILED)
        self.assertNotIn("secret", str(raised.exception))

    def test_biohub_probe_maps_provider_failures_without_retry(self) -> None:
        cases = (
            (402, EvidenceStatus.QUOTA_EXCEEDED),
            (429, EvidenceStatus.RATE_LIMITED),
            (503, EvidenceStatus.SERVER_ERROR),
        )
        for status_code, expected in cases:
            calls: list[object] = []

            def rejected(*_args: object, **_kwargs: object) -> object:
                calls.append(status_code)
                raise urllib.error.HTTPError(
                    BIOHUB_ESM_API_URL,
                    status_code,
                    "provider failure",
                    {},
                    None,
                )

            with self.subTest(status_code=status_code):
                with self.assertRaises(ProviderTransportError) as raised:
                    BiohubESMTransport(open_request=rejected).probe("biohub-token")
                self.assertEqual(raised.exception.status, expected)
                self.assertEqual(calls, [status_code])

        with self.assertRaises(ProviderTransportError) as raised:
            BiohubESMTransport(
                open_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    TimeoutError()
                )
            ).probe("biohub-token")
        self.assertEqual(raised.exception.status, EvidenceStatus.TIMEOUT)

    def test_biohub_probe_rejects_non_json_or_malformed_provider_shapes(self) -> None:
        cases = (
            _Response({"outputs": {}}, content_type="application/json"),
            _Response({"data": "not-an-object"}),
            _Response(
                {"outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)}},
                content_type="text/plain",
            ),
            _Response(
                {
                    "outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)},
                    "potential_sequence_of_concern": False,
                },
                content_encoding="gzip",
            ),
            _Response(
                {
                    "outputs": {"sequence": list(BIOHUB_ESM_PROBE_TOKENS)},
                    "potential_sequence_of_concern": True,
                }
            ),
            _Response(
                {
                    "outputs": {"sequence": [*BIOHUB_ESM_PROBE_TOKENS[:-1], 1]},
                    "potential_sequence_of_concern": False,
                }
            ),
        )
        for response in cases:
            with self.subTest(response=response):
                with self.assertRaises(ProviderTransportError) as raised:
                    BiohubESMTransport(
                        open_request=lambda *_args, **_kwargs: response
                    ).probe("biohub-token")
                self.assertEqual(
                    raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE
                )

    def test_biohub_probe_rejects_an_oversized_json_body(self) -> None:
        response = _Response({})
        response._body = b"{" + b" " * BIOHUB_ESM_MAX_RESPONSE_BYTES + b"}"

        with self.assertRaises(ProviderTransportError) as raised:
            BiohubESMTransport(open_request=lambda *_args, **_kwargs: response).probe(
                "biohub-token"
            )

        self.assertEqual(raised.exception.status, EvidenceStatus.SOURCE_UNAVAILABLE)

    def test_biohub_urlerror_timeout_is_a_timeout(self) -> None:
        def timed_out(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.URLError(TimeoutError("timed out"))

        with self.assertRaises(ProviderTransportError) as raised:
            BiohubESMTransport(open_request=timed_out).probe("biohub-token")

        self.assertEqual(raised.exception.status, EvidenceStatus.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
