"""Loopback-only HTTP server for the GenomiLab portal."""

from __future__ import annotations

import http.cookies
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
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..runtime.context.normalize import GENOMI_SESSION_ENV
from .service import GenomiLabService, LabError

JsonObject = dict[str, Any]

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 0
MAX_JSON_BYTES = 64 * 1024
_PROFILE_ROUTE = re.compile(r"^/api/v1/profiles/(patient-[a-f0-9]+)$")
_PROFILE_ACTION_ROUTE = re.compile(
    r"^/api/v1/profiles/(patient-[a-f0-9]+)/(activate|health-facts|reported-findings|genomes|consents/agi|investigations)$"
)
_JOB_ROUTE = re.compile(r"^/api/v1/jobs/(job-[a-f0-9]+)$")
_INVESTIGATION_ROUTE = re.compile(
    r"^/api/v1/investigations/(investigation-[a-f0-9]+)$"
)


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
        self.session_cookie = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(address, GenomiLabRequestHandler)
        port = int(self.server_address[1])
        self.base_url = f"http://{LOOPBACK_HOST}:{port}"
        self.launch_url = f"{self.base_url}/?token={self.launch_token}"
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
                {"error": {"code": "internal_error", "message": "The local portal encountered an error."}},
            )

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._require_host()
            self._require_session()
            self._require_origin_and_csrf()
            self._handle_post()
        except LabError as exc:
            self._send_json(exc.http_status, exc.to_json())
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"code": "internal_error", "message": "The local portal encountered an error."}},
            )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": {"code": "method_not_allowed", "message": "Cross-origin requests are not allowed."}},
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
        if parsed.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        token = parse_qs(parsed.query).get("token", [None])[0]
        if parsed.path == "/" and token is not None:
            with self.server.launch_token_lock:
                valid = not self.server.launch_token_consumed and secrets.compare_digest(
                    str(token), self.server.launch_token
                )
                if valid:
                    self.server.launch_token_consumed = True
            if not valid:
                raise LabError(
                    "invalid_launch_token",
                    "This launch link is not valid.",
                    http_status=401,
                )
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers(content_type="text/plain; charset=utf-8", content_length=0)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"genomilab_session={self.server.session_cookie}; HttpOnly; SameSite=Strict; Path=/",
            )
            self.end_headers()
            return
        self._require_session()
        if parsed.query:
            raise LabError("invalid_request", "Unexpected query parameters.", http_status=400)
        if parsed.path == "/":
            self._send_asset("index.html", "text/html; charset=utf-8")
            return
        if parsed.path in {"/app.js", "/api.js", "/render.js"}:
            self._send_asset(parsed.path.removeprefix("/"), "text/javascript; charset=utf-8")
            return
        if parsed.path in {
            "/styles.css",
            "/workspace.css",
            "/brief.css",
            "/responsive.css",
        }:
            self._send_asset(parsed.path.removeprefix("/"), "text/css; charset=utf-8")
            return
        if parsed.path == "/api/v1/bootstrap":
            payload = self.server.service.bootstrap()
            payload["csrf_token"] = self.server.csrf_token
            self._send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/v1/profiles":
            self._send_json(
                HTTPStatus.OK,
                {"profiles": self.server.service.bootstrap()["profiles"]},
            )
            return
        profile_match = _PROFILE_ROUTE.fullmatch(parsed.path)
        if profile_match:
            self._send_json(
                HTTPStatus.OK, self.server.service.profile(profile_match.group(1))
            )
            return
        job_match = _JOB_ROUTE.fullmatch(parsed.path)
        if job_match:
            self._send_json(
                HTTPStatus.OK, self.server.service.poll_job(job_match.group(1))
            )
            return
        investigation_match = _INVESTIGATION_ROUTE.fullmatch(parsed.path)
        if investigation_match:
            try:
                result = self.server.service.store.get_investigation(
                    investigation_match.group(1)
                )
            except KeyError as exc:
                raise LabError(
                    "investigation_not_found", "Investigation not found.", http_status=404
                ) from exc
            self._send_json(HTTPStatus.OK, result)
            return
        raise LabError("not_found", "Route not found.", http_status=404)

    def _handle_post(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query:
            raise LabError("invalid_request", "Unexpected query parameters.")
        if parsed.path == "/api/v1/profiles":
            payload = self._read_json()
            profile = self.server.service.create_profile(payload.get("display_name"))
            self._send_json(HTTPStatus.CREATED, profile)
            return
        match = _PROFILE_ACTION_ROUTE.fullmatch(parsed.path)
        if not match:
            raise LabError("not_found", "Route not found.", http_status=404)
        profile_id, action = match.groups()
        if action == "genomes":
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in {
                "application/octet-stream",
                "application/vnd.genomilab.vcf",
            }:
                raise LabError(
                    "unsupported_media_type",
                    "Genome intake requires a VCF upload body.",
                    http_status=415,
                )
            length = self._content_length()
            filename = self.headers.get("X-GenomiLab-Filename", "")
            result = self.server.service.start_genome_intake(
                profile_id,
                filename=filename,
                stream=self.rfile,
                content_length=length,
            )
            status = (
                HTTPStatus.ACCEPTED
                if result.get("status") == "in_progress"
                else HTTPStatus.CREATED
            )
            self._send_json(status, result)
            return
        payload = self._read_json()
        if action == "activate":
            result = self.server.service.activate_profile(profile_id)
        elif action == "health-facts":
            result = self.server.service.add_health_fact(profile_id, payload)
        elif action == "reported-findings":
            result = self.server.service.add_reported_finding(profile_id, payload)
        elif action == "consents/agi":
            if payload.get("approved") is not True:
                raise LabError(
                    "approval_required", "Check the approval box before granting access."
                )
            result = self.server.service.approve_genome_access(
                profile_id, purpose=payload.get("purpose")
            )
        elif action == "investigations":
            result = self.server.service.run_investigation(profile_id, payload)
        else:  # pragma: no cover - regex action set makes this unreachable.
            raise LabError("not_found", "Route not found.", http_status=404)
        self._send_json(HTTPStatus.CREATED, result)

    def _read_json(self) -> JsonObject:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise LabError(
                "unsupported_media_type", "This route requires JSON.", http_status=415
            )
        length = self._content_length()
        if length > MAX_JSON_BYTES:
            raise LabError("request_too_large", "The JSON request is too large.", http_status=413)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise LabError("incomplete_request", "The request body was incomplete.")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LabError("invalid_json", "The request body is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise LabError("invalid_json", "The JSON body must be an object.")
        return payload

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise LabError("content_length_required", "Content-Length is required.", http_status=411)
        try:
            length = int(raw)
        except ValueError as exc:
            raise LabError("invalid_content_length", "Content-Length is invalid.") from exc
        if length < 0:
            raise LabError("invalid_content_length", "Content-Length is invalid.")
        return length

    def _require_host(self) -> None:
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            raise LabError("invalid_host", "The request host is not allowed.", http_status=403)

    def _require_session(self) -> None:
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError as exc:
            raise LabError("authentication_required", "Open GenomiLab from its launch link.", http_status=401) from exc
        value = cookie.get("genomilab_session")
        if value is None or not secrets.compare_digest(value.value, self.server.session_cookie):
            raise LabError("authentication_required", "Open GenomiLab from its launch link.", http_status=401)

    def _require_origin_and_csrf(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin not in self.server.allowed_origins:
            raise LabError("invalid_origin", "Cross-origin requests are not allowed.", http_status=403)
        token = self.headers.get("X-GenomiLab-CSRF", "")
        if not secrets.compare_digest(token, self.server.csrf_token):
            raise LabError("invalid_csrf_token", "Refresh GenomiLab and try again.", http_status=403)

    def _send_asset(self, name: str, content_type: str) -> None:
        try:
            body = resources.files("genomi.lab").joinpath("static", name).read_bytes()
        except (FileNotFoundError, OSError) as exc:
            raise LabError("asset_not_found", "Portal asset not found.", http_status=404) from exc
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
) -> None:
    previous_umask = os.umask(0o077)
    previous_session = os.environ.get(GENOMI_SESSION_ENV)
    os.environ[GENOMI_SESSION_ENV] = f"genomilab-{secrets.token_urlsafe(18)}"
    server: GenomiLabHTTPServer | None = None
    try:
        server = create_lab_server(host=host, port=port)
        print("GenomiLab is running locally.", file=sys.stderr)
        print(f"Open: {server.launch_url}", file=sys.stderr)
        print("Press Ctrl-C to stop and revoke this session's genome access.", file=sys.stderr)
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
