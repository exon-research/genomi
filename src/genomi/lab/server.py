"""Loopback-only HTTP server for the GenomiLab portal."""

from __future__ import annotations

import json
import re
import secrets
import threading
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from .service import GenomiLabService, LabError

JsonObject = dict[str, Any]

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 0
MAX_JSON_BYTES = 64 * 1024
_INVESTIGATION_ROUTE = re.compile(r"^/api/v1/investigations/(investigation-[a-f0-9]+)$")
_INVESTIGATION_VIEW_ROUTE = re.compile(
    r"^/api/v1/investigations/(investigation-[a-f0-9]+)/(profile|events|event-stream)$"
)
_INVESTIGATION_ACTION_ROUTE = re.compile(
    r"^/api/v1/investigations/(investigation-[a-f0-9]+)/"
    r"(authorization-candidate|authorize-context|revoke-context|"
    r"capability-execute|capability-check)$"
)
_OBSERVATION_REVISION_ROUTE = re.compile(
    r"^/api/v1/molecular-profile/observations/"
    r"(observation-revision-[a-f0-9]+)/supersede$"
)
_INTEGRATION_ACTION_ROUTE = re.compile(
    r"^/api/v1/integrations/(paperclip|biohub-esm|proto)/"
    r"(connect|verify|disconnect)$"
)
_JAVASCRIPT_MODULE_ROUTE = re.compile(r"^/[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)*\.js$")
_OFFICIAL_RESOURCE_REDIRECTS = {
    "/official/biohub-api-keys": "https://biohub.ai/developer-console/api-keys",
    "/official/biohub-terms": "https://biohub.org/terms-of-use/",
    "/official/biohub-privacy": "https://biohub.org/privacy-policy/",
    "/official/biohub-limitations": "https://biohub.ai/limitations",
}


class GenomiLabHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: GenomiLabService,
        *,
        launch_token: str | None = None,
    ) -> None:
        if address[0] != LOOPBACK_HOST:
            raise ValueError("GenomiLab only binds to 127.0.0.1")
        self.service = service
        self.launch_token = launch_token or secrets.token_urlsafe(32)
        self.launch_token_consumed = False
        self.launch_token_lock = threading.Lock()
        self._pending_launch_handoff: JsonObject | None = None
        self._active_authorization_handoff: JsonObject | None = None
        self.session_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(address, GenomiLabRequestHandler)
        port = int(self.server_address[1])
        self.base_url = f"http://{LOOPBACK_HOST}:{port}"
        # The fragment is consumed by portal JavaScript and is never included in
        # the HTTP request target, Referer header, or server access log.
        self.launch_url = f"{self.base_url}/#token={quote(self.launch_token, safe='')}"
        self.allowed_hosts = {f"{LOOPBACK_HOST}:{port}", f"localhost:{port}"}
        self.allowed_origins = {
            f"http://{LOOPBACK_HOST}:{port}",
            f"http://localhost:{port}",
        }

    def issue_launch_url(
        self, *, authorization_handoff: JsonObject | None = None
    ) -> str:
        """Issue a fresh one-time browser token with an optional private handoff.

        The handoff stays server-side until this exact launch token is exchanged.
        The URL therefore identifies neither the investigation nor its signed
        authorization candidate.
        """

        with self.launch_token_lock:
            self.launch_token = secrets.token_urlsafe(32)
            self.launch_token_consumed = False
            self._pending_launch_handoff = self._copy_authorization_handoff(
                authorization_handoff
            )
            self.launch_url = (
                f"{self.base_url}/#token={quote(self.launch_token, safe='')}"
            )
            return self.launch_url

    def exchange_launch_token(self, launch_token: str) -> JsonObject | None:
        """Consume one launch token and activate its isolated portal session."""

        with self.launch_token_lock:
            valid = (
                not self.launch_token_consumed
                and bool(launch_token)
                and secrets.compare_digest(launch_token, self.launch_token)
            )
            if not valid:
                return None
            self.launch_token_consumed = True
            self.session_token = secrets.token_urlsafe(32)
            self.csrf_token = secrets.token_urlsafe(32)
            self._active_authorization_handoff = self._pending_launch_handoff
            self._pending_launch_handoff = None
            return {
                "session_token": self.session_token,
                "csrf_token": self.csrf_token,
            }

    def authorization_handoff(self) -> JsonObject | None:
        """Return the exact handoff bound to the authenticated portal session."""

        with self.launch_token_lock:
            return deepcopy(self._active_authorization_handoff)

    def set_active_authorization_handoff(
        self, investigation_id: str, candidate: JsonObject
    ) -> None:
        with self.launch_token_lock:
            self._active_authorization_handoff = self._copy_authorization_handoff(
                {
                    "kind": "investigation_authorization",
                    "investigation_id": investigation_id,
                    "authorization_candidate": candidate,
                }
            )

    def clear_authorization_handoff(
        self,
        investigation_id: str,
        *,
        candidate_receipt: object = None,
    ) -> None:
        with self.launch_token_lock:
            handoff = self._active_authorization_handoff
            if not isinstance(handoff, dict) or (
                handoff.get("investigation_id") != investigation_id
            ):
                return
            if candidate_receipt is not None:
                candidate = handoff.get("authorization_candidate")
                active_receipt = (
                    candidate.get("authorization_candidate_receipt")
                    if isinstance(candidate, dict)
                    else None
                )
                if active_receipt != candidate_receipt:
                    return
            self._active_authorization_handoff = None

    @staticmethod
    def _copy_authorization_handoff(
        handoff: JsonObject | None,
    ) -> JsonObject | None:
        if handoff is None:
            return None
        if not isinstance(handoff, dict):
            raise TypeError("authorization_handoff must be an object")
        investigation_id = handoff.get("investigation_id")
        candidate = handoff.get("authorization_candidate")
        if (
            handoff.get("kind") != "investigation_authorization"
            or not isinstance(investigation_id, str)
            or not investigation_id
            or not isinstance(candidate, dict)
            or candidate.get("investigation_id") != investigation_id
            or not candidate.get("authorization_candidate_receipt")
        ):
            raise ValueError("authorization_handoff is incomplete")
        return deepcopy(handoff)

    def server_close(self) -> None:
        try:
            self.service.close()
        finally:
            super().server_close()


class GenomiLabRequestHandler(BaseHTTPRequestHandler):
    server: GenomiLabHTTPServer
    server_version = "GenomiLab"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except LabError as exc:
            self._send_json(exc.http_status, exc.to_json())
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "The local portal encountered an error.",
                    }
                },
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._require_host()
            if urlsplit(self.path).path == "/api/v1/session":
                self._require_origin()
                self._handle_session_exchange()
                return
            self._require_session()
            self._require_origin_and_csrf()
            self._handle_post()
        except LabError as exc:
            self._send_json(exc.http_status, exc.to_json())
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "The local portal encountered an error.",
                    }
                },
            )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {
                "error": {
                    "code": "method_not_allowed",
                    "message": "Cross-origin requests are not allowed.",
                }
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        # Request targets can contain the one-time launch token. Patient data,
        # source paths, tokens, and bodies must never enter access logs.
        return

    def version_string(self) -> str:
        return "GenomiLab"

    def _handle_get(self) -> None:
        self._require_host()
        parsed = urlsplit(self.path)
        if parsed.query:
            raise LabError(
                "invalid_request", "Unexpected query parameters.", http_status=400
            )
        if parsed.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        # The shell and its same-origin assets contain no patient data and must
        # load before the fragment-delivered launch token can be exchanged.
        if parsed.path == "/":
            self._send_asset("index.html", "text/html; charset=utf-8")
            return
        if _JAVASCRIPT_MODULE_ROUTE.fullmatch(parsed.path):
            self._send_asset(
                parsed.path.removeprefix("/"), "text/javascript; charset=utf-8"
            )
            return
        if parsed.path in {
            "/styles.css",
            "/workspace.css",
            "/brief.css",
            "/responsive.css",
        }:
            self._send_asset(parsed.path.removeprefix("/"), "text/css; charset=utf-8")
            return
        official_resource = _OFFICIAL_RESOURCE_REDIRECTS.get(parsed.path)
        if official_resource is not None:
            self._send_external_redirect(official_resource)
            return
        self._require_session()
        if parsed.path == "/api/v1/bootstrap":
            payload = self.server.service.bootstrap()
            authorization_handoff = self.server.authorization_handoff()
            if authorization_handoff is not None:
                payload = {
                    **payload,
                    "authorization_handoff": authorization_handoff,
                }
            self._send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/v1/workspace":
            payload = self.server.service.bootstrap_workspace()
            self._send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/v1/molecular-profile":
            self._send_json(HTTPStatus.OK, self.server.service.molecular_profile())
            return
        if parsed.path == "/api/v1/integrations":
            self._send_json(HTTPStatus.OK, self.server.service.integrations())
            return
        if parsed.path == "/api/v1/investigations":
            self._send_json(
                HTTPStatus.OK,
                {"investigations": self.server.service.list_investigations()},
            )
            return
        investigation_match = _INVESTIGATION_ROUTE.fullmatch(parsed.path)
        if investigation_match:
            self._send_json(
                HTTPStatus.OK,
                self.server.service.investigation(investigation_match.group(1)),
            )
            return
        view_match = _INVESTIGATION_VIEW_ROUTE.fullmatch(parsed.path)
        if view_match:
            investigation_id, view = view_match.groups()
            if view == "profile":
                payload = self.server.service.investigation_profile(investigation_id)
            elif view == "events":
                payload = self.server.service.replay_investigation_events(
                    investigation_id
                )
            else:
                after_header = self.headers.get("Last-Event-ID", "0")
                try:
                    after_sequence = int(after_header or "0")
                except ValueError as exc:
                    raise LabError(
                        "invalid_event_cursor",
                        "The event cursor must be an integer.",
                    ) from exc
                payload = self.server.service.stream_investigation_events(
                    investigation_id,
                    after_sequence=after_sequence,
                )
            self._send_json(HTTPStatus.OK, payload)
            return
        raise LabError("not_found", "Route not found.", http_status=404)

    def _handle_session_exchange(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/api/v1/session" or parsed.query:
            raise LabError(
                "invalid_request", "Unexpected session request.", http_status=400
            )
        launch_token = self.headers.get("X-GenomiLab-Launch-Token", "")
        credentials = self.server.exchange_launch_token(launch_token)
        if credentials is None:
            raise LabError(
                "invalid_launch_token",
                "This launch link is not valid.",
                http_status=401,
            )
        self._send_json(HTTPStatus.OK, credentials)

    def _handle_post(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            raise LabError("invalid_request", "Unexpected query parameters.")
        if parsed.path == "/api/v1/molecular-profile/observations":
            payload = self._read_json()
            observation = self.server.service.add_profile_observation(payload)
            self._send_json(HTTPStatus.CREATED, observation)
            return
        integration_match = _INTEGRATION_ACTION_ROUTE.fullmatch(parsed.path)
        if integration_match:
            provider, action = integration_match.groups()
            payload = self._read_json()
            if action == "connect":
                result = self.server.service.connect_integration(provider, payload)
            elif action == "verify":
                if payload:
                    raise LabError(
                        "invalid_integration_request",
                        "Connection checks do not accept request fields.",
                    )
                result = self.server.service.verify_integration(provider)
            else:
                if set(payload) != {"confirmed"}:
                    raise LabError(
                        "invalid_integration_request",
                        "Disconnect requires only explicit confirmation.",
                    )
                result = self.server.service.disconnect_integration(
                    provider, confirmed=payload.get("confirmed") is True
                )
            self._send_json(HTTPStatus.OK, {"integration": result})
            return
        observation_match = _OBSERVATION_REVISION_ROUTE.fullmatch(parsed.path)
        if observation_match:
            (observation_id,) = observation_match.groups()
            payload = self._read_json()
            observation = self.server.service.review_or_supersede_observation(
                observation_id, payload
            )
            self._send_json(HTTPStatus.CREATED, observation)
            return
        if parsed.path == "/api/v1/molecular-profile/source-artifacts":
            payload = self._read_json()
            self._send_json(
                HTTPStatus.CREATED, self.server.service.add_source_artifact(payload)
            )
            return
        if parsed.path == "/api/v1/molecular-profile/specimens":
            payload = self._read_json()
            self._send_json(
                HTTPStatus.CREATED, self.server.service.add_specimen(payload)
            )
            return
        if parsed.path == "/api/v1/molecular-profile/assays":
            payload = self._read_json()
            self._send_json(HTTPStatus.CREATED, self.server.service.add_assay(payload))
            return
        match = _INVESTIGATION_ACTION_ROUTE.fullmatch(parsed.path)
        if match:
            investigation_id, action = match.groups()
            payload = self._read_json()
            if action == "authorization-candidate":
                result = self.server.service.investigation_authorization_candidate(
                    investigation_id, payload
                )
                self.server.set_active_authorization_handoff(
                    investigation_id, result
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "authorize-context":
                result = self.server.service.authorize_investigation_context(
                    investigation_id, payload
                )
                self.server.clear_authorization_handoff(
                    investigation_id,
                    candidate_receipt=payload.get(
                        "authorization_candidate_receipt"
                    ),
                )
                self._send_json(HTTPStatus.CREATED, result)
                return
            if action == "capability-execute":
                result = self.server.service.approve_and_continue_capability(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "capability-check":
                result = self.server.service.check_capability_request(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "revoke-context":
                if payload:
                    raise LabError(
                        "invalid_context_revocation",
                        "Context revocation accepts only an empty JSON object.",
                    )
                result = self.server.service.revoke_agent_context(investigation_id)
                self.server.clear_authorization_handoff(investigation_id)
                self._send_json(HTTPStatus.OK, result)
                return
        raise LabError("not_found", "Route not found.", http_status=404)

    def _read_json(self) -> JsonObject:
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "application/json":
            raise LabError(
                "unsupported_media_type", "This route requires JSON.", http_status=415
            )
        length = self._content_length()
        if length > MAX_JSON_BYTES:
            raise LabError(
                "request_too_large", "The JSON request is too large.", http_status=413
            )
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise LabError("incomplete_request", "The request body was incomplete.")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LabError(
                "invalid_json", "The request body is not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise LabError("invalid_json", "The JSON body must be an object.")
        return payload

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise LabError(
                "content_length_required",
                "Content-Length is required.",
                http_status=411,
            )
        try:
            length = int(raw)
        except ValueError as exc:
            raise LabError(
                "invalid_content_length", "Content-Length is invalid."
            ) from exc
        if length < 0:
            raise LabError("invalid_content_length", "Content-Length is invalid.")
        return length

    def _require_host(self) -> None:
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            raise LabError(
                "invalid_host", "The request host is not allowed.", http_status=403
            )

    def _require_session(self) -> None:
        value = self.headers.get("X-GenomiLab-Session", "")
        if not value or not secrets.compare_digest(value, self.server.session_token):
            raise LabError(
                "authentication_required",
                "Open GenomiLab from its launch link.",
                http_status=401,
            )

    def _require_origin(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin not in self.server.allowed_origins:
            raise LabError(
                "invalid_origin",
                "Cross-origin requests are not allowed.",
                http_status=403,
            )

    def _require_origin_and_csrf(self) -> None:
        self._require_origin()
        token = self.headers.get("X-GenomiLab-CSRF", "")
        if not secrets.compare_digest(token, self.server.csrf_token):
            raise LabError(
                "invalid_csrf_token",
                "Refresh GenomiLab and try again.",
                http_status=403,
            )

    def _send_asset(self, name: str, content_type: str) -> None:
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise LabError(
                "asset_not_found", "Portal asset not found.", http_status=404
            )
        try:
            body = (
                resources.files("genomi.lab")
                .joinpath("static", *relative.parts)
                .read_bytes()
            )
        except (FileNotFoundError, OSError) as exc:
            raise LabError(
                "asset_not_found", "Portal asset not found.", http_status=404
            ) from exc
        self.send_response(HTTPStatus.OK)
        self._security_headers(content_type=content_type, content_length=len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int | HTTPStatus, payload: JsonObject) -> None:
        body = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(int(status))
        self._security_headers(
            content_type="application/json; charset=utf-8", content_length=len(body)
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_external_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self._security_headers(
            content_type="text/plain; charset=utf-8", content_length=0
        )
        self.end_headers()

    def _security_headers(self, *, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )


def create_lab_server(
    *,
    host: str = LOOPBACK_HOST,
    port: int = DEFAULT_PORT,
    service: GenomiLabService | None = None,
    launch_token: str | None = None,
) -> GenomiLabHTTPServer:
    if host not in {LOOPBACK_HOST, "localhost"}:
        raise ValueError("GenomiLab is local-only and must bind to 127.0.0.1")
    return GenomiLabHTTPServer(
        (LOOPBACK_HOST, int(port)),
        service or GenomiLabService(),
        launch_token=launch_token,
    )
