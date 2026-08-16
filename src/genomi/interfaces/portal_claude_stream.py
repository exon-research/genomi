"""Per-run adapter for the Claude Code stream-json host contract.

Claude Code streams one JSON object per stdout line.  Orchestrator work and
native specialist work share that stream and are separated only by
``parent_tool_use_id``.  This session keeps the per-run specialist state that
makes GenomiLab's portal contract work on Claude: specialist lane isolation,
fixed execution-policy enforcement, and provider-receipt authorization.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from ..lab.specialist_policies import policy_manifest
from ..operations.registry.evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
    EvidenceResultReceiptError,
)
from . import portal_agents
from .portal_claude_runtime import GENOMI_INVOKE_TOOL

JsonObject = dict[str, Any]

SPECIALIST_SPAWN_TOOL = "Agent"
LAB_ASSIGNMENT_OPERATIONS = frozenset(
    {
        "lab.create_specialist_assignment",
        "lab.read_investigation",
        "lab.transition_specialist_assignment",
    }
)
_ASSIGNMENT_STATES = frozenset(
    {"proposed", "spawned", "completed", "failed", "cancelled"}
)
_RESULT_RECEIPT_PATTERN = re.compile(r"result-receipt-[A-Za-z0-9_-]{24,128}")


class ClaudeStreamSession:
    """Translate one Claude Code run into the portal's host-agent events."""

    def __init__(self, *, session_id: str = "") -> None:
        self.session_id = str(session_id or "")
        self._specialists: dict[str, JsonObject] = {}
        self._call_id_by_task_id: dict[str, str] = {}
        self._assignments: dict[str, JsonObject] = {}
        self._pending_operations: dict[str, str] = {}
        self._violated_call_ids: set[str] = set()
        self._completed_call_ids: set[str] = set()

    def parse_line(self, line: str) -> portal_agents.StreamParseOutcome:
        payload = portal_agents.json_line(line)
        if not isinstance(payload, dict):
            return portal_agents.non_json_outcome(line)
        event_type = str(payload.get("type") or "")
        if event_type == "system":
            return portal_agents.events_outcome(self._system_events(payload))
        if event_type == "result":
            return portal_agents.events_outcome(self._result_events(payload))
        if "error" in event_type.lower():
            return portal_agents.events_outcome([portal_agents.error_event(payload)])
        if event_type not in {"assistant", "user"}:
            return portal_agents.ignored_structured_event()
        blocks = _content_blocks(payload)
        parent_call_id = portal_agents.clean_str(payload.get("parent_tool_use_id"))
        if parent_call_id:
            return portal_agents.events_outcome(
                self._specialist_events(parent_call_id, payload, blocks)
            )
        return portal_agents.events_outcome(self._orchestrator_events(payload, blocks))

    # -- orchestrator lane -------------------------------------------------

    def _orchestrator_events(
        self, payload: JsonObject, blocks: list[JsonObject]
    ) -> list[JsonObject]:
        events: list[JsonObject] = []
        for block in blocks:
            block_type = str(block.get("type") or "")
            if block_type == "text" and isinstance(block.get("text"), str):
                # The terminal `result` line carries the complete answer, so
                # streamed assistant prose stays in the work trail.
                events.append(_status_event(block["text"]))
            elif block_type == "tool_use":
                events.extend(self._orchestrator_tool_call(block))
            elif block_type == "tool_result":
                events.extend(self._orchestrator_tool_result(block, payload))
        return events

    def _orchestrator_tool_call(self, block: JsonObject) -> list[JsonObject]:
        call_id = portal_agents.clean_str(block.get("id"))
        name = portal_agents.clean_str(block.get("name")) or "tool"
        tool_input = block.get("input") or {}
        if name == SPECIALIST_SPAWN_TOOL:
            if call_id:
                # The portal's spawn_agent call carries the native agent id,
                # which only arrives with the matching task_started line.
                self._specialists.setdefault(call_id, {"started": False})
            return []
        if name == GENOMI_INVOKE_TOOL and call_id and isinstance(tool_input, dict):
            operation = portal_agents.clean_str(tool_input.get("tool")) or ""
            if operation in LAB_ASSIGNMENT_OPERATIONS:
                self._pending_operations[call_id] = operation
        return [{"type": "tool_call", "id": call_id, "name": name, "input": tool_input}]

    def _orchestrator_tool_result(
        self, block: JsonObject, payload: JsonObject
    ) -> list[JsonObject]:
        call_id = portal_agents.clean_str(block.get("tool_use_id")) or ""
        specialist = self._specialists.get(call_id)
        if specialist is not None and specialist.get("started"):
            return self._complete_specialist(call_id, specialist, payload)
        operation = self._pending_operations.pop(call_id, "")
        result_fields = portal_agents.tool_result_fields(block.get("content"))
        if operation and not block.get("is_error"):
            self._remember_assignments(result_fields.get("payload"))
        return [
            {
                "type": "tool_result",
                "id": call_id or None,
                "name": None,
                "isError": bool(block.get("is_error")),
                **result_fields,
            }
        ]

    def _remember_assignments(self, payload: Any) -> None:
        for value in _assignment_records(payload):
            assignment_id = str(value.get("specialist_assignment_id") or "")
            policy = str(value.get("execution_policy") or "")
            state = str(value.get("state") or "")
            if not assignment_id or not policy or state not in _ASSIGNMENT_STATES:
                continue
            existing = self._assignments.get(assignment_id, {})
            self._assignments[assignment_id] = {
                **existing,
                "assignment_id": assignment_id,
                "execution_policy": policy,
                "specialist_brief_id": str(
                    value.get("specialist_brief_id")
                    or existing.get("specialist_brief_id")
                    or ""
                ),
                "specialist_role": str(
                    value.get("specialist_role") or existing.get("specialist_role") or ""
                ),
                "state": state,
            }

    # -- specialist lifecycle ----------------------------------------------

    def _system_events(self, payload: JsonObject) -> list[JsonObject]:
        subtype = str(payload.get("subtype") or "")
        if subtype == "task_started":
            return self._start_specialist(payload)
        specialist = self._specialist_for_task(payload)
        if specialist is None:
            return []
        if subtype == "task_updated":
            patch = payload.get("patch")
            status = (
                portal_agents.clean_str(patch.get("status"))
                if isinstance(patch, dict)
                else None
            )
            # The lifecycle patch is the fallback terminal status when the
            # orchestrator's tool_use_result omits one.
            if status:
                specialist["status"] = status
        elif subtype == "task_notification":
            status = portal_agents.clean_str(payload.get("status"))
            if status:
                specialist["status"] = status
            summary = payload.get("summary")
            if isinstance(summary, str) and summary.strip():
                specialist["terminal_text"] = summary
        return []

    def _start_specialist(self, payload: JsonObject) -> list[JsonObject]:
        call_id = portal_agents.clean_str(payload.get("tool_use_id"))
        task_id = portal_agents.clean_str(payload.get("task_id"))
        if not call_id or not task_id:
            return []
        policy = portal_agents.clean_str(payload.get("subagent_type")) or ""
        task_name = (
            portal_agents.clean_str(payload.get("description")) or policy or task_id
        )
        binding, binding_error = self._bind_assignment(policy, call_id)
        specialist: JsonObject = {
            "call_id": call_id,
            "agent_id": task_id,
            "task_name": task_name,
            "subagent_type": policy,
            "started": True,
            "status": "",
            "terminal_text": "",
        }
        tool_input: JsonObject = {"agent_id": task_id, "task_name": task_name}
        if binding is not None:
            bound = {
                "assignment_id": binding["assignment_id"],
                "execution_policy": binding["execution_policy"],
                "specialist_role": binding.get("specialist_role")
                or "Research specialist",
            }
            specialist.update(bound)
            tool_input.update(bound)
        else:
            specialist["binding_error"] = binding_error
        self._specialists[call_id] = specialist
        self._call_id_by_task_id[task_id] = call_id
        return [
            {
                "type": "tool_call",
                "id": call_id,
                "name": "spawn_agent",
                "input": tool_input,
            }
        ]

    def _bind_assignment(
        self, policy: str, call_id: str
    ) -> tuple[JsonObject | None, str]:
        """Bind the child to the proposed assignment its policy names."""

        candidates = [
            assignment
            for assignment in self._assignments.values()
            if assignment.get("state") == "proposed"
            and not assignment.get("call_id")
            and assignment.get("execution_policy") == policy
        ]
        if len(candidates) == 1:
            candidates[0]["call_id"] = call_id
            return candidates[0], ""
        if candidates:
            return None, "specialist_policy_binding_ambiguous"
        return None, "specialist_policy_binding_missing"

    def _specialist_for_task(self, payload: JsonObject) -> JsonObject | None:
        task_id = portal_agents.clean_str(payload.get("task_id")) or ""
        call_id = self._call_id_by_task_id.get(task_id, "")
        return self._specialists.get(call_id)

    # -- specialist lane ---------------------------------------------------

    def _specialist_events(
        self,
        parent_call_id: str,
        payload: JsonObject,
        blocks: list[JsonObject],
    ) -> list[JsonObject]:
        """Child work never reaches the answer or the top-level tool trail."""

        events: list[JsonObject] = []
        is_child_assistant = str(payload.get("type") or "") == "assistant"
        specialist = self._specialists.get(parent_call_id)
        for block in blocks:
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text = block.get("text")
                if is_child_assistant and specialist is not None and isinstance(text, str) and text.strip():
                    specialist["terminal_text"] = text
                continue
            if block_type != "tool_use":
                continue
            violation = self._policy_violation(parent_call_id, block)
            if violation:
                events.extend(self._violation_events(parent_call_id, violation))
                continue
            progress = self._progress_event(parent_call_id, block)
            if progress is not None:
                events.append(progress)
        return events

    def _policy_violation(self, parent_call_id: str, block: JsonObject) -> str:
        specialist = self._specialists.get(parent_call_id)
        if specialist is None or not specialist.get("started"):
            return "specialist_policy_binding_missing"
        binding_error = str(specialist.get("binding_error") or "")
        if binding_error:
            return binding_error
        name = portal_agents.clean_str(block.get("name")) or "tool"
        if not name.startswith("mcp__"):
            return f"specialist_policy_forbids_{name}"
        tool_input = block.get("input")
        operation = (
            portal_agents.clean_str(tool_input.get("tool")) or ""
            if isinstance(tool_input, dict)
            else ""
        )
        allowed = _allowed_operations(str(specialist.get("execution_policy") or ""))
        if name != GENOMI_INVOKE_TOOL or operation not in allowed:
            return "specialist_policy_operation_not_allowed"
        return ""

    def _violation_events(self, parent_call_id: str, violation: str) -> list[JsonObject]:
        """Report the first violation; the child's receipts are then void.

        Claude Code cannot interrupt a running subagent from the parent's
        stdout, so enforcement is the reported violation plus a refusal to
        authorize any provider receipt this child returns.
        """

        if parent_call_id in self._violated_call_ids:
            return []
        self._violated_call_ids.add(parent_call_id)
        specialist = self._specialists.get(parent_call_id, {})
        return [
            {
                "type": "error",
                "name": "specialist_policy_violation",
                "message": violation,
                "payload": {
                    "agent_id": specialist.get("agent_id") or parent_call_id,
                    "assignment_id": specialist.get("assignment_id"),
                    "execution_policy": specialist.get("execution_policy"),
                    "status": "failed",
                },
            }
        ]

    def _progress_event(
        self, parent_call_id: str, block: JsonObject
    ) -> JsonObject | None:
        """Expose bounded child progress without leaking child prose or results."""

        specialist = self._specialists.get(parent_call_id)
        if specialist is None or specialist.get("binding_error"):
            return None
        tool_input = block.get("input")
        operation = (
            portal_agents.clean_str(tool_input.get("tool")) or ""
            if isinstance(tool_input, dict)
            else ""
        )
        if not operation:
            return None
        agent_id = str(specialist.get("agent_id") or parent_call_id)
        update: JsonObject = {
            "agent_id": agent_id,
            "task_name": str(specialist.get("task_name") or agent_id),
            "status": "running",
            "message": _progress_message(operation),
        }
        assignment_id = str(specialist.get("assignment_id") or "")
        if assignment_id:
            update["assignment_id"] = assignment_id
        return {
            "type": "tool_result",
            "id": f"specialist-progress:{portal_agents.clean_str(block.get('id')) or operation}",
            "name": "specialist_progress",
            "isError": False,
            "content": update["message"],
            "payload": {"updates": [update]},
        }

    # -- specialist completion ---------------------------------------------

    def _complete_specialist(
        self,
        call_id: str,
        specialist: JsonObject,
        payload: JsonObject,
    ) -> list[JsonObject]:
        if call_id in self._completed_call_ids:
            return []
        self._completed_call_ids.add(call_id)
        result = payload.get("tool_use_result")
        result = result if isinstance(result, dict) else {}
        status = (
            portal_agents.clean_str(result.get("status"))
            or str(specialist.get("status") or "")
            or "failed"
        )
        succeeded = status == "completed" and call_id not in self._violated_call_ids
        agent_id = (
            portal_agents.clean_str(result.get("agentId"))
            or str(specialist.get("agent_id") or call_id)
        )
        native_policy = (
            portal_agents.clean_str(result.get("agentType"))
            or str(specialist.get("subagent_type") or "")
        )
        message = _result_text(result.get("content")) or str(
            specialist.get("terminal_text") or ""
        )
        update: JsonObject = {
            "agent_id": agent_id,
            "task_name": str(specialist.get("task_name") or agent_id),
            "status": "completed" if succeeded else "failed",
        }
        assignment_id = str(specialist.get("assignment_id") or "")
        if assignment_id:
            update["assignment_id"] = assignment_id
        if message:
            update["message"] = message
        if succeeded and message:
            self._authorize_specialist_receipts(
                specialist,
                message,
                native_agent_id=agent_id,
                native_policy=native_policy,
            )
        output: JsonObject = {
            "status": update["status"],
            "updates": [update],
            "agentsStates": {agent_id: update},
        }
        return [
            {
                "type": "tool_result",
                "id": call_id,
                "name": "spawn_agent",
                "isError": not succeeded,
                "content": portal_agents.content_preview(output),
                "payload": output,
            }
        ]

    def _authorize_specialist_receipts(
        self,
        specialist: JsonObject,
        message: str,
        *,
        native_agent_id: str,
        native_policy: str,
    ) -> None:
        """Bind only receipts observed in this child's terminal response."""

        assignment_id = str(specialist.get("assignment_id") or "")
        assignment = self._assignments.get(assignment_id, {})
        brief_id = str(assignment.get("specialist_brief_id") or "")
        policy = str(specialist.get("execution_policy") or "")
        if native_policy and native_policy != policy:
            # The child ran under a different profile than the assignment it
            # was bound to, so its results are outside the approved policy.
            return
        if not all((self.session_id, assignment_id, brief_id, policy, native_agent_id)):
            return
        for receipt_id in sorted(set(_RESULT_RECEIPT_PATTERN.findall(message))):
            try:
                EVIDENCE_RESULT_RECEIPTS.authorize_specialist_result(
                    receipt_id,
                    session_id=self.session_id,
                    specialist_assignment_id=assignment_id,
                    specialist_brief_id=brief_id,
                    native_agent_id=native_agent_id,
                    execution_policy=policy,
                )
            except EvidenceResultReceiptError:
                # Search receipts may expire before a long specialist turn ends,
                # and arbitrary receipt-looking prose is not trusted. Capture
                # still fails closed because it requires a valid authorization.
                continue

    # -- terminal result ---------------------------------------------------

    def _result_events(self, payload: JsonObject) -> list[JsonObject]:
        events: list[JsonObject] = []
        denials = payload.get("permission_denials")
        for denial in denials if isinstance(denials, list) else []:
            if not isinstance(denial, dict):
                continue
            tool = portal_agents.clean_approved_tool(denial.get("tool_name"))
            if not tool:
                continue
            label = portal_agents.permission_label(tool)
            events.append(
                {
                    "type": "error",
                    "name": "host_agent_permission_request",
                    "message": f"Claude requested permission to use {tool}.",
                    "permission_request": {
                        "kind": "host_agent_tool",
                        "tool": tool,
                        "label": label,
                    },
                }
            )
        result = payload.get("result")
        if isinstance(result, str) and result.strip():
            events.append({"type": "text_delta", "delta": result})
        return events


def _status_event(text: str) -> JsonObject:
    setup_event = portal_agents.text_or_diagnostic_event(text)
    if setup_event.get("type") == "diagnostic":
        return setup_event
    return {
        "type": "diagnostic",
        "name": "assistant_status",
        "message": portal_agents.content_preview(text),
    }


def _content_blocks(payload: JsonObject) -> list[JsonObject]:
    message = payload.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = [
        block["text"]
        for block in value
        if isinstance(block, dict)
        and str(block.get("type") or "") == "text"
        and isinstance(block.get("text"), str)
    ]
    return "\n".join(parts)


def _assignment_records(value: Any, depth: int = 0) -> list[JsonObject]:
    if depth > 5:
        return []
    if isinstance(value, str):
        try:
            return _assignment_records(json.loads(value), depth + 1)
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(value, list):
        records: list[JsonObject] = []
        for child in value:
            records.extend(_assignment_records(child, depth + 1))
        return records
    if not isinstance(value, dict):
        return []
    records = []
    assignment = value.get("assignment")
    if isinstance(assignment, dict):
        records.append(assignment)
    listed = value.get("specialist_assignments")
    if isinstance(listed, list):
        records.extend(item for item in listed if isinstance(item, dict))
    if records:
        return records
    for key in ("structuredContent", "structured_content", "result", "payload", "content", "text"):
        if key not in value:
            continue
        found = _assignment_records(value[key], depth + 1)
        if found:
            return found
    return []


def _allowed_operations(policy: str) -> frozenset[str]:
    return _policy_operations().get(policy, frozenset())


@lru_cache(maxsize=1)
def _policy_operations() -> dict[str, frozenset[str]]:
    return {
        str(profile["id"]): frozenset(profile["allowed_operations"])
        for profile in policy_manifest()["profiles"]
    }


def _progress_message(operation: str) -> str:
    if operation == "paperclip.search_biomedical":
        return "Searching public biomedical literature"
    if operation == "paperclip.retrieve_document_evidence":
        return "Reading line-pinned public evidence"
    if operation.startswith("biohub."):
        return "Running the bounded BioHub analysis"
    if operation.startswith("proto."):
        return "Running the bounded Proto analysis"
    return "Running the authorized specialist operation"


__all__ = ["ClaudeStreamSession"]
