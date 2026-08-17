"""One process-owned GenomiLab session for the current MCP host."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import secrets
import threading
from dataclasses import dataclass
from .models import JsonObject
from .paperclip_authorization_config import load_paperclip_authorization_config
from .scientific_executor_config import (
    ESM_SCIENTIFIC_EXECUTOR_ENV,
    PROTO_SCIENTIFIC_EXECUTOR_ENV,
    load_scientific_executor_configuration,
)
from .server import GenomiLabHTTPServer, create_lab_server
from .service import GenomiLabService


PAPERCLIP_AUTHORIZATION_CONFIG_ENV = "GENOMILAB_PAPERCLIP_AUTHORIZATION_CONFIG"
_LOCAL_TRANSPORTS = frozenset({"stdio", "in_process", "cli"})
_HOST_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_CURRENT_TRANSPORT: ContextVar[str] = ContextVar(
    "genomilab_mcp_transport", default="in_process"
)


@dataclass(frozen=True, slots=True)
class AgentHostContext:
    transport: str = "in_process"
    name: str = "local-agent"
    version: str = ""
    agent_session_id: str = ""

    def __post_init__(self) -> None:
        if not self.agent_session_id:
            object.__setattr__(
                self,
                "agent_session_id",
                f"mcp-session-{secrets.token_urlsafe(18)}",
            )

    @property
    def host_id(self) -> str:
        safe = _HOST_NAME_RE.sub("-", self.name.strip()).strip("-") or "agent"
        return f"mcp-{safe.lower()}"

    @property
    def processing_destination(self) -> str:
        label = self.name.strip() or "local agent"
        return f"current MCP host ({label}; host-reported identity)"

    def to_dict(self) -> JsonObject:
        return {
            "transport": self.transport,
            "name": self.name,
            "version": self.version,
            "host_id": self.host_id,
            "agent_session_id": self.agent_session_id,
            "processing_destination": self.processing_destination,
        }


class GenomiLabAgentRuntime:
    """Long-lived service and loopback portal shared by all agent calls."""

    def __init__(self, host: AgentHostContext) -> None:
        if host.transport not in _LOCAL_TRANSPORTS:
            raise RuntimeError(
                "GenomiLab patient operations require a local stdio MCP session."
            )
        paperclip_path = os.environ.get(PAPERCLIP_AUTHORIZATION_CONFIG_ENV)
        paperclip_policy = (
            load_paperclip_authorization_config(paperclip_path)
            if paperclip_path
            else None
        )
        scientific_executors = load_scientific_executor_configuration()
        self.host = host
        self.service = GenomiLabService(
            agent_host_id=host.agent_session_id,
            agent_processing_destination=host.processing_destination,
            paperclip_deployment_authorization=(
                paperclip_policy.deployment_authorization
                if paperclip_policy is not None
                else None
            ),
            paperclip_patient_data_contract=(
                paperclip_policy.patient_data_contract
                if paperclip_policy is not None
                else None
            ),
            esm_scientific_executor=scientific_executors.esm_executor,
            proto_scientific_executor=scientific_executors.proto_executor,
        )
        self._portal: GenomiLabHTTPServer | None = None
        self._portal_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._closed = False

    def open_workspace(self, *, open_portal: bool = True) -> JsonObject:
        workspace = self.service.open_agent_workspace()
        portal: JsonObject = {
            "status": "not_started",
            "role": "patient_onboarding_approval_and_monitoring",
        }
        if workspace.get("status") == "ready" and open_portal:
            portal = self.open_portal()
        return {
            **workspace,
            "agent_host": self.host.to_dict(),
            "portal": portal,
        }

    def open_portal(
        self, *, authorization_handoff: JsonObject | None = None
    ) -> JsonObject:
        with self._lock:
            if self._closed:
                raise RuntimeError("GenomiLab agent runtime is closed")
            if self._portal is None:
                self._portal = create_lab_server(service=self.service)
                self._portal_thread = threading.Thread(
                    target=self._portal.serve_forever,
                    kwargs={"poll_interval": 0.25},
                    name="genomilab-portal",
                    daemon=True,
                )
                self._portal_thread.start()
            launch_url = self._portal.issue_launch_url(
                authorization_handoff=authorization_handoff
            )
            return {
                "status": "ready",
                "role": "patient_onboarding_approval_and_monitoring",
                "base_url": self._portal.base_url,
                "launch_url": launch_url,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            portal = self._portal
            self._portal = None
        if portal is not None:
            portal.shutdown()
            portal.server_close()
        else:
            self.service.close()


_LOCK = threading.RLock()
_HOST = AgentHostContext()
_RUNTIME: GenomiLabAgentRuntime | None = None


def configure_mcp_host(
    client_info: object, *, transport: str
) -> AgentHostContext:
    """Begin one authorization-isolated session at the MCP initialize boundary.

    MCP permits exactly one initialize handshake per protocol session. Treating
    every handshake as a fresh GenomiLab session prevents a later Claude/Codex
    task with the same stable client name from inheriting the prior task's AGI
    handles or patient authorization. Remote transports can initialize public
    MCP tools, but do not own or replace the process-local GenomiLab session.
    """

    global _HOST, _RUNTIME
    payload = client_info if isinstance(client_info, dict) else {}
    name = str(payload.get("name") or "local-agent").strip() or "local-agent"
    version = str(payload.get("version") or "").strip()
    candidate = AgentHostContext(
        transport=str(transport or "in_process"), name=name, version=version
    )
    if candidate.transport not in _LOCAL_TRANSPORTS:
        return candidate
    with _LOCK:
        prior_runtime = _RUNTIME
        _RUNTIME = None
        if prior_runtime is not None:
            prior_runtime.close()
        _HOST = candidate
    return candidate


def current_agent_runtime() -> GenomiLabAgentRuntime:
    global _RUNTIME
    if _CURRENT_TRANSPORT.get() not in _LOCAL_TRANSPORTS:
        raise RuntimeError(
            "GenomiLab patient operations require a local stdio MCP session."
        )
    with _LOCK:
        if _RUNTIME is None:
            _RUNTIME = GenomiLabAgentRuntime(_HOST)
        return _RUNTIME


@contextmanager
def agent_transport_scope(transport: str):
    token = _CURRENT_TRANSPORT.set(str(transport or "in_process"))
    try:
        yield
    finally:
        _CURRENT_TRANSPORT.reset(token)


def close_agent_runtime() -> None:
    global _HOST, _RUNTIME
    with _LOCK:
        runtime = _RUNTIME
        _RUNTIME = None
        _HOST = AgentHostContext()
    if runtime is not None:
        runtime.close()


def reset_agent_runtime_for_tests(
    *, name: str = "local-agent", transport: str = "in_process"
) -> None:
    """Close the process session and select deterministic test host metadata."""

    close_agent_runtime()
    configure_mcp_host({"name": name, "version": "test"}, transport=transport)


atexit.register(close_agent_runtime)


__all__ = [
    "AgentHostContext",
    "ESM_SCIENTIFIC_EXECUTOR_ENV",
    "GenomiLabAgentRuntime",
    "PAPERCLIP_AUTHORIZATION_CONFIG_ENV",
    "PROTO_SCIENTIFIC_EXECUTOR_ENV",
    "agent_transport_scope",
    "close_agent_runtime",
    "configure_mcp_host",
    "current_agent_runtime",
    "reset_agent_runtime_for_tests",
]
