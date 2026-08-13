"""Codex app-server transport, session, and turn collection."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from .harness_adapter import (
    HarnessDynamicToolCall, HostInvocationUnavailable, HostTraceEvent,
)
from .harness_transport import PROTOCOL_VERSION, safe_json_dumps
from .harness_types import HarnessCommand, HarnessEventKind, HarnessEventStatus


class _CollectorAdapter(Protocol):
    def _observe_background_protocol_message(
        self, command: HarnessCommand, message: Mapping[str, Any]
    ) -> bool: ...
    def _note_background_turn_completed(
        self, command: HarnessCommand, thread_id: str, turn_id: str, status: str
    ) -> None: ...
    def _send_app_server_error(self, request_id: object, message: str) -> None: ...
    def _send_dynamic_tool_result(
        self, request_id: object, result: Mapping[str, Any], *, success: bool
    ) -> None: ...
    def _invoke_dynamic_tool_handler(
        self, call: HarnessDynamicToolCall
    ) -> Mapping[str, Any]: ...
    def _publish_background_trace(
        self, command: HarnessCommand, trace: HostTraceEvent
    ) -> bool: ...


class _JsonLineTransport(Protocol):
    def send(self, message: Mapping[str, Any]) -> None: ...

    def receive(self, timeout_seconds: float) -> dict[str, Any]: ...

    def close(self) -> None: ...


TransportFactory = Callable[[list[str], Mapping[str, str], int], _JsonLineTransport]


class _StdioJsonLineTransport:
    """One restricted app-server process speaking newline-delimited JSON-RPC."""

    def __init__(
        self, command: list[str], environment: Mapping[str, str], timeout_seconds: int
    ) -> None:
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=dict(environment),
        )
        self._timeout_seconds = timeout_seconds
        self._messages: queue.Queue[str | BaseException | None] = queue.Queue()
        self._stderr: list[str] = []
        self._send_lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        try:
            assert self._process.stdout is not None
            for line in self._process.stdout:
                self._messages.put(line)
        except BaseException as exc:  # pragma: no cover - OS pipe failure
            self._messages.put(exc)
        finally:
            self._messages.put(None)

    def _read_stderr(self) -> None:
        try:
            assert self._process.stderr is not None
            for line in self._process.stderr:
                self._stderr.append(line.rstrip())
                if len(self._stderr) > 50:
                    del self._stderr[:-50]
        except OSError:  # pragma: no cover - process teardown race
            return

    def send(self, message: Mapping[str, Any]) -> None:
        with self._send_lock:
            if self._process.poll() is not None or self._process.stdin is None:
                raise subprocess.SubprocessError("Codex app-server is not running")
            self._process.stdin.write(safe_json_dumps(message) + "\n")
            self._process.stdin.flush()

    def receive(self, timeout_seconds: float) -> dict[str, Any]:
        try:
            item = self._messages.get(timeout=max(0.01, timeout_seconds))
        except queue.Empty as exc:
            raise subprocess.TimeoutExpired(
                self._process.args, timeout_seconds
            ) from exc
        if isinstance(item, BaseException):
            raise subprocess.SubprocessError("Codex app-server stdout failed") from item
        if item is None:
            detail = "\n".join(self._stderr[-10:])
            raise subprocess.SubprocessError(
                "Codex app-server closed its protocol stream"
                + (f": {detail}" if detail else "")
            )
        try:
            message = json.loads(item)
        except json.JSONDecodeError as exc:
            raise subprocess.SubprocessError(
                "Codex app-server returned a non-JSON protocol message"
            ) from exc
        if not isinstance(message, dict):
            raise subprocess.SubprocessError(
                "Codex app-server protocol message must be an object"
            )
        return message

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:  # pragma: no cover - exceptional host
                    self._process.kill()
                    self._process.wait(timeout=2)
        finally:
            for stream in (self._process.stdout, self._process.stderr):
                if stream is None:
                    continue
                try:
                    stream.close()
                except OSError:
                    pass


class _AppServerSession:
    def __init__(self, transport: _JsonLineTransport, timeout_seconds: int) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self._next_request_id = 1
        self._request_lock = threading.Lock()

    def send_request(self, method: str, params: Mapping[str, Any]) -> int:
        """Send a request whose response will be consumed by the event loop."""

        with self._request_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            self.transport.send({"method": method, "id": request_id, "params": params})
        return request_id

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        request_id = self.send_request(method, params)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            message = self.transport.receive(deadline - time.monotonic())
            if message.get("id") == request_id and (
                "result" in message or "error" in message
            ):
                if "error" in message:
                    raise subprocess.SubprocessError(
                        f"Codex app-server rejected {method}"
                    )
                result = message.get("result")
                if not isinstance(result, Mapping):
                    raise ValueError(
                        f"Codex app-server {method} result must be an object"
                    )
                return result
            if observer is not None:
                observer(message)

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "genomilab",
                    "title": "GenomiLab",
                    "version": PROTOCOL_VERSION,
                },
                "capabilities": {
                    "experimentalApi": True,
                    "requestAttestation": False,
                    "mcpServerOpenaiFormElicitation": False,
                },
            },
        )
        self.transport.send({"method": "initialized"})


@dataclass(slots=True)
class _TurnCollector:
    adapter: _CollectorAdapter
    command: HarnessCommand
    capability_by_tool: Mapping[str, str]
    current_catalog: Mapping[str, Any]
    thread_id: str
    turn_id: str | None = None
    completed: bool = False
    failed: bool = False
    final_message: str | None = None
    traces: list[HostTraceEvent] | None = None
    dynamic_call_results: list[dict[str, str]] | None = None
    _seen: set[tuple[str, str, str]] | None = None

    def __post_init__(self) -> None:
        self.traces = []
        self.dynamic_call_results = []
        self._seen = set()

    def observe(self, message: dict[str, Any]) -> None:
        if self.adapter._observe_background_protocol_message(self.command, message):
            return
        method = message.get("method")
        if isinstance(method, str) and "id" in message:
            self._handle_server_request(message)
            return
        params = message.get("params")
        if not isinstance(params, Mapping):
            return
        if method in {"item/started", "item/completed"}:
            item = params.get("item")
            if isinstance(item, Mapping):
                self._observe_item(item, completed=method == "item/completed")
            return
        if method == "turn/completed" and params.get("threadId") == self.thread_id:
            turn = params.get("turn")
            if not isinstance(turn, Mapping):
                self.failed = True
                self.completed = True
                return
            turn_id = turn.get("id")
            if isinstance(turn_id, str):
                self.turn_id = turn_id
            for item in turn.get("items") or []:
                if isinstance(item, Mapping):
                    self._observe_item(item, completed=True)
            turn_status = str(turn.get("status") or "failed")
            self.adapter._note_background_turn_completed(
                self.command, self.thread_id, str(self.turn_id or ""), turn_status
            )
            self.failed = turn_status != "completed"
            self.completed = True

    def _handle_server_request(self, message: Mapping[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if method != "item/tool/call":
            self.adapter._send_app_server_error(
                request_id,
                "This restricted harness accepts only typed GenomiLab dynamic tools.",
            )
            return
        params = message.get("params")
        if not isinstance(params, Mapping):
            self.adapter._send_app_server_error(
                request_id, "Invalid dynamic tool call."
            )
            return
        call_id = str(params.get("callId") or "")
        tool = str(params.get("tool") or "")
        namespace = params.get("namespace")
        arguments = params.get("arguments")
        capability = self.capability_by_tool.get(tool)
        entry = self.current_catalog.get(capability or "")
        valid_entry = isinstance(entry, Mapping) and entry.get("available") is True
        valid_arguments = (
            isinstance(arguments, Mapping)
            and set(arguments) == {"request_id"}
            and isinstance(arguments.get("request_id"), str)
            and bool(str(arguments.get("request_id")).strip())
        )
        valid_identity = params.get("threadId") == self.thread_id and (
            self.turn_id is None or params.get("turnId") == self.turn_id
        )
        if (
            namespace != "genomilab"
            or not capability
            or not valid_entry
            or not valid_arguments
            or not valid_identity
            or not call_id
        ):
            self.adapter._send_dynamic_tool_result(
                request_id,
                {
                    "status": "capability_request_rejected",
                    "message": "The tool call is not in the exact approved GenomiLab capability catalog.",
                },
                success=False,
            )
            return
        request_id_value = str(arguments["request_id"]).strip()
        try:
            result = self.adapter._invoke_dynamic_tool_handler(
                HarnessDynamicToolCall(
                    command_id=self.command.command_id,
                    investigation_id=self.command.investigation_id,
                    thread_id=self.thread_id,
                    turn_id=str(params.get("turnId") or self.turn_id or "unknown-turn"),
                    call_id=call_id,
                    capability=capability,
                    request_id=request_id_value,
                )
            )
            self.adapter._send_dynamic_tool_result(request_id, result, success=True)
            result_status = str(result.get("status") or "completed")
            assert self.dynamic_call_results is not None
            self.dynamic_call_results.append(
                {
                    "request_id": request_id_value,
                    "capability": capability,
                    "status": result_status,
                }
            )
            trace_kind = (
                HarnessEventKind.APPROVAL_REQUIRED
                if result_status == "approval_required"
                else HarnessEventKind.EVIDENCE_RETURNED
            )
            trace_status = (
                HarnessEventStatus.WAITING
                if result_status == "approval_required"
                else HarnessEventStatus.COMPLETED
            )
            self._append_trace_once(
                ("dynamic_tool", call_id, request_id_value),
                HostTraceEvent(
                    trace_kind,
                    trace_status,
                    {
                        "call_id": call_id,
                        "capability": capability,
                        "request_id": request_id_value,
                        "result_status": result_status,
                    },
                ),
            )
        except (HostInvocationUnavailable, ValueError):
            self.adapter._send_dynamic_tool_result(
                request_id,
                {
                    "status": "capability_request_rejected",
                    "message": "GenomiLab rejected this dynamic capability request.",
                },
                success=False,
            )

    def _observe_item(self, item: Mapping[str, Any], *, completed: bool) -> None:
        item_type = item.get("type")
        if item_type == "agentMessage" and completed:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                self.final_message = text
            return
        if item_type == "collabAgentToolCall":
            self._observe_collaboration_call(item)
            return
        if item_type == "subAgentActivity":
            self._observe_subagent_activity(item)

    def _append_trace_once(
        self, key: tuple[str, str, str], trace: HostTraceEvent
    ) -> None:
        assert self._seen is not None and self.traces is not None
        if key in self._seen:
            return
        self._seen.add(key)
        if not self.adapter._publish_background_trace(self.command, trace):
            self.traces.append(trace)

    def _observe_collaboration_call(self, item: Mapping[str, Any]) -> None:
        item_id = str(item.get("id") or "collaboration")
        tool = str(item.get("tool") or "")
        status = str(item.get("status") or "")
        receivers = [
            str(value)
            for value in item.get("receiverThreadIds") or []
            if isinstance(value, str) and value.strip()
        ]
        if tool == "spawnAgent" and receivers and status != "failed":
            for agent_id in receivers:
                self._append_trace_once(
                    ("agent_started", item_id, agent_id),
                    HostTraceEvent(
                        HarnessEventKind.AGENT_STARTED,
                        HarnessEventStatus.RUNNING,
                        {
                            "agent_id": agent_id,
                            "role": "delegated_research_agent",
                            "assigned_step_id": "harness_reasoning",
                        },
                    ),
                )
        if status in {"completed", "failed"}:
            for agent_id in receivers or [str(item.get("senderThreadId") or item_id)]:
                self._append_trace_once(
                    ("agent_progress", item_id, agent_id),
                    HostTraceEvent(
                        HarnessEventKind.AGENT_PROGRESS,
                        HarnessEventStatus.RUNNING,
                        {
                            "agent_id": agent_id,
                            "assigned_step_id": "harness_reasoning",
                            "progress": (
                                "The installed harness reported delegated reasoning completed."
                                if status == "completed"
                                else "The installed harness reported delegated reasoning failed."
                            ),
                        },
                    ),
                )

    def _observe_subagent_activity(self, item: Mapping[str, Any]) -> None:
        item_id = str(item.get("id") or "subagent-activity")
        agent_id = str(item.get("agentThreadId") or "")
        activity = str(item.get("kind") or "")
        if not agent_id:
            return
        if activity == "started":
            self._append_trace_once(
                ("subagent_started", item_id, agent_id),
                HostTraceEvent(
                    HarnessEventKind.AGENT_STARTED,
                    HarnessEventStatus.RUNNING,
                    {
                        "agent_id": agent_id,
                        "role": "delegated_research_agent",
                        "assigned_step_id": "harness_reasoning",
                    },
                ),
            )
        elif activity in {"interacted", "interrupted"}:
            self._append_trace_once(
                (f"subagent_{activity}", item_id, agent_id),
                HostTraceEvent(
                    HarnessEventKind.AGENT_PROGRESS,
                    HarnessEventStatus.RUNNING,
                    {
                        "agent_id": agent_id,
                        "assigned_step_id": "harness_reasoning",
                        "progress": f"The installed harness reported subagent activity: {activity}.",
                    },
                ),
            )
