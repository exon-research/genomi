from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

JsonObject = dict[str, Any]
EventHandler = Callable[[JsonObject], None]


class CodexAppServerUnavailable(RuntimeError):
    """The app-server could not start a turn, so exec fallback remains safe."""


class CodexAppServerError(RuntimeError):
    """The app-server failed after accepting a turn; retrying would duplicate it."""


@dataclass
class CodexAppServerSession:
    stdin: TextIO
    stdout: TextIO
    on_event: EventHandler
    _next_request_id: int = 1
    _turn_started: bool = False
    _turn_submitted: bool = False
    _turn_completed: bool = False
    _turn_error: str | None = None
    _root_thread_id: str = ""
    _message_deltas: dict[str, str] = field(default_factory=dict)
    _specialists_by_thread_id: dict[str, JsonObject] = field(default_factory=dict)
    _specialist_final_messages: dict[str, str] = field(default_factory=dict)
    _completed_specialist_threads: set[str] = field(default_factory=set)
    _write_lock: threading.Lock = field(default_factory=threading.Lock)

    def run(
        self,
        *,
        prompt: str,
        cwd: str,
        genomi_mcp_server: JsonObject | None = None,
    ) -> None:
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "genomi-portal",
                    "title": "Genomi Web UI",
                    "version": "1",
                }
            },
        )
        self._notify("initialized")
        thread_params: JsonObject = {
            "cwd": cwd,
            "ephemeral": True,
            "approvalPolicy": "on-request",
            "sandbox": "workspace-write",
        }
        if genomi_mcp_server:
            thread_params["config"] = {
                "mcp_servers": {"genomi": genomi_mcp_server}
            }
        thread_result = self._request(
            "thread/start",
            thread_params,
        )
        thread = thread_result.get("thread")
        thread_id = str(thread.get("id") or "") if isinstance(thread, dict) else ""
        if not thread_id:
            raise CodexAppServerUnavailable("Codex app-server returned no thread id")
        self._root_thread_id = thread_id
        self._turn_submitted = True
        turn_result = self._request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]},
        )
        turn = turn_result.get("turn")
        if not isinstance(turn, dict) or not str(turn.get("id") or ""):
            raise CodexAppServerError("Codex app-server returned no accepted turn")
        self._turn_started = True
        while not self._turn_completed:
            self._read_message()
        if self._turn_error:
            raise CodexAppServerError(self._turn_error)

    def _request(self, method: str, params: JsonObject) -> JsonObject:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        while True:
            message = self._read_message()
            if message.get("method"):
                continue
            if message.get("id") != request_id:
                continue
            error = message.get("error")
            if error is not None:
                detail = _preview(error)
                error_type = CodexAppServerError if self._turn_started else CodexAppServerUnavailable
                raise error_type(f"Codex app-server {method} failed: {detail}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def _notify(self, method: str) -> None:
        self._write({"method": method})

    def _write(self, message: JsonObject) -> None:
        try:
            with self._write_lock:
                self.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                self.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            error_type = CodexAppServerError if self._turn_submitted else CodexAppServerUnavailable
            raise error_type(f"Codex app-server input closed: {exc}") from exc

    def _read_message(self) -> JsonObject:
        line = self.stdout.readline()
        if not line:
            error_type = CodexAppServerError if self._turn_submitted else CodexAppServerUnavailable
            raise error_type("Codex app-server stream closed unexpectedly")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return {}
        if not isinstance(message, dict):
            return {}
        method = str(message.get("method") or "")
        params = message.get("params")
        if method and isinstance(params, dict):
            if "id" in message:
                self._handle_server_request(message.get("id"), method, params)
            else:
                self._handle_notification(method, params)
        return message

    def _handle_server_request(self, request_id: Any, method: str, params: JsonObject) -> None:
        metadata = params.get("_meta")
        requested_schema = params.get("requestedSchema")
        if (
            method == "mcpServer/elicitation/request"
            and params.get("serverName") == "genomi"
            and params.get("mode") == "form"
            and isinstance(metadata, dict)
            and metadata.get("codex_approval_kind") == "mcp_tool_call"
            and isinstance(metadata.get("tool_params"), dict)
            and requested_schema == {"type": "object", "properties": {}}
        ):
            self._write({"id": request_id, "result": {"action": "accept", "content": {}}})
            return

        approval_tools = {
            "item/commandExecution/requestApproval": ("Bash", "Run a command"),
            "item/fileChange/requestApproval": ("Write", "Create or update project files"),
            "execCommandApproval": ("Bash", "Run a command"),
            "applyPatchApproval": ("Write", "Create or update project files"),
        }
        approval = approval_tools.get(method)
        if approval:
            tool, label = approval
            self.on_event(
                {
                    "type": "error",
                    "name": "host_agent_permission_request",
                    "message": f"Codex requested permission to {label.lower()}.",
                    "permission_request": {
                        "kind": "host_agent_tool",
                        "tool": tool,
                        "label": label,
                    },
                }
            )
            decision = "denied" if method in {"execCommandApproval", "applyPatchApproval"} else "decline"
            self._write({"id": request_id, "result": {"decision": decision}})
            return
        if method in {"item/tool/requestUserInput", "mcpServer/elicitation/request"}:
            self.on_event(
                {
                    "type": "error",
                    "name": "host_agent_permission_request",
                    "message": "Codex requested additional user input.",
                    "permission_request": {
                        "kind": "host_agent_tool",
                        "tool": "AskUserQuestion",
                        "label": "Answer a Codex follow-up",
                    },
                }
            )
        self._write(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Genomi portal does not implement server request {method}",
                },
            }
        )

    def _handle_notification(self, method: str, params: JsonObject) -> None:
        thread_id = str(params.get("threadId") or "")
        if method == "item/agentMessage/delta":
            item_id = str(params.get("itemId") or "")
            delta = params.get("delta")
            if isinstance(delta, str) and delta:
                self._message_deltas[item_id] = self._message_deltas.get(item_id, "") + delta
                if self._is_root_notification(thread_id):
                    self.on_event({"type": "text_delta", "delta": delta})
            return
        if method in {"item/started", "item/completed"}:
            item = params.get("item")
            if isinstance(item, dict):
                completed = method == "item/completed"
                if not self._is_root_notification(thread_id):
                    self._remember_specialist_message(thread_id, item, completed=completed)
                    return
                if str(item.get("type") or "") == "subAgentActivity":
                    events = self._specialist_activity_events(item, completed=completed)
                else:
                    events = self._item_events(item, completed=completed)
                for event in events:
                    self.on_event(event)
            return
        if method == "turn/completed":
            if not self._is_root_notification(thread_id):
                self._complete_specialist(thread_id, params.get("turn"))
                return
            turn = params.get("turn")
            if isinstance(turn, dict):
                status = str(turn.get("status") or "")
                if status == "failed":
                    self._turn_error = _preview(turn.get("error")) or "Codex turn failed"
                elif status == "interrupted":
                    self._turn_error = "Codex turn was interrupted"
            self._turn_completed = True

    def _is_root_notification(self, thread_id: str) -> bool:
        return not thread_id or not self._root_thread_id or thread_id == self._root_thread_id

    def _specialist_activity_events(
        self,
        item: JsonObject,
        *,
        completed: bool,
    ) -> list[JsonObject]:
        # Codex app-server represents a native specialist launch as a
        # subAgentActivity on the parent thread. Its immediate item/completed
        # only completes the launch notification; the child thread's own
        # turn/completed is the specialist's terminal boundary.
        if completed:
            return []
        child_thread_id = str(item.get("agentThreadId") or "")
        if not child_thread_id:
            return []
        item_id = str(item.get("id") or child_thread_id)
        agent_path = str(item.get("agentPath") or child_thread_id)
        self._specialists_by_thread_id[child_thread_id] = {
            "call_id": item_id,
            "agent_id": agent_path,
            "task_name": agent_path,
        }
        return [
            {
                "type": "tool_call",
                "id": item_id,
                "name": "spawn_agent",
                "input": {
                    "agent_id": agent_path,
                    "task_name": agent_path,
                    "receiverThreadIds": [child_thread_id],
                },
            }
        ]

    def _remember_specialist_message(
        self,
        thread_id: str,
        item: JsonObject,
        *,
        completed: bool,
    ) -> None:
        if not completed or str(item.get("type") or "") != "agentMessage":
            return
        text = item.get("text")
        if isinstance(text, str) and text:
            self._specialist_final_messages[thread_id] = text

    def _complete_specialist(self, thread_id: str, turn_value: Any) -> None:
        if not thread_id or thread_id in self._completed_specialist_threads:
            return
        specialist = self._specialists_by_thread_id.get(thread_id)
        if not specialist:
            return
        turn = turn_value if isinstance(turn_value, dict) else {}
        status = str(turn.get("status") or "failed")
        succeeded = status == "completed"
        message = self._specialist_final_messages.get(thread_id, "")
        if not message:
            for item in reversed(turn.get("items") or []):
                if not isinstance(item, dict) or str(item.get("type") or "") != "agentMessage":
                    continue
                text = item.get("text")
                if isinstance(text, str) and text:
                    message = text
                    break
        agent_id = str(specialist.get("agent_id") or thread_id)
        update: JsonObject = {
            "agent_id": agent_id,
            "task_name": str(specialist.get("task_name") or agent_id),
            "status": "completed" if succeeded else "failed",
        }
        if message:
            update["message"] = message
        output: JsonObject = {
            "status": "completed" if succeeded else "failed",
            "updates": [update],
            "receiverThreadIds": [thread_id],
            "agentsStates": {agent_id: update},
        }
        self.on_event(
            {
                "type": "tool_result",
                "id": str(specialist.get("call_id") or thread_id),
                "name": "spawn_agent",
                "isError": not succeeded,
                "content": _preview(output),
                "payload": output,
            }
        )
        self._completed_specialist_threads.add(thread_id)

    def _item_events(self, item: JsonObject, *, completed: bool) -> list[JsonObject]:
        item_type = str(item.get("type") or "")
        item_id = str(item.get("id") or "")
        if item_type == "agentMessage" and completed:
            text = item.get("text")
            streamed = self._message_deltas.get(item_id, "")
            if isinstance(text, str) and text and not streamed:
                return [{"type": "text_delta", "delta": text}]
            if isinstance(text, str) and streamed and text.startswith(streamed):
                suffix = text[len(streamed) :]
                return [{"type": "text_delta", "delta": suffix}] if suffix else []
            return []
        tool = _tool_item(item)
        if tool is None:
            return []
        name, tool_input, output = tool
        if not completed:
            return [{"type": "tool_call", "id": item_id, "name": name, "input": tool_input}]
        failed = str(item.get("status") or "") == "failed" or item.get("success") is False
        return [
            {
                "type": "tool_result",
                "id": item_id,
                "name": name,
                "isError": failed,
                "content": _preview(output),
                # Keep the structured app-server item result available to the
                # portal projection layer.  The normal public-event boundary
                # sanitizes this value before it reaches the browser.
                "payload": output,
            }
        ]


_COLLAB_TOOL_NAMES = {
    "spawnAgent": "spawn_agent",
    "sendInput": "send_message",
    "resumeAgent": "followup_task",
    "wait": "wait_agent",
    "closeAgent": "interrupt_agent",
}


def _tool_item(item: JsonObject) -> tuple[str, JsonObject, Any] | None:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return "exec_command", {"cmd": item.get("command") or ""}, item.get("aggregatedOutput") or ""
    if item_type == "mcpToolCall":
        server = str(item.get("server") or "mcp")
        tool = str(item.get("tool") or "tool")
        output = item.get("result") if item.get("error") is None else item.get("error")
        return f"{server}.{tool}", _object(item.get("arguments")), output
    if item_type == "dynamicToolCall":
        namespace = str(item.get("namespace") or "dynamic")
        tool = str(item.get("tool") or "tool")
        arguments = _object(item.get("arguments"))
        if tool.lower() == "task" and (
            arguments.get("subagent_type") or arguments.get("description")
        ):
            task_name = str(arguments.get("description") or "Research specialist")
            tool_input: JsonObject = {
                "task_name": task_name,
                "message": str(arguments.get("prompt") or task_name),
            }
            agent_id = _task_agent_id(item.get("contentItems"))
            output: JsonObject = {
                "updates": ([{"agent_id": agent_id, "status": "completed"}] if agent_id else []),
            }
            return "spawn_agent", tool_input, output
        return f"{namespace}.{tool}", arguments, item.get("contentItems") or []
    if item_type == "collabAgentToolCall":
        raw_name = str(item.get("tool") or "collaboration")
        receiver_ids = item.get("receiverThreadIds") or []
        tool_input = {
            key: item[key]
            for key in ("prompt", "receiverThreadIds", "model", "reasoningEffort", "agentsStates")
            if item.get(key) not in (None, [], {})
        }
        if item.get("prompt"):
            tool_input["message"] = item["prompt"]
        if receiver_ids:
            tool_input["agent_id"] = receiver_ids[0]
        agents_states = item.get("agentsStates") if isinstance(item.get("agentsStates"), dict) else {}
        updates = [
            {
                "agent_id": agent_id,
                "status": state.get("status"),
                **({"message": state["message"]} if state.get("message") else {}),
            }
            for agent_id, state in agents_states.items()
            if isinstance(state, dict)
        ]
        return _COLLAB_TOOL_NAMES.get(raw_name, raw_name), tool_input, {
            "status": item.get("status"),
            "updates": updates,
            "receiverThreadIds": receiver_ids,
            "agentsStates": agents_states,
        }
    return None


def _object(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {"value": value} if value is not None else {}


def _preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:4000]
    return json.dumps(value, ensure_ascii=False, default=str)[:4000]


def _task_agent_id(value: Any) -> str:
    match = re.search(r"agentId:\s*([A-Za-z0-9_-]+)", _preview(value))
    return match.group(1) if match else ""
