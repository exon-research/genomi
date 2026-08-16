from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Protocol

JsonObject = dict[str, Any]

# Set once from `genomi lab --agent` / `genomi serve --agent`. It outranks the
# launching host agent because it is the only signal the person typed on
# purpose, and a workspace's own saved choice still outranks it.
_LAUNCH_AGENT_ID = ""


class StreamAdapter(Protocol):
    def parse_line(self, line: str) -> "StreamParseOutcome":
        ...


@dataclass(frozen=True)
class StreamParseOutcome:
    kind: str
    events: list[JsonObject]
    stdout: str | None = None


StreamAdapterFactory = Callable[..., StreamAdapter]


@dataclass(frozen=True)
class AgentDriver:
    id: str
    label: str
    command: str
    summary: str
    invocation_args: tuple[str, ...]
    stream_adapter_factory: StreamAdapterFactory
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


def bootstrap_agent_id() -> str:
    """The host agent that launched this Genomi process, if it has a driver."""

    from ..runtime import context as runtime_context

    agent_id = runtime_context.bootstrap_agent_id()
    return agent_id if agent_id in _AGENT_DRIVER_BY_ID else ""


def runnable_agent_ids() -> list[str]:
    return [str(agent["id"]) for agent in detect_agents() if agent.get("runnable")]


def set_launch_agent_id(agent_id: str) -> None:
    """Record the assistant named by `--agent` when this portal was started."""

    global _LAUNCH_AGENT_ID
    _LAUNCH_AGENT_ID = str(agent_id or "").strip()


def launch_agent_id() -> str:
    """The assistant `--agent` named at launch, if it has a runnable driver."""

    return _LAUNCH_AGENT_ID if _LAUNCH_AGENT_ID in runnable_agent_ids() else ""


def agent_invocation(agent_id: str, *, approved_tools: list[str] | tuple[str, ...] | None = None) -> list[str] | None:
    driver = driver_for(agent_id)
    if driver is None:
        return None
    invocation = driver.invocation(shutil.which(driver.command))
    if invocation is None:
        return None
    if driver.id == "claude":
        invocation.extend(clean_approved_tools(approved_tools))
    return invocation


def new_stream_adapter(agent_id: str, *, session_id: str = "") -> StreamAdapter:
    """Build one adapter for one run; stateful hosts keep per-run state."""

    driver = driver_for(agent_id)
    factory = driver.stream_adapter_factory if driver else _plain_text_adapter
    return factory(session_id=session_id)


def agent_events_for_line(agent_id: str, line: str) -> list[JsonObject]:
    return parse_agent_line(agent_id, line).events


def parse_agent_line(agent_id: str, line: str) -> StreamParseOutcome:
    return new_stream_adapter(agent_id).parse_line(line)


def driver_for(agent_id: str) -> AgentDriver | None:
    return _AGENT_DRIVER_BY_ID.get(agent_id)


class PlainTextStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        return events_outcome([{"type": "text_delta", "delta": line}]) if line.strip() else ignored_structured_event()


class CodexStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        payload = json_line(line)
        if not isinstance(payload, dict):
            return non_json_outcome(line)
        event = _codex_event(payload)
        event_type = str(event.get("type") or "")
        if event_type == "agent_message":
            message = event.get("message")
            return events_outcome([text_or_diagnostic_event(message)]) if isinstance(message, str) and message else ignored_structured_event()
        if event_type in {"agent_message_delta", "response.output_text.delta"}:
            delta = event.get("delta")
            return events_outcome([text_or_diagnostic_event(delta)]) if isinstance(delta, str) and delta else ignored_structured_event()
        if event_type == "function_call":
            return events_outcome([_codex_tool_call(event)])
        if event_type == "function_call_output":
            return events_outcome([_codex_tool_result(event)])
        if event_type == "item.completed" and isinstance(event.get("item"), dict):
            item = event["item"]
            item_type = str(item.get("type") or "")
            if item_type == "agent_message":
                text = item.get("text")
                return events_outcome([text_or_diagnostic_event(text)]) if isinstance(text, str) and text else ignored_structured_event()
            if item_type == "function_call":
                return events_outcome([_codex_tool_call(item)])
            if item_type == "function_call_output":
                return events_outcome([_codex_tool_result(item)])
        if "error" in event_type.lower():
            return events_outcome([error_event(event)])
        return ignored_structured_event()


class GeminiStreamAdapter:
    def parse_line(self, line: str) -> StreamParseOutcome:
        payload = json_line(line)
        if not isinstance(payload, dict):
            return non_json_outcome(line)
        event_type = str(payload.get("type") or payload.get("event") or "")
        if event_type in {"text", "content", "message"} and isinstance(payload.get("text"), str):
            return events_outcome([text_or_diagnostic_event(payload["text"])])
        if event_type == "function_call":
            return events_outcome(
                [
                    {
                        "type": "tool_call",
                        "id": clean_str(payload.get("id")),
                        "name": clean_str(payload.get("function_name")) or "tool",
                        "input": jsonish(payload.get("arguments")),
                    }
                ]
            )
        if event_type == "function_response":
            result_fields = tool_result_fields(payload.get("response") if "response" in payload else payload.get("error"))
            return events_outcome(
                [
                    {
                        "type": "tool_result",
                        "id": clean_str(payload.get("id")),
                        "name": clean_str(payload.get("function_name")),
                        "isError": bool(payload.get("error")),
                        **result_fields,
                    }
                ]
            )
        if "error" in event_type.lower():
            return events_outcome([error_event(payload)])
        return ignored_structured_event()


def events_outcome(events: list[JsonObject]) -> StreamParseOutcome:
    return StreamParseOutcome(kind="events", events=events) if events else ignored_structured_event()


def ignored_structured_event() -> StreamParseOutcome:
    return StreamParseOutcome(kind="ignored_structured_event", events=[])


def non_json_outcome(line: str) -> StreamParseOutcome:
    stripped = line.strip()
    if not stripped:
        return ignored_structured_event()
    if stripped[0] in "[{":
        return ignored_structured_event()
    return events_outcome([text_or_diagnostic_event(line)])


def text_or_diagnostic_event(text: str) -> JsonObject:
    if _looks_like_host_setup_text(text):
        return {"type": "diagnostic", "name": "host_agent_context_load", "message": content_preview(text)}
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


def _codex_event(payload: JsonObject) -> JsonObject:
    nested = payload.get("payload")
    return nested if payload.get("type") == "response_item" and isinstance(nested, dict) else payload


def _codex_tool_call(event: JsonObject) -> JsonObject:
    return {
        "type": "tool_call",
        "id": clean_str(event.get("call_id")),
        "name": clean_str(event.get("name")) or "tool",
        "input": jsonish(event.get("arguments")),
    }


def _codex_tool_result(event: JsonObject) -> JsonObject:
    result_fields = tool_result_fields(event.get("output"))
    return {
        "type": "tool_result",
        "id": clean_str(event.get("call_id")),
        "name": None,
        "isError": False,
        **result_fields,
    }


def tool_result_fields(value: Any) -> JsonObject:
    payload = jsonish(value)
    content = content_preview(value)
    result: JsonObject = {"content": content, "payload": payload}
    permission = permission_request_from_message(content)
    if permission:
        result["permission_request"] = permission
    return result


def jsonish(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _json_text(value)
        return parsed if parsed is not None else value
    return value if value is not None else {}


def content_preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:4000]
    return _compact_json(value, limit=4000)


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def json_line(line: str) -> Any:
    return _json_text(line.strip())


def _json_text(text: str) -> Any:
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def error_event(payload: JsonObject) -> JsonObject:
    message = payload.get("message") or payload.get("error") or _compact_json(payload, limit=1600)
    text = content_preview(message)
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
    tool = clean_approved_tool(match.group(1)) if match else _file_permission_tool(text)
    if not tool:
        return None
    return {
        "kind": "host_agent_tool",
        "tool": tool,
        "label": permission_label(tool),
    }


def _file_permission_tool(message: str) -> str:
    if re.search(r"requested permissions? to write to\s+", message, flags=re.IGNORECASE):
        return "Write"
    if re.search(r"requested permissions? to edit\s+", message, flags=re.IGNORECASE):
        return "Edit"
    return ""


def clean_approved_tools(values: list[str] | tuple[str, ...] | None) -> list[str]:
    clean: list[str] = []
    for value in values or []:
        tool = clean_approved_tool(value)
        if tool and tool not in clean:
            clean.append(tool)
    return clean


def clean_approved_tool(value: Any) -> str:
    text = str(value or "").strip().strip("`'\"")
    if not text or len(text) > 180:
        return ""
    if any(char in text for char in "\r\n;&|"):
        return ""
    return text


def permission_label(tool: str) -> str:
    if tool == "WebSearch":
        return "Search the public web"
    if tool == "WebFetch":
        return "Open a public web page"
    if tool == "mcp__genomi__genomi_describe_context":
        return "Read current Genomi context"
    if tool == "mcp__genomi__genomi_parse_source":
        return "Add a genome"
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
    if tool == "Bash" or tool.startswith("Bash("):
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


def _plain_text_adapter(**_options: Any) -> StreamAdapter:
    return PlainTextStreamAdapter()


def _codex_adapter(**_options: Any) -> StreamAdapter:
    return CodexStreamAdapter()


def _gemini_adapter(**_options: Any) -> StreamAdapter:
    return GeminiStreamAdapter()


def _claude_adapter(**options: Any) -> StreamAdapter:
    # Imported at call time so the Claude session module can use these generic
    # stream helpers without an import cycle.
    from .portal_claude_stream import ClaudeStreamSession

    return ClaudeStreamSession(session_id=str(options.get("session_id") or ""))


AGENT_DRIVERS: tuple[AgentDriver, ...] = (
    AgentDriver(
        id="codex",
        label="Codex CLI",
        command="codex",
        summary="Runs `codex exec --json` with Genomi tools available from the host install.",
        invocation_args=("exec", "--json", "--skip-git-repo-check"),
        stream_adapter_factory=_codex_adapter,
    ),
    AgentDriver(
        id="claude",
        label="Claude Code",
        command="claude",
        summary=(
            "Runs `claude -p --output-format stream-json` bound to this portal's Genomi "
            "MCP server and GenomiLab specialist policies, reporting denied tools instead "
            "of bypassing permissions."
        ),
        invocation_args=(
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # Subagent text is not streamed without this, so the specialist lane
            # and provider-receipt binding would have nothing to observe.
            "--forward-subagent-text",
            # Deny-and-report rather than silently proceeding; the portal
            # surfaces the denial and retries with approved tools.
            "--permission-mode",
            "dontAsk",
            # Must stay last: --allowedTools is variadic and absorbs the
            # approved-tool retry list appended by agent_invocation.
            "--allowedTools",
            "mcp__genomi__*",
            # Permission name of the subagent tool that streams as `Agent`.
            "Task",
            # People hand Genomi their records by pointing at them in the
            # conversation, and capability guidance lives in skill files. With
            # no setting sources loaded, denying Read leaves the orchestrator
            # unable to open the very records it was given.
            "Read",
            "Glob",
        ),
        stream_adapter_factory=_claude_adapter,
    ),
    AgentDriver(
        id="gemini",
        label="Gemini CLI",
        command="gemini",
        summary="Detected for setup visibility; a runnable GenomiLab driver needs a verified headless JSON stream contract.",
        invocation_args=("--output-format", "stream-json"),
        stream_adapter_factory=_gemini_adapter,
        runnable=False,
    ),
    AgentDriver(
        id="opencode",
        label="OpenCode",
        command="opencode",
        summary="Detected for setup visibility; a runnable GenomiLab driver needs an explicit invocation and stream contract.",
        invocation_args=(),
        stream_adapter_factory=_plain_text_adapter,
        runnable=False,
    ),
)
_AGENT_DRIVER_BY_ID = {driver.id: driver for driver in AGENT_DRIVERS}
