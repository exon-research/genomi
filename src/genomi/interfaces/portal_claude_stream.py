"""Per-run adapter for the Claude Code stream-json host contract.

Claude Code streams one JSON object per stdout line.  Orchestrator work and
native specialist work share that stream and are separated only by
``parent_tool_use_id``.  This session keeps the per-run specialist state that
makes GenomiLab's portal contract work on Claude: specialist lane isolation,
fixed execution-policy enforcement, and provider-receipt authorization.
"""

from __future__ import annotations

from typing import Any

from ..operations.registry.evidence_result_receipts import (
    EVIDENCE_RESULT_RECEIPTS,
    EvidenceResultReceiptError,
)
from . import portal_agents, portal_specialist_lane
from .portal_claude_runtime import GENOMI_INVOKE_TOOL

JsonObject = dict[str, Any]

SPECIALIST_SPAWN_TOOL = "Agent"
SPECIALIST_CONTINUE_TOOL = "SendMessage"


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
        is_assistant = str(payload.get("type") or "") == "assistant"
        for block in blocks:
            block_type = str(block.get("type") or "")
            if block_type == "text" and is_assistant and isinstance(block.get("text"), str):
                # The terminal `result` line carries the complete answer, so
                # streamed assistant prose stays in the work trail. Replayed
                # user text is the operator's own message, never host work.
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
        if name in {SPECIALIST_SPAWN_TOOL, SPECIALIST_CONTINUE_TOOL}:
            if call_id:
                # The portal's spawn_agent call carries the native agent id,
                # which only arrives with the matching task_started line.
                self._specialists.setdefault(
                    call_id,
                    {
                        "started": False,
                        "continuation": name == SPECIALIST_CONTINUE_TOOL,
                    },
                )
            return []
        if name == GENOMI_INVOKE_TOOL and call_id and isinstance(tool_input, dict):
            operation = portal_agents.clean_str(tool_input.get("tool")) or ""
            if operation in portal_specialist_lane.LAB_ASSIGNMENT_OPERATIONS:
                self._pending_operations[call_id] = operation
        return [{"type": "tool_call", "id": call_id, "name": name, "input": tool_input}]

    def _orchestrator_tool_result(
        self, block: JsonObject, payload: JsonObject
    ) -> list[JsonObject]:
        call_id = portal_agents.clean_str(block.get("tool_use_id")) or ""
        specialist = self._specialists.get(call_id)
        if specialist is not None:
            if _is_async_launch(payload.get("tool_use_result")):
                # A background Agent returns the moment the child is launched,
                # long before it has done any work. Its terminal boundary is the
                # later task_notification, exactly like a resumed child.
                specialist["async_launch"] = True
                return []
            if specialist.get("continuation"):
                # A continuation's tool_result is the immediate resume
                # acknowledgement; the child's terminal boundary is its
                # task_notification.
                return []
            if specialist.get("started"):
                return self._complete_specialist_from_spawn(
                    call_id, specialist, payload
                )
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
        for value in portal_specialist_lane.assignment_records(payload):
            assignment_id = str(value.get("specialist_assignment_id") or "")
            merged = portal_specialist_lane.merged_assignment(
                self._assignments.get(assignment_id, {}), value
            )
            if merged is not None:
                self._assignments[assignment_id] = merged

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
            if specialist.get("continuation") or specialist.get("async_launch"):
                # Resumed and background children never deliver a terminal
                # Agent tool_result, so this notification is their only
                # completion boundary.
                return self._complete_specialist(
                    str(specialist.get("call_id") or ""),
                    specialist,
                    status=str(specialist.get("status") or ""),
                    message=str(specialist.get("terminal_text") or ""),
                    agent_id=str(specialist.get("agent_id") or ""),
                    native_policy=str(specialist.get("subagent_type") or ""),
                )
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
        pending = self._specialists.get(call_id, {})
        specialist: JsonObject = {
            "call_id": call_id,
            "agent_id": task_id,
            "task_name": task_name,
            "subagent_type": policy,
            "started": True,
            "continuation": bool(pending.get("continuation")),
            "async_launch": bool(pending.get("async_launch")),
            "status": "",
            "terminal_text": "",
            "provider_calls": 0,
            "provider_errors": 0,
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
        """Bind the child to the live assignment its policy names.

        Claude Code emits a task_started line both for a fresh Agent spawn and
        for a SendMessage continuation of a running child, so both live
        assignment states can own a child.
        """

        candidates = [
            assignment
            for assignment in self._assignments.values()
            if assignment.get("state")
            in portal_specialist_lane.BINDABLE_ASSIGNMENT_STATES
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
        # A resumed child keeps its task id across turns, so the notification's
        # own tool_use_id names the exact turn that is ending.
        call_id = portal_agents.clean_str(payload.get("tool_use_id")) or ""
        if call_id not in self._specialists:
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
            if block_type == "tool_result":
                # A failing provider call is an answerability gap the host agent
                # must be able to tell apart from a child that simply stopped.
                if specialist is not None and block.get("is_error"):
                    specialist["provider_errors"] = (
                        int(specialist.get("provider_errors") or 0) + 1
                    )
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
        allowed = portal_specialist_lane.allowed_operations(
            str(specialist.get("execution_policy") or "")
        )
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
        specialist["provider_calls"] = int(specialist.get("provider_calls") or 0) + 1
        agent_id = str(specialist.get("agent_id") or parent_call_id)
        update: JsonObject = {
            "agent_id": agent_id,
            "task_name": str(specialist.get("task_name") or agent_id),
            "status": "running",
            "message": portal_specialist_lane.progress_message(operation),
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

    def _complete_specialist_from_spawn(
        self,
        call_id: str,
        specialist: JsonObject,
        payload: JsonObject,
    ) -> list[JsonObject]:
        """A foreground Agent's tool_use_result is the child's terminal boundary."""

        result = payload.get("tool_use_result")
        result = result if isinstance(result, dict) else {}
        return self._complete_specialist(
            call_id,
            specialist,
            status=portal_agents.clean_str(result.get("status"))
            or str(specialist.get("status") or ""),
            message=_result_text(result.get("content"))
            or str(specialist.get("terminal_text") or ""),
            agent_id=portal_agents.clean_str(result.get("agentId"))
            or str(specialist.get("agent_id") or call_id),
            native_policy=portal_agents.clean_str(result.get("agentType"))
            or str(specialist.get("subagent_type") or ""),
        )

    def _complete_specialist(
        self,
        call_id: str,
        specialist: JsonObject,
        *,
        status: str,
        message: str,
        agent_id: str,
        native_policy: str,
    ) -> list[JsonObject]:
        if not call_id or call_id in self._completed_call_ids:
            return []
        self._completed_call_ids.add(call_id)
        agent_id = agent_id or call_id
        update = portal_specialist_lane.terminal_specialist_update(
            specialist,
            agent_id=agent_id,
            run_completed=(status or "failed") == "completed",
            violated=call_id in self._violated_call_ids,
            message=message,
        )
        delivered = update["status"] == "completed"
        if delivered:
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
                "isError": not delivered,
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
        for receipt_id in portal_specialist_lane.observed_result_receipt_ids(message):
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


def _is_async_launch(value: Any) -> bool:
    """A background Agent acknowledges the launch, not the child's result."""

    if not isinstance(value, dict):
        return False
    return bool(value.get("isAsync")) or str(value.get("status") or "") == "async_launched"


__all__ = ["ClaudeStreamSession"]
