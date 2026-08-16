from __future__ import annotations

import os
from unittest import mock

from genomi.interfaces import cli, portal_agents, portal_project_assistant, portal_store
from genomi.interfaces.cli import build_parser
from genomi.runtime import context as runtime_context

from tests.support.runtime.genomi import GenomiRuntimeTestCase


def _installed(*commands: str):
    return mock.patch(
        "genomi.interfaces.portal_agents.shutil.which",
        side_effect=lambda command: f"/usr/local/bin/{command}" if command in set(commands) else None,
    )


def _host_agent_session(**session_env: str):
    cleared = {name: "" for name in runtime_context.AGENT_SESSION_ENVS}
    return mock.patch.dict(os.environ, {**cleared, **session_env}, clear=False)


class WorkspaceAssistantResolutionTests(GenomiRuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        portal_agents.set_launch_agent_id("")
        self.addCleanup(portal_agents.set_launch_agent_id, "")

    def test_workspace_started_from_claude_code_runs_on_claude_code(self) -> None:
        project = portal_store.create_project(name="Bootstrapped from Claude Code")

        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(resolution.state, "ready")
        self.assertEqual(resolution.agent_id, "claude")
        self.assertEqual(resolution.source, "bootstrap_host_agent")
        self.assertEqual(workspace["assistant"]["active_agent_id"], "claude")
        self.assertEqual(workspace["assistant"]["active_label"], "Claude Code")
        self.assertEqual(workspace["assistant"]["selected_agent_id"], "")
        self.assertEqual([agent["id"] for agent in workspace["agents"] if agent["active"]], ["claude"])

    def test_saved_workspace_choice_wins_over_the_bootstrap_host_agent(self) -> None:
        project = portal_store.create_project(name="Chosen assistant")

        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            choice = portal_project_assistant.select_agent(project["project_id"], "codex")
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(choice["agent_id"], "codex")
        self.assertEqual(resolution.agent_id, "codex")
        self.assertEqual(resolution.source, "workspace_choice")
        self.assertEqual(workspace["assistant"]["selected_agent_id"], "codex")
        self.assertEqual([agent["id"] for agent in workspace["agents"] if agent["selected"]], ["codex"])

    def test_saved_choice_persists_across_reads_and_is_scoped_to_one_workspace(self) -> None:
        chosen = portal_store.create_project(name="Chosen")
        untouched = portal_store.create_project(name="Untouched")

        with _installed("codex", "claude"), _host_agent_session(CODEX_THREAD_ID="thread-1"):
            portal_project_assistant.select_agent(chosen["project_id"], "claude")

            self.assertEqual(portal_project_assistant.selected_agent_id(chosen["project_id"]), "claude")
            self.assertEqual(portal_project_assistant.selected_agent_id(untouched["project_id"]), "")
            self.assertEqual(portal_project_assistant.resolve_agent(chosen["project_id"]).agent_id, "claude")
            self.assertEqual(portal_project_assistant.resolve_agent(untouched["project_id"]).agent_id, "codex")

    def test_explicit_request_agent_wins_over_the_saved_workspace_choice(self) -> None:
        project = portal_store.create_project(name="One-off assistant")

        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            portal_project_assistant.select_agent(project["project_id"], "claude")
            resolution = portal_project_assistant.resolve_agent(project["project_id"], requested_agent_id="codex")

        self.assertEqual(resolution.agent_id, "codex")
        self.assertEqual(resolution.source, "request")

    def test_saved_choice_that_cannot_run_here_is_reported_instead_of_swapped(self) -> None:
        project = portal_store.create_project(name="Assistant went away")

        with _installed("codex", "claude"), _host_agent_session():
            portal_project_assistant.select_agent(project["project_id"], "claude")
        with _installed("codex"), _host_agent_session(CODEX_THREAD_ID="thread-1"):
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(resolution.state, "workspace_choice_unavailable")
        self.assertEqual(resolution.agent_id, "")
        self.assertEqual(resolution.unavailable_agent_id, "claude")
        self.assertEqual(resolution.unavailable_label, "Claude Code")
        self.assertEqual(workspace["assistant"]["state"], "workspace_choice_unavailable")
        self.assertEqual(workspace["assistant"]["unavailable_label"], "Claude Code")

    def test_an_assistant_without_a_runnable_driver_cannot_be_selected(self) -> None:
        project = portal_store.create_project(name="Unsupported assistant")

        with _installed("codex", "gemini"), _host_agent_session():
            saved = portal_project_assistant.select_agent(project["project_id"], "gemini")

        self.assertIsNone(saved)
        self.assertEqual(portal_project_assistant.selected_agent_id(project["project_id"]), "")

    def test_no_runnable_assistant_is_reported_as_none_available(self) -> None:
        project = portal_store.create_project(name="No assistant")

        with _installed(), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(resolution.state, "none_available")
        self.assertEqual(workspace["assistant"]["active_agent_id"], "")
        self.assertEqual([agent["id"] for agent in workspace["agents"] if agent["runnable"]], [])

    def test_workspace_reports_the_assistant_that_failed_its_last_turn(self) -> None:
        project = portal_store.create_project(name="Out of allowance")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review my CYP2C19 genotype",
            agent_id="codex",
        )
        portal_store.finish_frame(
            str(frame["id"]),
            status="failed",
            error='{"message": "You have hit your usage limit."}',
        )

        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        by_id = {agent["id"]: agent for agent in workspace["agents"]}
        self.assertEqual(by_id["codex"]["last_run_failure"], "assistant_usage_limit_reached")
        self.assertNotIn("last_run_failure", by_id["claude"])

    def test_a_bare_terminal_launch_with_several_assistants_asks_instead_of_guessing(self) -> None:
        project = portal_store.create_project(name="Plain terminal launch")

        with _installed("codex", "claude"), _host_agent_session():
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(resolution.state, "choice_required")
        self.assertEqual(resolution.agent_id, "")
        self.assertEqual(resolution.candidate_agent_ids, ("codex", "claude"))
        self.assertEqual(workspace["assistant"]["state"], "choice_required")
        self.assertEqual(workspace["assistant"]["active_agent_id"], "")
        self.assertEqual([agent["id"] for agent in workspace["agents"] if agent["active"]], [])

    def test_a_bare_terminal_launch_uses_the_only_installed_assistant(self) -> None:
        project = portal_store.create_project(name="Single assistant")

        with _installed("claude"), _host_agent_session():
            resolution = portal_project_assistant.resolve_agent(project["project_id"])

        self.assertEqual(resolution.state, "ready")
        self.assertEqual(resolution.agent_id, "claude")
        self.assertEqual(resolution.source, "only_runnable")

    def test_a_bare_terminal_launch_skips_the_assistant_that_just_failed_here(self) -> None:
        project = portal_store.create_project(name="One assistant already failed")
        frame = portal_store.create_frame(
            project_id=project["project_id"],
            request="Review my CYP2C19 genotype",
            agent_id="codex",
        )
        portal_store.finish_frame(
            str(frame["id"]),
            status="failed",
            error='{"message": "You have hit your usage limit."}',
        )

        with _installed("codex", "claude"), _host_agent_session():
            resolution = portal_project_assistant.resolve_agent(project["project_id"])

        self.assertEqual(resolution.state, "ready")
        self.assertEqual(resolution.agent_id, "claude")
        self.assertEqual(resolution.source, "only_one_working_here")

    def test_a_turn_the_person_stopped_does_not_count_as_an_assistant_failure(self) -> None:
        project = portal_store.create_project(name="Stopped by the person")
        frame = portal_store.create_frame(project_id=project["project_id"], request="Stop this", agent_id="codex")
        portal_store.finish_frame(str(frame["id"]), status="canceled", error="Run canceled.")

        with _installed("codex", "claude"), _host_agent_session():
            resolution = portal_project_assistant.resolve_agent(project["project_id"])

        self.assertEqual(resolution.state, "choice_required")

    def test_launch_agent_option_outranks_the_bootstrap_host_agent(self) -> None:
        project = portal_store.create_project(name="Launched with --agent")

        with _installed("codex", "claude"), _host_agent_session(CLAUDE_CODE_SESSION_ID="session-1"):
            portal_agents.set_launch_agent_id("codex")
            resolution = portal_project_assistant.resolve_agent(project["project_id"])
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        self.assertEqual(resolution.agent_id, "codex")
        self.assertEqual(resolution.source, "launch_option")
        self.assertEqual(workspace["assistant"]["source"], "launch_option")

    def test_saved_choice_and_explicit_request_outrank_the_launch_agent_option(self) -> None:
        project = portal_store.create_project(name="Launch option overridden")

        with _installed("codex", "claude"), _host_agent_session():
            portal_agents.set_launch_agent_id("codex")
            portal_project_assistant.select_agent(project["project_id"], "claude")
            saved = portal_project_assistant.resolve_agent(project["project_id"])
            requested = portal_project_assistant.resolve_agent(project["project_id"], requested_agent_id="codex")

        self.assertEqual((saved.agent_id, saved.source), ("claude", "workspace_choice"))
        self.assertEqual((requested.agent_id, requested.source), ("codex", "request"))

    def test_a_later_successful_turn_clears_the_assistant_failure_note(self) -> None:
        project = portal_store.create_project(name="Recovered")
        failed = portal_store.create_frame(project_id=project["project_id"], request="First try", agent_id="codex")
        portal_store.finish_frame(str(failed["id"]), status="failed", error="Rate limit reached")
        recovered = portal_store.create_frame(project_id=project["project_id"], request="Second try", agent_id="codex")
        portal_store.finish_frame(str(recovered["id"]), status="completed", output="Here is the evidence.")

        with _installed("codex", "claude"), _host_agent_session():
            workspace = portal_project_assistant.workspace_assistants(project["project_id"])

        by_id = {agent["id"]: agent for agent in workspace["agents"]}
        self.assertNotIn("last_run_failure", by_id["codex"])
        self.assertEqual(portal_store.latest_agent_run_failures(project["project_id"]), {})


class LaunchAgentOptionTests(GenomiRuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        portal_agents.set_launch_agent_id("")
        self.addCleanup(portal_agents.set_launch_agent_id, "")

    def test_serve_and_lab_accept_a_runnable_assistant(self) -> None:
        parser = build_parser()

        serve_args = parser.parse_args(["serve", "--app", "--agent", "claude"])
        lab_args = parser.parse_args(["lab", "--agent", "claude"])
        with _installed("codex", "claude"):
            cli._apply_launch_agent(serve_args.agent)
            after_serve = portal_agents.launch_agent_id()
            cli._apply_launch_agent(lab_args.agent)
            after_lab = portal_agents.launch_agent_id()

        self.assertEqual(serve_args.agent, "claude")
        self.assertEqual(lab_args.agent, "claude")
        self.assertEqual(after_serve, "claude")
        self.assertEqual(after_lab, "claude")

    def test_an_unknown_or_unrunnable_assistant_is_refused_with_the_runnable_ids(self) -> None:
        with _installed("codex", "claude"):
            with self.assertRaises(SystemExit) as unknown:
                cli._apply_launch_agent("copilot")
            with self.assertRaises(SystemExit) as not_runnable:
                cli._apply_launch_agent("gemini")

            self.assertEqual(portal_agents.launch_agent_id(), "")

        self.assertIn("--agent 'copilot' is not a runnable assistant here", str(unknown.exception))
        self.assertIn("Available: codex, claude", str(unknown.exception))
        self.assertIn("--agent 'gemini' is not a runnable assistant here", str(not_runnable.exception))

    def test_no_agent_option_leaves_the_launch_choice_unset(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["lab"])
        with _installed("codex", "claude"):
            cli._apply_launch_agent(args.agent)

            self.assertIsNone(args.agent)
            self.assertEqual(portal_agents.launch_agent_id(), "")
