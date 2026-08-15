from __future__ import annotations

import io
import json
import re
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
        self.created_observations: list[dict[str, object]] = []
        self.created_source_artifacts: list[dict[str, object]] = []
        self.created_specimens: list[dict[str, object]] = []
        self.created_assays: list[dict[str, object]] = []
        self.revised_observations: list[tuple[str, dict[str, object]]] = []
        self.context_candidate_requests: list[tuple[str, dict[str, object]]] = []
        self.authorization_requests: list[
            tuple[str, str, dict[str, object]]
        ] = []
        self.integration_requests: list[tuple[str, str, object]] = []
        self.bootstrap_error: Exception | None = None

    def close(self) -> None:
        return

    def bootstrap(self) -> dict[str, object]:
        if self.bootstrap_error is not None:
            raise self.bootstrap_error
        return {
            "status": "ready",
            "product": "GenomiLab",
            "workspace": {"workspace_id": "workspace-acde1234"},
        }

    def integrations(self) -> dict[str, object]:
        return {
            "status": "ready",
            "integrations": [
                {
                    "provider": "paperclip",
                    "connection_state": "not_configured",
                    "credential_state": "missing",
                    "execution_location": "remote",
                    "policy_state": "blocked_missing_deployment_authorization",
                    "investigation_operations": [],
                    "investigation_routes": [],
                    "investigation_purposes": [],
                    "last_verified_at": None,
                    "use_scope": "fixed_public_connection_probe",
                }
            ],
        }

    def connect_integration(
        self, provider: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.integration_requests.append((provider, "connect", dict(payload)))
        return {
            "provider": provider,
            "connection_state": "configured_unverified",
            "credential_state": "stored",
            "policy_state": "blocked_missing_deployment_authorization",
        }

    def verify_integration(self, provider: str) -> dict[str, object]:
        self.integration_requests.append((provider, "verify", None))
        return {"provider": provider, "connection_state": "ready"}

    def disconnect_integration(
        self, provider: str, *, confirmed: bool
    ) -> dict[str, object]:
        self.integration_requests.append((provider, "disconnect", confirmed))
        return {"provider": provider, "connection_state": "not_configured"}

    def add_profile_observation(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_observations.append(payload)
        return {"observation_revision_id": "observation-revision-acde1234", **payload}

    def investigation_context_candidate(
        self, investigation_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.context_candidate_requests.append((investigation_id, payload))
        return {
            "status": "candidate",
            "investigation_id": investigation_id,
            "genomic_scope": {
                "operation": "variant.resolve",
                "rsid": "rs123",
            },
        }

    def investigation_authorization_candidate(
        self, investigation_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.authorization_requests.append(
            (investigation_id, "candidate", dict(payload))
        )
        return {
            "status": "authorization_required",
            "investigation_id": investigation_id,
            "authorization_candidate_receipt": "signed-candidate",
            "authorization_scope": {"harness": {}, "providers": []},
        }

    def authorize_and_start_investigation(
        self, investigation_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.authorization_requests.append(
            (investigation_id, "start", dict(payload))
        )
        return {"status": "in_progress", "investigation_id": investigation_id}

    def add_source_artifact(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_source_artifacts.append(payload)
        return {"artifact_id": "artifact-acde1234", **payload}

    def add_specimen(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_specimens.append(payload)
        return {"specimen_id": "specimen-acde1234", **payload}

    def add_assay(self, payload: dict[str, object]) -> dict[str, object]:
        self.created_assays.append(payload)
        return {"assay_id": "assay-acde1234", **payload}

    def review_or_supersede_observation(
        self, observation_revision_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.revised_observations.append((observation_revision_id, payload))
        return {
            "observation_revision_id": "observation-revision-beef1234",
            "supersedes_revision_id": observation_revision_id,
            **payload,
        }


class _Response:
    def __init__(self, raw: bytes) -> None:
        header_block, separator, self.body = raw.partition(b"\r\n\r\n")
        if not separator:
            raise AssertionError(
                f"handler did not emit a complete HTTP response: {raw!r}"
            )
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
    def session_header(self) -> str:
        return self.server.session_token

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
        return {"X-GenomiLab-Session": self.session_header}

    def mutation_headers(
        self, *, content_type: str = "application/json"
    ) -> dict[str, str]:
        return {
            "X-GenomiLab-Session": self.session_header,
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

    def test_fragment_launch_token_is_exchanged_once_without_a_cookie(self) -> None:
        self.assertEqual(
            self.server.launch_url,
            f"{self.origin}/#token={quote(self.launch_token, safe='')}",
        )
        shell = self.request("GET", "/")
        self.assertEqual(shell.status, 200)
        self.assertNotIn(self.launch_token, shell.body.decode("utf-8"))
        self.assertIsNone(shell.headers.get("Set-Cookie"))

        exchange = self.request(
            "POST",
            "/api/v1/session",
            headers={
                "Origin": self.origin,
                "X-GenomiLab-Launch-Token": self.launch_token,
            },
        )
        self.assertEqual(exchange.status, 200)
        self.assertEqual(exchange.json()["session_token"], self.server.session_token)
        self.assertEqual(exchange.json()["csrf_token"], self.server.csrf_token)
        self.assertNotEqual(exchange.json()["session_token"], self.launch_token)
        self.assertIsNone(exchange.headers.get("Set-Cookie"))

        authenticated = self.request(
            "GET", "/api/v1/bootstrap", headers=self.authenticated_headers()
        )
        self.assertEqual(authenticated.status, 200)
        self.assertNotIn("csrf_token", authenticated.json())

        replay = self.request(
            "POST",
            "/api/v1/session",
            headers={
                "Origin": self.origin,
                "X-GenomiLab-Launch-Token": self.launch_token,
            },
        )
        self.assert_error(replay, 401, "invalid_launch_token")

    def test_query_launch_token_and_ambient_cookies_never_authenticate(self) -> None:
        query_launch = self.request("GET", f"/?token={quote(self.launch_token)}")
        self.assert_error(query_launch, 400, "invalid_request")
        self.assertFalse(self.server.launch_token_consumed)
        self.assertIsNone(query_launch.headers.get("Set-Cookie"))

        missing_session = self.request("GET", "/api/v1/bootstrap")
        self.assert_error(missing_session, 401, "authentication_required")

        stolen_loopback_cookie = self.request(
            "GET",
            "/api/v1/bootstrap",
            headers={
                "Cookie": f"genomilab_session={self.server.session_token}",
            },
        )
        self.assert_error(stolen_loopback_cookie, 401, "authentication_required")

        wrong_header = self.request(
            "GET",
            "/api/v1/bootstrap",
            headers={"X-GenomiLab-Session": "wrong"},
        )
        self.assert_error(wrong_header, 401, "authentication_required")

    def test_hostile_loopback_port_cannot_exchange_or_replay_ambient_auth(self) -> None:
        hostile_origin = f"http://{LOOPBACK_HOST}:{self.port + 1}"
        hostile_exchange = self.request(
            "POST",
            "/api/v1/session",
            headers={
                "Origin": hostile_origin,
                "X-GenomiLab-Launch-Token": self.launch_token,
            },
        )
        self.assert_error(hostile_exchange, 403, "invalid_origin")
        self.assertFalse(self.server.launch_token_consumed)

        rightful_exchange = self.request(
            "POST",
            "/api/v1/session",
            headers={
                "Origin": self.origin,
                "X-GenomiLab-Launch-Token": self.launch_token,
            },
        )
        self.assertEqual(rightful_exchange.status, 200)

        ambient_replay = self.request(
            "GET",
            "/api/v1/bootstrap",
            headers={
                "Cookie": f"genomilab_session={self.server.session_token}",
                "Origin": hostile_origin,
            },
        )
        self.assert_error(ambient_replay, 401, "authentication_required")

    def test_host_origin_and_csrf_are_all_enforced(self) -> None:
        bad_host = self.request(
            "GET",
            "/healthz",
            headers={"Host": "attacker.example"},
        )
        self.assert_error(bad_host, 403, "invalid_host")

        body = b'{"modality":"pathology","label":"Synthetic finding"}'
        no_origin = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers={
                "X-GenomiLab-Session": self.session_header,
                "X-GenomiLab-CSRF": self.server.csrf_token,
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(no_origin, 403, "invalid_origin")

        bad_origin = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers={
                "X-GenomiLab-Session": self.session_header,
                "Origin": "http://attacker.example",
                "X-GenomiLab-CSRF": self.server.csrf_token,
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(bad_origin, 403, "invalid_origin")

        bad_csrf = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers={
                "X-GenomiLab-Session": self.session_header,
                "Origin": self.origin,
                "X-GenomiLab-CSRF": "wrong",
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(bad_csrf, 403, "invalid_csrf_token")

        accepted = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers=self.mutation_headers(),
            body=body,
        )
        self.assertEqual(accepted.status, 201)
        self.assertEqual(
            self.service.created_observations,
            [{"modality": "pathology", "label": "Synthetic finding"}],
        )

    def test_json_content_type_length_and_size_limits(self) -> None:
        wrong_type = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers=self.mutation_headers(content_type="text/plain"),
            body=b"{}",
        )
        self.assert_error(wrong_type, 415, "unsupported_media_type")

        missing_length = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers=self.mutation_headers(),
            body=b"{}",
            add_content_length=False,
        )
        self.assert_error(missing_length, 411, "content_length_required")

        oversized_headers = self.mutation_headers()
        oversized_headers["Content-Length"] = str(MAX_JSON_BYTES + 1)
        oversized = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers=oversized_headers,
        )
        self.assert_error(oversized, 413, "request_too_large")

        non_object = self.request(
            "POST",
            "/api/v1/molecular-profile/observations",
            headers=self.mutation_headers(),
            body=b"[]",
        )
        self.assert_error(non_object, 400, "invalid_json")

        investigation_wrong_type = self.request(
            "POST",
            "/api/v1/investigations",
            headers=self.mutation_headers(content_type="text/plain"),
            body=b"{}",
        )
        self.assert_error(investigation_wrong_type, 415, "unsupported_media_type")

    def test_integration_setup_is_authenticated_csrf_protected_and_redacted(
        self,
    ) -> None:
        unauthenticated = self.request("GET", "/api/v1/integrations")
        self.assert_error(unauthenticated, 401, "authentication_required")

        listing = self.request(
            "GET", "/api/v1/integrations", headers=self.authenticated_headers()
        )
        self.assertEqual(listing.status, 200)
        self.assertNotIn("api_key", listing.body.decode("utf-8"))

        body = b'{"api_key":"gxl-super-secret"}'
        missing_csrf = self.request(
            "POST",
            "/api/v1/integrations/paperclip/connect",
            headers={
                "X-GenomiLab-Session": self.session_header,
                "Origin": self.origin,
                "Content-Type": "application/json",
            },
            body=body,
        )
        self.assert_error(missing_csrf, 403, "invalid_csrf_token")

        connected = self.request(
            "POST",
            "/api/v1/integrations/paperclip/connect",
            headers=self.mutation_headers(),
            body=body,
        )
        self.assertEqual(connected.status, 200)
        self.assertNotIn("gxl-super-secret", connected.body.decode("utf-8"))
        self.assertEqual(
            self.service.integration_requests,
            [("paperclip", "connect", {"api_key": "gxl-super-secret"})],
        )

    def test_integration_actions_accept_only_fixed_provider_and_payload_shapes(
        self,
    ) -> None:
        unknown = self.request(
            "POST",
            "/api/v1/integrations/arbitrary/connect",
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assert_error(unknown, 404, "not_found")

        verify_fields = self.request(
            "POST",
            "/api/v1/integrations/biohub-esm/verify",
            headers=self.mutation_headers(),
            body=b'{"sequence":"forbidden"}',
        )
        self.assert_error(verify_fields, 400, "invalid_integration_request")

        disconnect_fields = self.request(
            "POST",
            "/api/v1/integrations/proto/disconnect",
            headers=self.mutation_headers(),
            body=b'{"confirmed":true,"command":"forbidden"}',
        )
        self.assert_error(disconnect_fields, 400, "invalid_integration_request")

        verified = self.request(
            "POST",
            "/api/v1/integrations/biohub-esm/verify",
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assertEqual(verified.status, 200)
        self.assertEqual(
            self.service.integration_requests,
            [("biohub-esm", "verify", None)],
        )

    def test_one_start_authorization_routes_delegate_exact_json_payloads(
        self,
    ) -> None:
        investigation_id = "investigation-acde1234"
        selection = {
            "purpose": "Investigate a synthetic condition",
            "observation_revision_ids": ["observation-revision-acde1234"],
        }
        candidate = self.request(
            "POST",
            f"/api/v1/investigations/{investigation_id}/authorization-candidate",
            headers=self.mutation_headers(),
            body=json.dumps(selection).encode("utf-8"),
        )
        self.assertEqual(candidate.status, 200)

        approval = {
            "authorization_candidate_receipt": "signed-candidate",
            "approved": True,
        }
        started = self.request(
            "POST",
            f"/api/v1/investigations/{investigation_id}/authorize-start",
            headers=self.mutation_headers(),
            body=json.dumps(approval).encode("utf-8"),
        )
        self.assertEqual(started.status, 201)
        self.assertEqual(
            self.service.authorization_requests,
            [
                (investigation_id, "candidate", selection),
                (investigation_id, "start", approval),
            ],
        )

    def test_profile_entity_and_revision_routes_delegate_exact_json_payloads(
        self,
    ) -> None:
        cases = (
            (
                "/api/v1/molecular-profile/source-artifacts",
                {
                    "content_sha256": "a" * 64,
                    "source_type": "laboratory_report",
                    "title": "Synthetic report",
                },
                self.service.created_source_artifacts,
                "artifact_id",
            ),
            (
                "/api/v1/molecular-profile/specimens",
                {
                    "artifact_id": "artifact-acde1234",
                    "specimen_type": "blood",
                    "tumor_normal_role": "germline",
                },
                self.service.created_specimens,
                "specimen_id",
            ),
            (
                "/api/v1/molecular-profile/assays",
                {
                    "artifact_id": "artifact-acde1234",
                    "specimen_id": "specimen-acde1234",
                    "assay_type": "targeted panel",
                    "assay_scope": {"reported_description": "panel genes"},
                    "detection_limits": {
                        "reported_description": "report-stated limits"
                    },
                },
                self.service.created_assays,
                "assay_id",
            ),
        )
        for path, payload, recorded, identifier_field in cases:
            with self.subTest(path=path):
                response = self.request(
                    "POST",
                    path,
                    headers=self.mutation_headers(),
                    body=json.dumps(payload).encode("utf-8"),
                )
                self.assertEqual(response.status, 201)
                self.assertEqual(recorded[-1], payload)
                self.assertIn(identifier_field, response.json())

        revision_payload = {
            "label": "Patient-reported correction",
            "artifact_id": "artifact-acde1234",
        }
        response = self.request(
            "POST",
            (
                "/api/v1/molecular-profile/observations/"
                "observation-revision-acde1234/supersede"
            ),
            headers=self.mutation_headers(),
            body=json.dumps(revision_payload).encode("utf-8"),
        )
        self.assertEqual(response.status, 201)
        self.assertEqual(
            self.service.revised_observations[-1],
            ("observation-revision-acde1234", revision_payload),
        )
        self.assertEqual(
            response.json()["supersedes_revision_id"],
            "observation-revision-acde1234",
        )

        malformed = self.request(
            "POST",
            (
                "/api/v1/molecular-profile/observations/"
                "observation-revision-not-hex/supersede"
            ),
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assert_error(malformed, 404, "not_found")

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
                    response.headers.get("Content-Type", "").startswith(
                        "application/json"
                    )
                )

        mutation = self.request(
            "POST",
            "/api/v1/operations",
            headers=self.mutation_headers(),
            body=b"{}",
        )
        self.assert_error(mutation, 404, "not_found")

        for legacy_action in (
            "context-candidate",
            "context-approval",
            "context-compare",
            "harness-preview",
            "start",
            "resume",
            "replace-harness",
            "plan-accept",
        ):
            with self.subTest(legacy_action=legacy_action):
                legacy = self.request(
                    "POST",
                    (
                        "/api/v1/investigations/investigation-acde1234/"
                        f"{legacy_action}"
                    ),
                    headers=self.mutation_headers(),
                    body=b"{}",
                )
                self.assert_error(legacy, 404, "not_found")

        query = self.request(
            "GET",
            "/api/v1/bootstrap?operation=genomi.list_resources",
            headers=self.authenticated_headers(),
        )
        self.assert_error(query, 400, "invalid_request")

    def test_authenticated_browser_can_load_the_complete_module_graph(self) -> None:
        visited: set[str] = set()
        pending = ["app.js"]
        while pending:
            module_name = pending.pop()
            if module_name in visited:
                continue
            response = self.request(
                "GET",
                f"/{module_name}",
                headers=self.authenticated_headers(),
            )
            with self.subTest(module=module_name):
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers.get("Content-Type"),
                    "text/javascript; charset=utf-8",
                )
            visited.add(module_name)
            source = response.body.decode("utf-8")
            pending.extend(
                re.findall(
                    r'(?:from\s+|import\s+)["\']\./([^"\']+)["\']',
                    source,
                )
            )
        self.assertGreater(len(visited), 3)

        missing = self.request(
            "GET",
            "/missing-module.js",
            headers=self.authenticated_headers(),
        )
        self.assert_error(missing, 404, "asset_not_found")

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
        self.assertIn(
            "default-src 'none'", response.headers.get("Content-Security-Policy", "")
        )
        self.assertEqual(response.headers.get("Server"), "GenomiLab")
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(response.headers.get("Access-Control-Allow-Credentials"))

        preflight = self.request(
            "OPTIONS",
            "/api/v1/molecular-profile/observations",
            headers={
                "Origin": "http://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assert_error(preflight, 405, "method_not_allowed")
        self.assertIsNone(preflight.headers.get("Access-Control-Allow-Origin"))

    def test_official_resource_links_redirect_only_to_fixed_destinations(self) -> None:
        destinations = {
            "/official/biohub-api-keys": "https://biohub.ai/developer-console/api-keys",
            "/official/biohub-terms": "https://biohub.org/terms-of-use/",
            "/official/biohub-privacy": "https://biohub.org/privacy-policy/",
            "/official/biohub-limitations": "https://biohub.ai/limitations",
        }
        for path, expected in destinations.items():
            with self.subTest(path=path):
                response = self.request("GET", path)
                self.assertEqual(response.status, 302)
                self.assertEqual(response.headers.get("Location"), expected)
                self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
                self.assertEqual(response.body, b"")

        hostile = self.request(
            "GET", "/official/biohub-api-keys?next=https://evil.test"
        )
        self.assert_error(hostile, 400, "invalid_request")

    def test_internal_errors_and_access_logs_do_not_disclose_sensitive_values(
        self,
    ) -> None:
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
