"""Loopback-only HTTP server for the GenomiLab portal."""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from ..operations import call_operation
from ..runtime.context.normalize import GENOMI_SESSION_ENV
from .harness import InstalledCodexAppServerAdapter
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
    r"(context-candidate|context-approval|context-compare|harness-preview|start|resume|messages|"
    r"replace-harness|cancel|revoke-context|review-packet|plan-accept|"
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
        self._require_session()
        if parsed.path == "/api/v1/bootstrap":
            payload = self.server.service.bootstrap()
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
        with self.server.launch_token_lock:
            valid = (
                not self.server.launch_token_consumed
                and bool(launch_token)
                and secrets.compare_digest(launch_token, self.server.launch_token)
            )
            if valid:
                self.server.launch_token_consumed = True
        if not valid:
            raise LabError(
                "invalid_launch_token",
                "This launch link is not valid.",
                http_status=401,
            )
        self._send_json(
            HTTPStatus.OK,
            {
                "session_token": self.server.session_token,
                "csrf_token": self.server.csrf_token,
            },
        )

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
        if parsed.path == "/api/v1/investigations":
            payload = self._read_json()
            investigation = self.server.service.create_investigation(payload)
            self._send_json(HTTPStatus.CREATED, investigation)
            return
        match = _INVESTIGATION_ACTION_ROUTE.fullmatch(parsed.path)
        if match:
            investigation_id, action = match.groups()
            payload = self._read_json()
            if action == "context-candidate":
                result = self.server.service.investigation_context_candidate(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "context-approval":
                result = self.server.service.approve_investigation_context(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.CREATED, result)
                return
            if action == "context-compare":
                result = self.server.service.compare_investigation_context_candidate(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "harness-preview":
                result = self.server.service.harness_disclosure_candidate(
                    investigation_id,
                    operation=payload.get("operation", "start_task_run"),
                    instruction=payload.get("instruction") or payload.get("message"),
                    artifact_kind=payload.get("artifact_kind", "plan"),
                    reason=payload.get("reason"),
                    command_id=payload.get("command_id"),
                    expected_revision=payload.get("expected_revision"),
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "plan-accept":
                result = self.server.service.accept_current_plan(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "capability-execute":
                result = self.server.service.continue_harness_capability_after_approval(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "capability-check":
                result = self.server.service.resume_harness_capability_job(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "start":
                result = self.server.service.start_investigation(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "resume":
                result = self.server.service.resume_investigation(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "messages":
                result = self.server.service.send_investigation_message(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "replace-harness":
                result = self.server.service.replace_harness_binding(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "cancel":
                result = self.server.service.cancel_background_work(
                    investigation_id, payload
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "revoke-context":
                result = self.server.service.revoke_private_context(investigation_id)
                self._send_json(HTTPStatus.OK, result)
                return
            if action == "review-packet":
                raise LabError(
                    "capability_unavailable",
                    "Review packets are planned for the patient MVP and are not enabled yet.",
                    http_status=409,
                )
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


def run_lab(
    *,
    host: str = LOOPBACK_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    harness_processing_destination: str | None = None,
) -> None:
    previous_umask = os.umask(0o077)
    previous_session = os.environ.get(GENOMI_SESSION_ENV)
    server: GenomiLabHTTPServer | None = None
    try:
        # Resolve identity in the caller's current Genomi context before the
        # portal creates its isolated session.  Only the opaque user id crosses
        # this boundary; no AGI access grant, context payload, or patient data
        # is copied into the new session.
        prior_context = call_operation("genomi.describe_context", {})
        prior_user_id = str(prior_context.get("active_user_id") or "").strip()
        os.environ[GENOMI_SESSION_ENV] = f"genomilab-{secrets.token_urlsafe(18)}"
        if prior_user_id:
            selected = call_operation(
                "active_genome_index.select_user", {"user_id": prior_user_id}
            )
            selected_user = selected.get("user")
            selected_user_id = (
                str(selected_user.get("user_id") or "").strip()
                if isinstance(selected_user, dict)
                else ""
            )
            if selected_user_id != prior_user_id:
                raise RuntimeError(
                    "GenomiLab could not bind the exact current Genomi user."
                )
        service = GenomiLabService(
            harness_adapter=InstalledCodexAppServerAdapter.discover(
                processing_destination=harness_processing_destination
            )
        )
        server = create_lab_server(host=host, port=port, service=service)
        print("GenomiLab is running locally.", file=sys.stderr)
        print(f"Open: {server.launch_url}", file=sys.stderr)
        print(
            "Press Ctrl-C to stop and revoke this session's genome access.",
            file=sys.stderr,
        )
        if open_browser:
            webbrowser.open(server.launch_url)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        if previous_session is None:
            os.environ.pop(GENOMI_SESSION_ENV, None)
        else:
            os.environ[GENOMI_SESSION_ENV] = previous_session
        os.umask(previous_umask)
