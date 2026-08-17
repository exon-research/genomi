"""Credential-scoped Proto prerequisite verification through Modal."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from .evidence_types import EvidenceStatus, ProviderTransportError


PROTO_RUNTIME_PACKAGE: Final = "modal"
PROTO_RUNTIME_MINIMUM_VERSION: Final = "1.5.1"
PROTO_MODAL_SERVER_URL: Final = "https://api.modal.com"
PROTO_MODAL_PROBE_TIMEOUT_SECONDS: Final = 15.0
PROTO_MODAL_PROBE_WORKER: Final = "genomi.lab.proto_modal_probe_worker"
PROTO_MODAL_MAX_WORKER_RESPONSE_BYTES: Final = 4_096

ProcessRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class ModalProtoTransport:
    """Verify explicit Modal credentials and one exact existing environment.

    The Modal SDK reads server configuration from ambient state. The probe
    therefore runs in an isolated child with a fixed official endpoint, an
    empty temporary config path, no inherited Modal/proxy/CA variables, and a
    hard total timeout. Credentials travel over the child's private stdin, not
    command arguments or environment variables.
    """

    verification_available = True

    def __init__(
        self,
        *,
        process_runner: ProcessRunner = subprocess.run,
        python_executable: str = sys.executable,
        timeout_seconds: float = PROTO_MODAL_PROBE_TIMEOUT_SECONDS,
    ) -> None:
        if (
            not isinstance(python_executable, str)
            or not python_executable
            or not os.path.isabs(python_executable)
        ):
            raise ValueError("python_executable must be an absolute path")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._process_runner = process_runner
        self._python_executable = python_executable
        self._timeout_seconds = timeout_seconds

    def probe(self, token_id: str, token_secret: str, environment: str) -> None:
        payload = json.dumps(
            {
                "token_id": _credential(token_id, maximum=500),
                "token_secret": _credential(token_secret, maximum=4_096),
                "environment": _environment(environment),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        try:
            with tempfile.TemporaryDirectory(prefix="genomilab-modal-probe-") as raw:
                working_directory = Path(raw)
                completed = self._process_runner(
                    [
                        self._python_executable,
                        "-I",
                        "-m",
                        PROTO_MODAL_PROBE_WORKER,
                    ],
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_directory,
                    env=_worker_environment(
                        working_directory / "empty-modal-config.toml"
                    ),
                    timeout=self._timeout_seconds,
                    check=False,
                    close_fds=True,
                )
        except subprocess.TimeoutExpired:
            raise ProviderTransportError(EvidenceStatus.TIMEOUT) from None
        except OSError:
            raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE) from None

        status = _worker_status(completed)
        if status is None:
            return
        raise ProviderTransportError(status)


def _credential(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
    return value.strip()


def _environment(value: object) -> str:
    name = _credential(value, maximum=200)
    if any(character.isspace() for character in name):
        raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
    return name


def _worker_environment(config_path: Path) -> dict[str, str]:
    """Build a minimal environment; never inherit endpoint or TLS overrides."""

    environment = {
        "MODAL_CONFIG_PATH": str(config_path),
        "MODAL_LOGLEVEL": "WARNING",
        "MODAL_SERVER_URL": PROTO_MODAL_SERVER_URL,
        "NO_PROXY": "api.modal.com",
        "no_proxy": "api.modal.com",
    }
    for name in ("SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _worker_status(
    completed: subprocess.CompletedProcess[bytes],
) -> EvidenceStatus | None:
    if (
        isinstance(completed.returncode, bool)
        or not isinstance(completed.returncode, int)
        or completed.returncode != 0
        or not isinstance(completed.stdout, bytes)
        or len(completed.stdout) > PROTO_MODAL_MAX_WORKER_RESPONSE_BYTES
    ):
        return EvidenceStatus.SOURCE_UNAVAILABLE
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return EvidenceStatus.SOURCE_UNAVAILABLE
    if not isinstance(payload, Mapping) or set(payload) != {"status"}:
        return EvidenceStatus.SOURCE_UNAVAILABLE
    status = payload.get("status")
    if status == "ready":
        return None
    try:
        resolved = EvidenceStatus(status)
    except (TypeError, ValueError):
        return EvidenceStatus.SOURCE_UNAVAILABLE
    return (
        resolved
        if resolved
        in {
            EvidenceStatus.AUTHENTICATION_FAILED,
            EvidenceStatus.QUOTA_EXCEEDED,
            EvidenceStatus.RATE_LIMITED,
            EvidenceStatus.TIMEOUT,
            EvidenceStatus.NETWORK_ERROR,
            EvidenceStatus.SERVER_ERROR,
            EvidenceStatus.SOURCE_UNAVAILABLE,
            EvidenceStatus.NOT_FOUND,
        }
        else EvidenceStatus.SOURCE_UNAVAILABLE
    )
