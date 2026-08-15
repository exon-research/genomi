from __future__ import annotations

import json
import os
import secrets
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from typing import Any, TextIO
from urllib.parse import urlparse

from ..operations import (
    OperationError,
    call_operation,
    defaults_applied_for_call,
    get_operation,
    operation_discovery_payload,
)
from ..runtime import background_jobs, portal_routes
from .presentation import present_result
from . import portal

JsonObject = dict[str, Any]
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_HTTP_HOST = portal_routes.DEFAULT_HTTP_HOST
DEFAULT_HTTP_PORT = portal_routes.DEFAULT_HTTP_PORT
MAX_HTTP_REQUEST_BYTES = 64 * 1024 * 1024


def serve_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    print("[genomi] starting MCP server on stdio", file=error_stream, flush=True)
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(output_stream, _error(None, -32700, f"Parse error: {exc}"))
            continue
        response = handle_request(request)
        if response is not None:
            _write(output_stream, response)
    return 0


def serve_http(
    *,
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    open_browser: bool = False,
    stderr: TextIO | None = None,
) -> int:
    error_stream = stderr or sys.stderr
    try:
        server = make_http_server(host, port)
    except OSError as exc:
        print(
            "[genomi] portal port unavailable at "
            f"{portal_routes.portal_url(host, port)}; stop the existing server or pass --port. ({exc})",
            file=error_stream,
            flush=True,
        )
        return 1
    actual_host, actual_port = server.server_address
    portal_url = portal_routes.portal_url(actual_host, actual_port)
    print(f"[genomi] starting GenomiLab workspace on {portal_url}", file=error_stream, flush=True)
    print(f"[genomi] starting MCP server on {portal_routes.mcp_url(actual_host, actual_port)}", file=error_stream, flush=True)
    if open_browser:
        try:
            webbrowser.open(portal_url)
        except Exception as exc:
            print(f"[genomi] could not open browser automatically: {exc}", file=error_stream, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def make_http_server(
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
) -> ThreadingHTTPServer:
    return _GenomiMCPHTTPServer((host, port), _GenomiMCPHTTPRequestHandler)


def handle_request(request: JsonObject) -> JsonObject | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "genomi", "version": "0.1.0"},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        capability = params.get("capability") if isinstance(params, dict) else None
        namespace = params.get("namespace") if isinstance(params, dict) else None
        try:
            return _result(request_id, operation_discovery_payload(capability=capability, namespace=namespace))
        except OperationError as exc:
            return _error(request_id, -32602, exc.message)
    if method == "tools/call":
        if not isinstance(params, dict):
            return _error(request_id, -32602, "tools/call params must be an object")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _error(request_id, -32602, "tools/call requires a string name")
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "tools/call arguments must be an object")
        try:
            arguments = dict(arguments)
            operation = get_operation(name)
            if _background_enabled() and operation.mcp_background_eligible:
                timeout_seconds = background_jobs.background_timeout_seconds()
                job = background_jobs.start_operation_job(name, arguments)
                job = background_jobs.wait_for_job(str(job["job_id"]), timeout_seconds=timeout_seconds)
                if job.get("status") == "completed":
                    result = job.get("result") or {}
                    if not isinstance(result, dict):
                        raise OperationError("invalid_background_result", "background operation result must be an object")
                    presented = present_result(name, result)
                elif job.get("status") == "failed":
                    error = job.get("error") if isinstance(job.get("error"), dict) else {}
                    error_payload = OperationError(
                        str(error.get("code") or "background_job_failed"),
                        str(error.get("message") or "Background job failed."),
                    ).to_json(operation=name)
                    return _result(
                        request_id,
                        {
                            "content": [{"type": "text", "text": json.dumps(error_payload, indent=2, sort_keys=True)}],
                            "isError": True,
                        },
                    )
                else:
                    presented = background_jobs.public_job_status(job, timeout_seconds=timeout_seconds)
                    defaults = defaults_applied_for_call(name, arguments)
                    if defaults:
                        presented["defaults_applied"] = defaults
            else:
                result = call_operation(name, arguments)
                presented = present_result(name, result)
            return _result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(presented, indent=2, sort_keys=False)}]},
            )
        except OperationError as exc:
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps(exc.to_json(operation=name), indent=2, sort_keys=True)}],
                    "isError": True,
                },
            )
        except Exception as exc:
            error_payload = OperationError("internal_error", str(exc)).to_json(operation=name)
            return _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(error_payload, indent=2, sort_keys=True),
                        }
                    ],
                    "isError": True,
                },
            )
    return _error(request_id, -32601, f"Method not found: {method}")


def handle_http_payload(payload: Any) -> tuple[int, JsonObject | list[JsonObject] | None]:
    """Handle a JSON-RPC HTTP payload using the same implementation as stdio MCP."""

    if isinstance(payload, list):
        responses: list[JsonObject] = []
        for item in payload:
            response = handle_request(item) if isinstance(item, dict) else _error(None, -32600, "Invalid Request")
            if response is not None:
                responses.append(response)
        return (HTTPStatus.OK, responses) if responses else (HTTPStatus.ACCEPTED, None)
    if isinstance(payload, dict):
        response = handle_request(payload)
        return (HTTPStatus.OK, response) if response is not None else (HTTPStatus.ACCEPTED, None)
    return HTTPStatus.BAD_REQUEST, _error(None, -32600, "Invalid Request")


class _GenomiMCPHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], RequestHandlerClass: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.portal_csrf_token = secrets.token_urlsafe(32)


class _GenomiMCPHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "GenomiMCP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == portal_routes.HEALTH_ENDPOINT:
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "server": "genomi",
                    "transport": "http",
                    "mcp_endpoint": portal_routes.MCP_ENDPOINT,
                    "portal_endpoint": portal_routes.PORTAL_ENDPOINT,
                },
            )
            return
        if portal.is_portal_get_path(path) and not self._portal_request_allowed():
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if portal.handle_get(self, path, parsed.query):
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers("0")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, Mcp-Session-Id, Last-Event-ID")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in {portal_routes.MCP_ENDPOINT, f"{portal_routes.MCP_ENDPOINT}/"}:
            if portal.is_portal_post_path(path) and not self._portal_request_allowed():
                self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            if portal.handle_post_request(self, path):
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self._send_json(HTTPStatus.LENGTH_REQUIRED, _error(None, -32600, "Missing Content-Length"))
            return
        try:
            length = int(content_length)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, _error(None, -32600, "Invalid Content-Length"))
            return
        if length < 0 or length > MAX_HTTP_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _error(None, -32600, "Request body too large"))
            return

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, _error(None, -32700, f"Parse error: {exc}"))
            return

        status, response = handle_http_payload(payload)
        self._send_json(status, response)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[genomi] http {self.address_string()} - {format % args}", file=sys.stderr, flush=True)

    def _send_json(self, status: int, payload: JsonObject | list[JsonObject] | None) -> None:
        body = b"" if payload is None else (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(status)
        self._send_common_headers(str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_common_headers(self, content_length: str) -> None:
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", content_length)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")

    def _portal_request_allowed(self) -> bool:
        return self._portal_client_allowed() and self._portal_host_allowed()

    def _portal_client_allowed(self) -> bool:
        try:
            return _is_loopback_host(str(self.client_address[0]))
        except (IndexError, TypeError):
            return False

    def _portal_host_allowed(self) -> bool:
        raw_host = str(self.headers.get("Host") or "").strip()
        if not raw_host:
            return False
        candidate = _host_name(raw_host)
        if candidate == "localhost":
            return True
        return _is_loopback_host(candidate)


def _background_enabled() -> bool:
    env_value = os.environ.get("GENOMI_MCP_BACKGROUND", "1").strip().lower()
    return env_value not in {"0", "false", "no", "off", "disabled"}


def _result(request_id: Any, result: JsonObject) -> JsonObject:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> JsonObject:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}


def _host_name(raw_host: str) -> str:
    host = raw_host.strip()
    if host.startswith("["):
        closing = host.find("]")
        return host[1:closing].lower() if closing > 0 else host.strip("[]").lower()
    return host.rsplit(":", 1)[0].lower() if ":" in host else host.lower()


def _is_loopback_host(candidate: str) -> bool:
    try:
        address = ip_address(candidate)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _write(stream: TextIO, payload: JsonObject) -> None:
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()
