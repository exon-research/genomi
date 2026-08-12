from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr
from email.message import Message
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.parse import quote

from genomi.lab.server import (
    LOOPBACK_HOST,
    MAX_JSON_BYTES,
    GenomiLabHTTPServer,
    GenomiLabRequestHandler,
    create_lab_server,
)


class _SyntheticService:
    """Small patient-free service double for the HTTP security boundary."""

    def __init__(self) -> None:
        self.created_names: list[object] = []
        self.bootstrap_error: Exception | None = None

    def close(self) -> None:
        return

    def bootstrap(self) -> dict[str, object]:
        if self.bootstrap_error is not None:
            raise self.bootstrap_error
        return {
            "status": "ready",
            "product": "GenomiLab",
            "profiles": [],
        }

    def create_profile(self, display_name: object) -> dict[str, object]:
        self.created_names.append(display_name)
        return {
            "profile_id": "patient-acde1234",
            "display_name": display_name,
        }


class _Response:
    def __init__(self, raw: bytes) -> None:
        header_block, separator, self.body = raw.partition(b"\r\n\r\n")
        if not separator:
            raise AssertionError(f"handler did not emit a complete HTTP response: {raw!r}")
        lines = header_block.decode("iso-8859-1").split("\r\n")
        self.status = int(lines[0].split(" ", 2)[1])
        self.headers = Message()
        for line in lines[1:]:
            name, value = line.split(":", 1)
            self.headers.add_header(name, value.strip())

    def json(self) -> dict[str, object]:
        value = json.loads(self.body)
        if not isinstance(value, dict):
            raise AssertionError(f"expected a JSON object, got {value!r}")
        return value


def _without_socket_bind(
    server: ThreadingHTTPServer,
    address: tuple[str, int],
    _handler: type[GenomiLabRequestHandler],
) -> None:
    # The execution sandbox prohibits bind(2). The handler itself is exercised
    # end-to-end using its byte streams below; only the base socket setup is
    # replaced here.
    server.server_address = address


class GenomiLabHTTPSecurityTests(unittest.TestCase):
    port = 48123
    launch_token = "launch-secret-only-for-this-test"

    def setUp(self) -> None:
        self.service = _SyntheticService()
        self.socket_patch = mock.patch.object(
            ThreadingHTTPServer,
            "__init__",
            new=_without_socket_bind,
        )
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)
        self.server = GenomiLabHTTPServer(
            (LOOPBACK_HOST, self.port),
            self.service,
            launch_token=self.launch_token,
        )

    @property
    def host(self) -> str:
        return f"{LOOPBACK_HOST}:{self.port}"

    @property
    def origin(self) -> str:
        return f"http://{self.host}"

    @property
    def cookie(self) -> str:
        return f"genomilab_session={self.server.session_cookie}"

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        include_host: bool = True,
        add_content_length: bool = True,
    ) -> _Response:
        request_headers = dict(headers or {})
        if include_host and "Host" not in request_headers:
            request_headers["Host"] = self.host
        if body and add_content_length and "Content-Length" not in request_headers:
            request_headers["Content-Length"] = str(len(body))

        handler = GenomiLabRequestHandler.__new__(GenomiLabRequestHandler)
        handler.server = self.server
        handler.client_address = (LOOPBACK_HOST, 54321)
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.command = method
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True
        handler.headers = Message()
        for name, value in request_headers.items():
            handler.headers.add_header(name, value)
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()

        getattr(handler, f"do_{method}")()
        return _Response(handler.wfile.getvalue())

    def authenticated_headers(self) -> dict[str, str]:
        return {"Cookie": self.cookie}

    def mutation_headers(self, *, content_type: str = "application/json") -> dict[str, str]:
        return {
            "Cookie": self.cookie,
            "Origin": self.origin,
            "X-GenomiLab-CSRF": self.server.csrf_token,
            "Content-Type": content_type,
        }

    def assert_error(self, response: _Response, status: int, code: str) -> None:
        self.assertEqual(response.status, status)
        payload = response.json()
        error = payload.get("error")
        self.assertIsInstance(error, dict)
        assert isinstance(error, dict)
        self.assertEqual(error.get("code"), code)

    def test_server_refuses_non_loopback_bind_targets(self) -> None:
        with self.assertRaisesRegex(ValueError, "local-only"):
            create_lab_server(host="0.0.0.0", service=self.service)
        with self.assertRaisesRegex(ValueError, "only binds"):
            GenomiLabHTTPServer(("192.0.2.10", self.port), self.service)

    def test_launch_token_is_exchanged_once_for_strict_session_cookie(self) -> None:
        first = self.request("GET", f"/?token={quote(self.launch_token)}")

        self.assertEqual(first.status, 303)
        self.assertEqual(first.headers.get("Location"), "/")
        set_cookie = first.headers.get("Set-Cookie", "")
        self.assertIn(self.cookie, set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/", set_cookie)
        self.assertNotIn(self.launch_token, set_cookie)

        authenticated = self.request(
            "GET",
            "/api/v1/bootstrap",
            headers=self.authenticated_headers(),
        )
        self.assertEqual(authenticated.status, 200)
        self.assertEqual(authenticated.json()["csrf_token"], self.server.csrf_token)

        replay = self.request("GET", f"/?token={quote(self.launch_token)}")
        self.assert_error(replay, 401, "invalid_launch_token")
        self.assertIsNone(replay.headers.get("Set-Cookie"))

    def test_invalid_launch_token_and_cookie_do_not_authenticate(self) -> None:
        invalid_launch = self.request("GET", "/?token=wrong")
        self.assert_error(invalid_launch, 401, "invalid_launch_token")
        self.assertIsNone(invalid_launch.headers.get("Set-Cookie"))

        missing_cookie = self.request("GET", "/api/v1/bootstrap")
        self.assert_error(missing_cookie, 401, "authentication_required")

        wrong_cookie = self.request(
            "GET",
            "/api/v1/bootstrap",
            headers={"Cookie": "genomilab_session=wrong"},
        )
        self.assert_error(wrong_cookie, 401, "authentication_required")

    def test_host_origin_and_csrf_are_all_enforced(self) -> None:
        bad_host = self.request(
            "GET",
            "/healthz",
            headers={"Host": "attacker.example"},
        )
        self.assert_error(bad_host, 403, "invalid_host")

        body = b'{"display_name":"Synthetic Patient"}'
        no_origin = self.request(
            "POST",
            "/api/v1/profiles",
            headers={
                "Cookie": self.cookie,
                "X-GenomiLab-CSRF": self.server.csrf_token,
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(no_origin, 403, "invalid_origin")

        bad_origin = self.request(
            "POST",
            "/api/v1/profiles",
            headers={
                "Cookie": self.cookie,
                "Origin": "http://attacker.example",
                "X-GenomiLab-CSRF": self.server.csrf_token,
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(bad_origin, 403, "invalid_origin")

        bad_csrf = self.request(
            "POST",
            "/api/v1/profiles",
            headers={
                "Cookie": self.cookie,
                "Origin": self.origin,
                "X-GenomiLab-CSRF": "wrong",
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(bad_csrf, 403, "invalid_csrf_token")

        accepted = self.request(
            "POST",
            "/api/v1/profiles",
            headers=self.mutation_headers(),
            body=body,
        )
        self.assertEqual(accepted.status, 201)
        self.assertEqual(self.service.created_names, ["Synthetic Patient"])

    def test_json_content_type_length_and_size_limits(self) -> None:
        wrong_type = self.request(
            "POST",
            "/api/v1/profiles",
            headers=self.mutation_headers(content_type="text/plain"),
            body=b"{}",
        )
        self.assert_error(wrong_type, 415, "unsupported_media_type")

        missing_length = self.request(
            "POST",
            "/api/v1/profiles",
            headers=self.mutation_headers(),
            body=b"{}",
            add_content_length=False,
        )
        self.assert_error(missing_length, 411, "content_length_required")

        oversized_headers = self.mutation_headers()
        oversized_headers["Content-Length"] = str(MAX_JSON_BYTES + 1)
        oversized = self.request(
            "POST",
            "/api/v1/profiles",
            headers=oversized_headers,
        )
        self.assert_error(oversized, 413, "request_too_large")

        non_object = self.request(
            "POST",
            "/api/v1/profiles",
            headers=self.mutation_headers(),
            body=b"[]",
        )
        self.assert_error(non_object, 400, "invalid_json")

        upload_wrong_type = self.request(
            "POST",
            "/api/v1/profiles/patient-acde1234/genomes",
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assert_error(upload_wrong_type, 415, "unsupported_media_type")

    def test_route_allowlist_and_asset_traversal_are_rejected(self) -> None:
        for path in (
            "/api/v1/operations",
            "/api/v1/admin",
            "/static/../server.py",
            "/%2e%2e/server.py",
            "/app.js/../../server.py",
        ):
            with self.subTest(path=path):
                response = self.request(
                    "GET",
                    path,
                    headers=self.authenticated_headers(),
                )
                self.assert_error(response, 404, "not_found")
                self.assertTrue(
                    response.headers.get("Content-Type", "").startswith("application/json")
                )

        mutation = self.request(
            "POST",
            "/api/v1/operations",
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assert_error(mutation, 404, "not_found")

        query = self.request(
            "GET",
            "/api/v1/bootstrap?operation=genomi.list_resources",
            headers=self.authenticated_headers(),
        )
        self.assert_error(query, 400, "invalid_request")

    def test_security_headers_are_present_and_cors_is_absent(self) -> None:
        response = self.request("GET", "/healthz")

        self.assertEqual(response.status, 200)
        expected = {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-origin",
        }
        for name, value in expected.items():
            self.assertEqual(response.headers.get(name), value, name)
        self.assertIn("default-src 'none'", response.headers.get("Content-Security-Policy", ""))
        self.assertEqual(response.headers.get("Server"), "GenomiLab")
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(response.headers.get("Access-Control-Allow-Credentials"))

        preflight = self.request(
            "OPTIONS",
            "/api/v1/profiles",
            headers={
                "Origin": "http://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assert_error(preflight, 405, "method_not_allowed")
        self.assertIsNone(preflight.headers.get("Access-Control-Allow-Origin"))

    def test_internal_errors_and_access_logs_do_not_disclose_sensitive_values(self) -> None:
        sensitive = "Synthetic Patient; rs999999; /private/intake/source.vcf"
        self.service.bootstrap_error = RuntimeError(sensitive)
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            response = self.request(
                "GET",
                "/api/v1/bootstrap",
                headers=self.authenticated_headers(),
            )

        self.assert_error(response, 500, "internal_error")
        self.assertNotIn(sensitive, response.body.decode("utf-8"))
        self.assertNotIn(sensitive, stderr.getvalue())
        self.assertNotIn(self.launch_token, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
