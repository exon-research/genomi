from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from typing import Any, Protocol

JsonObject = dict[str, Any]


class StreamAdapter(Protocol):
    def parse_line(self, line: str) -> "StreamParseOutcome":
        ...


@dataclass(frozen=True)
class StreamParseOutcome:
    kind: str
    events: list[JsonObject]
    stdout: str | None = None


@dataclass(frozen=True)
class AgentDriver:
    id: str
    label: str
    command: str
    summary: str
    invocation_args: tuple[str, ...]
    stream_adapter: StreamAdapter
    runnable: bool = True

    def invocation(self, resolved_command: str | None) -> list[str] | None:
        if not self.runnable or not resolved_command:
            return None
        return [resolved_command, *self.invocation_args]


def detect_agents() -> list[JsonObject]:
    agents: list[JsonObject] = []
    for driver in AGENT_DRIVERS:
        resolved = shutil.which(driver.command)
        runnable = bool(resolved and driver.runnable)
        agents.append(
            {
                "id": driver.id,
                "label": driver.label,
                "command": driver.command,
                "summary": driver.summary,
                "available": resolved is not None,
                "runnable": runnable,
                "status": _driver_status(driver, resolved),
            }
        )
    return agents


def default_agent_id() -> str | None:
    for agent in detect_agents():
        if agent.get("runnable"):
            return str(agent["id"])
    return None


def agent_invocation(agent_id: str, *, approved_tools: list[str] | tuple[str, ...] | None = None) -> list[str] | None:
    driver = driver_for(agent_id)
    if driver is None:
        return None
    invocation = driver.invocation(shutil.which(driver.command))
    if invocation is None:
        return None
    if driver.id == "claude":
        invocation.extend(_clean_approved_tools(approved_tools))
    return invocation


def agent_events_for_line(agent_id: str, line: str) -> list[JsonObject]:
    return parse_agent_line(agent_id, line).events


def parse_agent_line(agent_id: str, line: str) -> StreamParseOutcome:
    driver = driver_for(agent_id)
    adapter = driver.stream_adapter if driver else PlainTextStreamAdapter()
    return adapter.parse_line(line)


def text_or_diagnostic_event(text: str) -> JsonObject:
    return _text_or_diagnostic_event(text)


def driver_for(agent_id: str) -> AgentDriver | None:
    return _AGENT_DRIVER_BY_ID.get(agent_id)


class PlainTextStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        return _events_outcome([{"type": "text_delta", "delta": line}]) if line.strip() else _ignored_structured_event()


class ClaudeStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        payload = _json_line(line)
        if not isinstance(payload, dict):
            return _non_json_outcome(line)
        event_type = str(payload.get("type") or "")
        if "error" in event_type.lower():
            return _events_outcome([_error_event(payload)])
        if event_type == "result":
            result = payload.get("result")
            if isinstance(result, str) and result.strip():
                return _events_outcome([{"type": "text_delta", "delta": result}])
            return _ignored_structured_event()
        events: list[JsonObject] = []
        content_blocks = _claude_content_blocks(payload)
        has_tool_use = any(str(block.get("type") or "") == "tool_use" for block in content_blocks)
        for block in content_blocks:
            block_type = str(block.get("type") or "")
            if block_type == "text" and isinstance(block.get("text"), str):
                events.append(_text_or_diagnostic_event(block["text"]) if has_tool_use else _claude_status_event(block["text"]))
            elif block_type == "tool_use":
                name = _clean_str(block.get("name")) or "tool"
                events.append({"type": "tool_call", "id": _clean_str(block.get("id")), "name": name, "input": block.get("input") or {}})
            elif block_type == "tool_result":
                result_fields = _tool_result_fields(block.get("content"))
                events.append(
                    {
                        "type": "tool_result",
                        "id": _clean_str(block.get("tool_use_id")),
                        "name": None,
                        "isError": bool(block.get("is_error")),
                        **result_fields,
                    }
                )
        return _events_outcome(events)


def _claude_status_event(text: str) -> JsonObject:
    setup_event = _text_or_diagnostic_event(text)
    if setup_event.get("type") == "diagnostic":
        return setup_event
    return {
        "type": "diagnostic",
        "name": "assistant_status",
        "message": _content_preview(text),
    }


class CodexStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        payload = _json_line(line)
        if not isinstance(payload, dict):
            return _non_json_outcome(line)
        event = _codex_event(payload)
        event_type = str(event.get("type") or "")
        if event_type == "agent_message":
            message = event.get("message")
            return _events_outcome([_text_or_diagnostic_event(message)]) if isinstance(message, str) and message else _ignored_structured_event()
        if event_type in {"agent_message_delta", "response.output_text.delta"}:
            delta = event.get("delta")
            return _events_outcome([_text_or_diagnostic_event(delta)]) if isinstance(delta, str) and delta else _ignored_structured_event()
        if event_type == "function_call":
            return _events_outcome([_codex_tool_call(event)])
        if event_type == "function_call_output":
            return _events_outcome([_codex_tool_result(event)])
        if event_type == "item.completed" and isinstance(event.get("item"), dict):
            item = event["item"]
            item_type = str(item.get("type") or "")
            if item_type == "function_call":
                return _events_outcome([_codex_tool_call(item)])
            if item_type == "function_call_output":
                return _events_outcome([_codex_tool_result(item)])
        if "error" in event_type.lower():
            return _events_outcome([_error_event(event)])
        return _ignored_structured_event()


class GeminiStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        payload = _json_line(line)
        if not isinstance(payload, dict):
            return _non_json_outcome(line)
        event_type = str(payload.get("type") or payload.get("event") or "")
        if event_type in {"text", "content", "message"} and isinstance(payload.get("text"), str):
            return _events_outcome([_text_or_diagnostic_event(payload["text"])])
        if event_type == "function_call":
            return _events_outcome(
                [
                    {
                        "type": "tool_call",
                        "id": _clean_str(payload.get("id")),
                        "name": _clean_str(payload.get("function_name")) or "tool",
                        "input": _jsonish(payload.get("arguments")),
                    }
                ]
            )
        if event_type == "function_response":
            result_fields = _tool_result_fields(payload.get("response") if "response" in payload else payload.get("error"))
            return _events_outcome(
                [
                    {
                        "type": "tool_result",
                        "id": _clean_str(payload.get("id")),
                        "name": _clean_str(payload.get("function_name")),
                        "isError": bool(payload.get("error")),
                        **result_fields,
                    }
                ]
            )
        if "error" in event_type.lower():
            return _events_outcome([_error_event(payload)])
        return _ignored_structured_event()


def _events_outcome(events: list[JsonObject]) -> StreamParseOutcome:
    return StreamParseOutcome(kind="events", events=events) if events else _ignored_structured_event()


def _ignored_structured_event() -> StreamParseOutcome:
    return StreamParseOutcome(kind="ignored_structured_event", events=[])


def _non_json_outcome(line: str) -> StreamParseOutcome:
    stripped = line.strip()
    if not stripped:
        return _ignored_structured_event()
    if stripped[0] in "[{":
        return _ignored_structured_event()
    return _events_outcome([text_or_diagnostic_event(line)])


def _text_or_diagnostic_event(text: str) -> JsonObject:
    if _looks_like_host_setup_text(text):
        return {"type": "diagnostic", "name": "host_agent_context_load", "message": _content_preview(text)}
    return {"type": "text_delta", "delta": text}


def _looks_like_host_setup_text(text: str) -> bool:
    stripped = text.strip()
    if "Base directory for this skill:" in stripped:
        return True
    if stripped.startswith("[spawn_agent]"):
        return True
    return False


def _driver_status(driver: AgentDriver, resolved: str | None) -> str:
    if resolved and driver.runnable:
        return "runnable"
    if resolved:
        return "detected_setup_only"
    return "missing"


def _claude_content_blocks(payload: JsonObject) -> list[JsonObject]:
    message = payload.get("message")
    content = message.get("content") if isinstance(message, dict) else payload.get("content")
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _codex_event(payload: JsonObject) -> JsonObject:
    nested = payload.get("payload")
    return nested if payload.get("type") == "response_item" and isinstance(nested, dict) else payload


def _codex_tool_call(event: JsonObject) -> JsonObject:
    return {
        "type": "tool_call",
        "id": _clean_str(event.get("call_id")),
        "name": _clean_str(event.get("name")) or "tool",
        "input": _jsonish(event.get("arguments")),
    }


def _codex_tool_result(event: JsonObject) -> JsonObject:
    result_fields = _tool_result_fields(event.get("output"))
    return {
        "type": "tool_result",
        "id": _clean_str(event.get("call_id")),
        "name": None,
        "isError": False,
        **result_fields,
    }


def _tool_result_fields(value: Any) -> JsonObject:
    payload = _jsonish(value)
    content = _content_preview(value)
    result: JsonObject = {"content": content, "payload": payload}
    permission = permission_request_from_message(content)
    if permission:
        result["permission_request"] = permission
    return result


def _jsonish(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _json_text(value)
        return parsed if parsed is not None else value
    return value if value is not None else {}


def _content_preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:4000]
    return _compact_json(value, limit=4000)


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_line(line: str) -> Any:
    return _json_text(line.strip())


def _json_text(text: str) -> Any:
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _error_event(payload: JsonObject) -> JsonObject:
    message = payload.get("message") or payload.get("error") or _compact_json(payload, limit=1600)
    text = _content_preview(message)
    event: JsonObject = {"type": "error", "message": text}
    permission = permission_request_from_message(text)
    if permission:
        event["name"] = "host_agent_permission_request"
        event["permission_request"] = permission
    return event


def permission_request_from_message(message: str) -> JsonObject | None:
    text = str(message or "").strip()
    if not text:
        return None
    match = re.search(r"requested permissions? to use\s+(.+?)(?:,\s+but\b|\s+but\b|\.|\n|$)", text, flags=re.IGNORECASE)
    tool = _clean_approved_tool(match.group(1)) if match else _file_permission_tool(text)
    if not tool:
        return None
    return {
        "kind": "host_agent_tool",
        "tool": tool,
        "label": _permission_label(tool),
    }


def _file_permission_tool(message: str) -> str:
    if re.search(r"requested permissions? to write to\s+", message, flags=re.IGNORECASE):
        return "Write"
    if re.search(r"requested permissions? to edit\s+", message, flags=re.IGNORECASE):
        return "Edit"
    return ""


def clean_approved_tool(value: Any) -> str:
    return _clean_approved_tool(value)


def _clean_approved_tools(values: list[str] | tuple[str, ...] | None) -> list[str]:
    clean: list[str] = []
    for value in values or []:
        tool = _clean_approved_tool(value)
        if tool and tool not in clean:
            clean.append(tool)
    return clean


def _clean_approved_tool(value: Any) -> str:
    text = str(value or "").strip().strip("`'\"")
    if not text or len(text) > 180:
        return ""
    if any(char in text for char in "\r\n;&|"):
        return ""
    return text


def _permission_label(tool: str) -> str:
    if tool == "WebSearch":
        return "Search the public web"
    if tool == "WebFetch":
        return "Open a public web page"
    if tool == "mcp__genomi__genomi_describe_context":
        return "Read current Genomi context"
    if tool == "mcp__genomi__genomi_parse_source":
        return "Add a genome source"
    if tool == "mcp__genomi__research_build_target_packet":
        return "Build an evidence packet"
    if tool == "mcp__genomi__variant_resolve":
        return "Look up variant evidence"
    if tool.startswith("mcp__genomi__"):
        return "Use GenomiLab workspace tools"
    if tool.startswith("mcp__"):
        return "Use an external connector"
    if tool == "Write":
        return "Create or update project files"
    if tool == "Edit":
        return "Edit project files"
    if tool.startswith("Bash("):
        return "Shell command"
    return tool.split("(", 1)[0] or "Host-agent tool"


def _compact_json(value: Any, *, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except TypeError:
        text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


AGENT_DRIVERS: tuple[AgentDriver, ...] = (
    AgentDriver(
        id="claude",
        label="Claude Code",
        command="claude",
        summary="Best structured stream support; uses the Genomi MCP server installed in Claude Code.",
        invocation_args=(
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--allowedTools",
            "mcp__genomi__*",
        ),
        stream_adapter=ClaudeStreamAdapter(),
    ),
    AgentDriver(
        id="codex",
        label="Codex CLI",
        command="codex",
        summary="Runs `codex exec --json` with Genomi tools available from the host install.",
        invocation_args=("exec", "--json", "--skip-git-repo-check"),
        stream_adapter=CodexStreamAdapter(),
    ),
    AgentDriver(
        id="gemini",
        label="Gemini CLI",
        command="gemini",
        summary="Detected for setup visibility; a runnable GenomiLab driver needs a verified headless JSON stream contract.",
        invocation_args=("--output-format", "stream-json"),
        stream_adapter=GeminiStreamAdapter(),
        runnable=False,
    ),
    AgentDriver(
        id="opencode",
        label="OpenCode",
        command="opencode",
        summary="Detected for setup visibility; a runnable GenomiLab driver needs an explicit invocation and stream contract.",
        invocation_args=(),
        stream_adapter=PlainTextStreamAdapter(),
        runnable=False,
    ),
)
_AGENT_DRIVER_BY_ID = {driver.id: driver for driver in AGENT_DRIVERS}
