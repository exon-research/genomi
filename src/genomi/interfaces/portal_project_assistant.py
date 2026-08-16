"""Which local assistant a workspace runs its turns on.

Genomi detects assistant CLIs on PATH, but which one a workspace uses is a
durable decision, not a per-request accident. This module owns that
project-scoped choice, the order Genomi resolves it in, and the workspace view
of it that the portal shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import portal_agents, portal_project_events, portal_state, portal_store

JsonObject = dict[str, Any]
PROJECT_ASSISTANT_KEY = "selected_assistant"

READY = "ready"
REQUESTED_UNAVAILABLE = "requested_unavailable"
CHOICE_UNAVAILABLE = "workspace_choice_unavailable"
CHOICE_REQUIRED = "choice_required"
NONE_AVAILABLE = "none_available"

FROM_REQUEST = "request"
FROM_WORKSPACE_CHOICE = "workspace_choice"
FROM_LAUNCH_OPTION = "launch_option"
FROM_BOOTSTRAP_HOST_AGENT = "bootstrap_host_agent"
FROM_ONLY_RUNNABLE = "only_runnable"
FROM_ONLY_ONE_WORKING_HERE = "only_one_working_here"

# A run the person stopped, or one Genomi cut short by restarting, says nothing
# about whether that assistant works.
_NON_RUNTIME_FAILURE_REASONS = frozenset({"run_stopped_by_you", "assistant_stopped_at_restart"})


@dataclass(frozen=True)
class AssistantResolution:
    """The assistant one turn will run on, and why that one."""

    state: str
    agent_id: str = ""
    source: str = ""
    unavailable_agent_id: str = ""
    unavailable_label: str = ""
    candidate_agent_ids: tuple[str, ...] = ()


def selected_agent_id(project_id: str | None, *, root: str | Path | None = None) -> str:
    clean_project_id = str(project_id or "").strip()
    if not clean_project_id:
        return ""
    project = portal_state.read_state(root)["projects"].get(clean_project_id)
    choice = project.get(PROJECT_ASSISTANT_KEY) if isinstance(project, dict) else None
    return str(choice.get("agent_id") or "").strip() if isinstance(choice, dict) else ""


def select_agent(project_id: str, agent_id: str, *, root: str | Path | None = None) -> JsonObject | None:
    """Persist this workspace's assistant. Returns None for an unknown project."""

    clean_project_id = str(project_id or "").strip()
    clean_agent_id = str(agent_id or "").strip()
    if not clean_project_id or clean_agent_id not in portal_agents.runnable_agent_ids():
        return None

    def mutate(state: JsonObject) -> JsonObject | None:
        project = state["projects"].get(clean_project_id)
        if not isinstance(project, dict):
            return None
        now = datetime.now(timezone.utc).isoformat()
        choice = {"agent_id": clean_agent_id, "selected_at": now}
        project[PROJECT_ASSISTANT_KEY] = choice
        project["updated_at"] = now
        return dict(choice)

    choice = portal_state.mutate_state(mutate, root)
    if not isinstance(choice, dict):
        return None
    portal_project_events.emit_project_event(
        clean_project_id,
        "project_changed",
        {"reason": "assistant_changed"},
        root=root,
    )
    return choice


def resolve_agent(
    project_id: str | None,
    *,
    requested_agent_id: str | None = None,
    root: str | Path | None = None,
) -> AssistantResolution:
    """Which assistant runs this turn, in order of how deliberate the signal is.

    This request's `agentId`, then the workspace's saved choice, then `--agent`
    from the launch command, then the host agent that started this portal. With
    no signal at all, Genomi only picks by itself when the pick is not
    arbitrary: one installed assistant, or one that has not just failed here.
    Otherwise it asks the person once and remembers the answer, because a silent
    pick between equals is what sends a turn to an assistant nobody chose.
    """

    runnable = portal_agents.runnable_agent_ids()
    requested = str(requested_agent_id or "").strip()
    if requested:
        if requested in runnable:
            return AssistantResolution(READY, agent_id=requested, source=FROM_REQUEST)
        return _unavailable(REQUESTED_UNAVAILABLE, requested)
    chosen = selected_agent_id(project_id, root=root)
    if chosen:
        if chosen in runnable:
            return AssistantResolution(READY, agent_id=chosen, source=FROM_WORKSPACE_CHOICE)
        return _unavailable(CHOICE_UNAVAILABLE, chosen)
    launched = portal_agents.launch_agent_id()
    if launched:
        return AssistantResolution(READY, agent_id=launched, source=FROM_LAUNCH_OPTION)
    bootstrap = portal_agents.bootstrap_agent_id()
    if bootstrap in runnable:
        return AssistantResolution(READY, agent_id=bootstrap, source=FROM_BOOTSTRAP_HOST_AGENT)
    if not runnable:
        return AssistantResolution(NONE_AVAILABLE)
    if len(runnable) == 1:
        return AssistantResolution(READY, agent_id=runnable[0], source=FROM_ONLY_RUNNABLE)
    failed_here = runtime_failures(project_id, root=root)
    working = [agent_id for agent_id in runnable if agent_id not in failed_here]
    if len(working) == 1:
        return AssistantResolution(READY, agent_id=working[0], source=FROM_ONLY_ONE_WORKING_HERE)
    return AssistantResolution(CHOICE_REQUIRED, candidate_agent_ids=tuple(runnable))


def runtime_failures(project_id: str | None, *, root: str | Path | None = None) -> dict[str, str]:
    """Assistants whose most recent finished turn here failed at runtime level."""

    failures = portal_store.latest_agent_run_failures(str(project_id or ""), root=root)
    return {
        agent_id: str(outcome.get("reason") or "")
        for agent_id, outcome in failures.items()
        if str(outcome.get("reason") or "") not in _NON_RUNTIME_FAILURE_REASONS
    }


def workspace_assistants(project_id: str | None = None, *, root: str | Path | None = None) -> JsonObject:
    """Every detected assistant plus which one this workspace will use."""

    resolution = resolve_agent(project_id, root=root)
    chosen = selected_agent_id(project_id, root=root)
    failures = runtime_failures(project_id, root=root)
    agents: list[JsonObject] = []
    for agent in portal_agents.detect_agents():
        agent_id = str(agent.get("id") or "")
        entry = {**agent, "selected": agent_id == chosen, "active": agent_id == resolution.agent_id}
        if agent_id in failures:
            entry["last_run_failure"] = failures[agent_id]
        agents.append(entry)
    return {
        "agents": agents,
        "assistant": {
            "state": resolution.state,
            "source": resolution.source,
            "active_agent_id": resolution.agent_id,
            "active_label": agent_label(resolution.agent_id),
            "selected_agent_id": chosen,
            "unavailable_agent_id": resolution.unavailable_agent_id,
            "unavailable_label": resolution.unavailable_label,
        },
    }


def agent_label(agent_id: str) -> str:
    driver = portal_agents.driver_for(str(agent_id or "").strip())
    return driver.label if driver else str(agent_id or "").strip()


def _unavailable(state: str, agent_id: str) -> AssistantResolution:
    return AssistantResolution(state, unavailable_agent_id=agent_id, unavailable_label=agent_label(agent_id))
