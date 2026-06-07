"""Local static server support for rendered dashboard artifacts."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ...runtime import background_jobs

JsonObject = dict[str, Any]

_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_VERIFY_TIMEOUT_SECONDS = 1.5


def serve_dashboard_info(
    *,
    directory: str | Path,
    filename: str,
    start_server: bool,
) -> JsonObject:
    serve_dir = Path(directory).resolve()
    port = _find_available_port(_DEFAULT_PORT)
    url = f"http://{_HOST}:{port}/{filename}"
    command = (
        f"python3 -m http.server {port} --bind {_HOST} "
        f"--directory {shlex.quote(str(serve_dir))}"
    )
    payload: JsonObject = {
        "directory": str(serve_dir),
        "filename": filename,
        "port": port,
        "url": url,
        "command": command,
    }
    if not start_server or not autoserve_enabled():
        payload["status"] = "ready_to_start"
        return payload

    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                _HOST,
                "--directory",
                str(serve_dir),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        payload.update(
            {
                "status": "start_failed",
                "error": {"code": "dashboard_server_start_failed", "message": str(exc)},
            }
        )
        return payload

    payload["status"] = "started"
    payload["pid"] = process.pid
    verified = _verify_url(url)
    if verified is not None:
        payload["http_status"] = verified
    return payload


def autoserve_enabled() -> bool:
    configured = os.environ.get("GENOMI_DASHBOARD_AUTOSERVE")
    if configured is not None:
        return configured.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return background_jobs.background_enabled()


def _find_available_port(start: int) -> int:
    for port in range(start, start + 200):
        if _port_available(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((_HOST, port))
        except OSError:
            return False
        return True


def _verify_url(url: str) -> int | None:
    deadline = time.monotonic() + _VERIFY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.25) as response:
                return int(response.status)
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    return None
