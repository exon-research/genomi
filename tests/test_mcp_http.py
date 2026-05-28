from __future__ import annotations

import http.client
import json
import threading
import unittest

from genomi.interfaces import mcp


class MCPHTTPTests(unittest.TestCase):
    def test_health_endpoint_reports_http_transport(self) -> None:
        with _running_server() as address:
            status, payload = _request_json("GET", address, "/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["server"], "genomi")
        self.assertEqual(payload["transport"], "http")
        self.assertEqual(payload["mcp_endpoint"], "/mcp")

    def test_mcp_endpoint_reuses_initialize_handler(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

        with _running_server() as address:
            status, payload = _request_json("POST", address, "/mcp?view=default", request)

        self.assertEqual(status, 200)
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["result"]["serverInfo"]["name"], "genomi")
        self.assertEqual(payload["result"]["capabilities"], {"tools": {}})

    def test_initialized_notification_returns_accepted_without_body(self) -> None:
        request = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}

        with _running_server() as address:
            status, payload = _request_json("POST", address, "/mcp", request)

        self.assertEqual(status, 202)
        self.assertIsNone(payload)


class _running_server:
    def __enter__(self) -> tuple[str, int]:
        self.server = mcp.make_http_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_address

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _request_json(
    method: str,
    address: tuple[str, int],
    path: str,
    payload: object | None = None,
) -> tuple[int, object | None]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection = http.client.HTTPConnection(address[0], address[1], timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        parsed = json.loads(data.decode("utf-8")) if data else None
        return response.status, parsed
    finally:
        connection.close()

