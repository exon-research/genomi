from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

class _FakeAppServerTransport:
    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, message: Any) -> None:
        self.sent.append(dict(message))

    def receive(self, _: float) -> dict[str, Any]:
        if not self.script:
            raise subprocess.TimeoutExpired("fake-app-server", 1)
        message = self.script.pop(0)
        if message.get("$reply"):
            expected_method = str(message["$reply"])
            request = next(
                item
                for item in reversed(self.sent)
                if item.get("method") == expected_method and "id" in item
            )
            result = message.get("result", {})
            return {"id": request["id"], "result": result}
        return message

    def close(self) -> None:
        self.closed = True


class _BlockingAppServerTransport(_FakeAppServerTransport):
    def __init__(self, script: list[dict[str, Any]]) -> None:
        super().__init__(script)
        self.turn_started = threading.Event()
        self.interrupt_requested = threading.Event()
        self._condition = threading.Condition()
        self._interrupt_replied = False

    def send(self, message: Any) -> None:
        super().send(message)
        if message.get("method") == "turn/interrupt":
            self.interrupt_requested.set()
            with self._condition:
                self._condition.notify_all()

    def receive(self, timeout: float) -> dict[str, Any]:
        if self.script:
            message = super().receive(timeout)
            if message.get("method") == "turn/started" or (
                message.get("id") is not None
                and any(item.get("method") == "turn/start" for item in self.sent)
            ):
                self.turn_started.set()
            return message
        with self._condition:
            self._condition.wait_for(self.interrupt_requested.is_set, timeout=timeout)
        if not self.interrupt_requested.is_set():
            raise subprocess.TimeoutExpired("fake-app-server", timeout)
        interrupt = next(
            item for item in self.sent if item.get("method") == "turn/interrupt"
        )
        if not self._interrupt_replied:
            self._interrupt_replied = True
            return {"id": interrupt["id"], "result": {}}
        return {
            "method": "turn/completed",
            "params": {
                "threadId": "codex-thread-a",
                "turn": {
                    "id": "turn-a",
                    "status": "interrupted",
                    "items": [],
                },
            },
        }


def _app_server_runner(
    command: list[str], **_: Any
) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, "codex 9.9.9\n", "")
    if command[1:] == ["app-server", "--help"]:
        return subprocess.CompletedProcess(
            command,
            0,
            "Usage: codex app-server\n--stdio\ngenerate-json-schema\n",
            "",
        )
    raise AssertionError(f"unexpected discovery command: {command}")


def _plan_artifact() -> dict[str, Any]:
    return {
        "summary": "Proposed plan",
        "steps": [
            {
                "id": "step-1",
                "title": "Review",
                "rationale": "Ground the work",
                "capabilities": ["investigation.project_profile"],
                "proposed_agent_role": "patient_context_reviewer",
                "requires_private_context": True,
                "requires_external_provider": False,
            }
        ],
        "proposed_agent_roles": [
            {
                "role": "patient_context_reviewer",
                "objective": "Review approved patient context",
                "assigned_step_ids": ["step-1"],
            }
        ],
        "capability_requests": [
            {
                "id": "request-profile",
                "step_id": "step-1",
                "assigned_agent_role": "patient_context_reviewer",
                "capability": "investigation.project_profile",
                "parameters": "{}",
            }
        ],
        "required_approvals": [],
    }


def _completed_turn(turn_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "turn/completed",
        "params": {
            "threadId": "codex-thread-a",
            "turn": {
                "id": turn_id,
                "status": "completed",
                "items": [
                    {
                        "type": "agentMessage",
                        "id": "message-a",
                        "text": json.dumps(artifact),
                        "phase": "final_answer",
                        "memoryCitation": None,
                    }
                ],
            },
        },
    }
