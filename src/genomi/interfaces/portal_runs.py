from __future__ import annotations

import json
import queue
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..runtime.context import GENOMI_SESSION_ENV
from . import (
    portal_active_context,
    portal_agents,
    portal_codex_app_server,
    portal_codex_runtime,
    portal_context,
    portal_conversation_reviews,
    portal_genomilab,
    portal_lab_skill_context,
    portal_project_genomes,
    portal_run_events,
    portal_store,
    portal_turns,
    portal_workspace_files,
    portal_workspaces,
)

JsonObject = dict[str, Any]
PortalRun = portal_run_events.PortalRun
_EMPTY_SUCCESS_DIAGNOSTIC = "The assistant finished successfully but did not return output."
GENOMILAB_PORTAL_PROJECT_ENV = "GENOMILAB_PORTAL_PROJECT_ID"
GENOMILAB_PORTAL_FRAME_ENV = "GENOMILAB_PORTAL_FRAME_ID"


class HostAgentRunPresentation:
    def __init__(self, run: PortalRun) -> None:
        self.run = run
        self.visible_streamed_content = False
        self.permission_request: JsonObject | None = None
        self.workspace: Path | None = None
        self.workspace_snapshot: portal_workspace_files.WorkspaceSnapshot = {}
        self._tool_names_by_id: dict[str, str] = {}
        self._tool_calls_by_id: dict[str, JsonObject] = {}

    def configure_workspace_tracking(
        self,
        workspace: Path,
        snapshot: portal_workspace_files.WorkspaceSnapshot,
    ) -> None:
        self.workspace = workspace
        self.workspace_snapshot = snapshot

    def emit_diagnostic(self, name: str, *, agent_id: str | None = None, message: str | None = None) -> None:
        event: JsonObject = {"type": "diagnostic", "name": name}
        if agent_id:
            event["agentId"] = agent_id
        if message:
            event["message"] = message
        self.handle_agent_event(event)

    def handle_agent_event(self, event: JsonObject) -> None:
        event = _event_with_permission_request(event)
        event_type = str(event.get("type") or "")
        self._remember_tool_call(event)
        permission = event.get("permission_request")
        if self.permission_request is not None and event_type in {"tool_call", "tool_result", "error"}:
            return
        if isinstance(permission, dict):
            self.permission_request = dict(permission)
        if event_type == "text_delta":
            self._append_answer_text(str(event.get("delta") or ""))
        elif event_type in {"tool_call", "tool_result", "error", "diagnostic"}:
            if event_type != "diagnostic":
                self.visible_streamed_content = True
            if event_type == "tool_result" and not event.get("isError"):
                self._bind_created_lab_investigation(event)
            if self.run.frame_id:
                portal_store.append_message(self.run.frame_id, role="tool", event=event, run_id=self.run.id)
            self.run.emit("agent", event)
            if self._completed_workspace_write(event):
                self.materialize_workspace_files()
        else:
            self.run.emit("agent", event)

    def materialize_workspace_files(self) -> None:
        if not self.run.project_id or self.workspace is None:
            return
        self.workspace_snapshot = _emit_workspace_file_artifacts(
            self.run,
            self,
            self.workspace,
            self.workspace_snapshot,
        )

    def handle_plain_text_fallback(self, text: str) -> None:
        if text:
            self.handle_agent_event(portal_agents.text_or_diagnostic_event(text))

    def drain_stderr(self, stderr_queue: queue.Queue[str]) -> None:
        chunks: list[str] = []
        while True:
            try:
                chunks.append(stderr_queue.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return
        text = "".join(chunks)[-4000:]
        clean_text = text.strip()
        if not clean_text:
            return
        self.run.error = clean_text
        self.visible_streamed_content = True
        self.run.emit("stderr", {"chunk": text})

    def complete_success(self) -> None:
        if not self.run.output.strip():
            self._append_answer_text(_EMPTY_SUCCESS_DIAGNOSTIC)
        if self.run.frame_id:
            portal_store.finish_frame(self.run.frame_id, status="completed", output=self.run.output, run_id=self.run.id)

    def fail_process_exit(self, message: str) -> None:
        if self.run.frame_id:
            portal_store.finish_frame(self.run.frame_id, status="failed", output=self.run.output, error=message, run_id=self.run.id)

    def pause_for_permission(self) -> None:
        if self.run.frame_id:
            portal_store.finish_frame(
                self.run.frame_id,
                status="needs_input",
                output=self.run.output,
                run_id=self.run.id,
            )

    def record_internal_error(self, message: str) -> None:
        event: JsonObject = {"type": "error", "name": "host_agent_internal_error", "message": message}
        self.visible_streamed_content = True
        if self.run.frame_id:
            try:
                portal_store.append_message(self.run.frame_id, role="tool", event=event, run_id=self.run.id)
            except Exception:
                pass
        try:
            self.run.emit("agent", event)
        except Exception:
            pass

    def fail_internal(self, message: str) -> None:
        if self.run.frame_id:
            try:
                portal_store.finish_frame(self.run.frame_id, status="failed", output=self.run.output, error=message, run_id=self.run.id)
            except Exception:
                pass

    def _append_answer_text(self, delta: str) -> None:
        if delta.strip():
            self.visible_streamed_content = True
        self.run.output += delta
        if self.run.frame_id:
            portal_store.upsert_assistant_message(
                self.run.frame_id,
                run_id=self.run.id,
                text=self.run.output,
                stream_status="streaming",
            )
        self.run.emit("agent", {"type": "text_delta", "delta": delta})

    def _remember_tool_call(self, event: JsonObject) -> None:
        if event.get("type") != "tool_call":
            return
        tool_id = str(event.get("id") or "").strip()
        tool_name = str(event.get("name") or "").strip()
        if tool_id and tool_name:
            self._tool_names_by_id[tool_id] = tool_name
            tool_input = event.get("input")
            self._tool_calls_by_id[tool_id] = {
                "name": tool_name,
                "input": dict(tool_input) if isinstance(tool_input, dict) else {},
            }

    def _bind_created_lab_investigation(self, event: JsonObject) -> None:
        project_id = str(self.run.project_id or "").strip()
        frame_id = str(self.run.frame_id or "").strip()
        tool_id = str(event.get("id") or "").strip()
        call = self._tool_calls_by_id.pop(tool_id, {}) if tool_id else {}
        name = str(event.get("name") or call.get("name") or "").strip()
        tool_input = call.get("input")
        invoked_operation = (
            str(tool_input.get("tool") or "").strip()
            if isinstance(tool_input, dict)
            else ""
        )
        if (
            not project_id
            or not frame_id
            or name
            not in {
                "genomi.genomi.invoke",
                "genomi.invoke",
                "mcp__genomi__genomi_invoke",
            }
            or invoked_operation != "lab.create_investigation"
        ):
            return
        investigation_id = _lab_investigation_id_from_result(
            event.get("payload", event.get("content"))
        )
        if not investigation_id:
            return
        current_binding = portal_genomilab.project_binding(project_id)
        if (
            isinstance(current_binding, dict)
            and str(current_binding.get("frame_id") or "") == frame_id
        ):
            # The first Lab investigation created in a conversation is the
            # patient-facing investigation. Public-only research sidecars may
            # be created later in that same conversation, but must not replace
            # its canonical continuation target.
            return
        try:
            portal_genomilab.bind_investigation(
                project_id,
                investigation_id=investigation_id,
                frame_id=frame_id,
            )
        except (portal_genomilab.PortalGenomiLabError, OSError, ValueError):
            # A result that cannot be verified against this project's canonical
            # user/session boundary is never persisted as a portal binding.
            return

    def _completed_workspace_write(self, event: JsonObject) -> bool:
        if event.get("type") != "tool_result" or event.get("isError"):
            return False
        tool_id = str(event.get("id") or "").strip()
        tool_name = str(event.get("name") or "").strip()
        if not tool_name and tool_id:
            tool_name = self._tool_names_by_id.pop(tool_id, "")
        return tool_name in {"Write", "Edit"}


def _lab_investigation_id_from_result(value: object, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if isinstance(value, str):
        try:
            return _lab_investigation_id_from_result(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return ""
    if isinstance(value, list):
        for item in value:
            investigation_id = _lab_investigation_id_from_result(item, depth + 1)
            if investigation_id:
                return investigation_id
        return ""
    if not isinstance(value, dict):
        return ""
    investigation = value.get("investigation")
    if isinstance(investigation, dict):
        investigation_id = str(investigation.get("investigation_id") or "").strip()
        if investigation_id:
            return investigation_id
    for key in (
        "structuredContent",
        "structured_content",
        "result",
        "payload",
        "content",
        "text",
    ):
        if key not in value:
            continue
        investigation_id = _lab_investigation_id_from_result(value[key], depth + 1)
        if investigation_id:
            return investigation_id
    return ""


class ConversationReviewRunPresentation(HostAgentRunPresentation):
    def handle_agent_event(self, event: JsonObject) -> None:
        event = _event_with_permission_request(event)
        event_type = str(event.get("type") or "")
        if event_type == "text_delta":
            self.run.output += str(event.get("delta") or "")
            return
        if event_type in {"tool_call", "tool_result", "error", "diagnostic"}:
            self.run.emit("agent", event)

    def handle_plain_text_fallback(self, text: str) -> None:
        if text:
            self.run.output += text

    def complete_success(self) -> None:
        review = portal_store.complete_frame_review(
            str(self.run.frame_id or ""),
            review_run_id=self.run.id,
            output=self.run.output,
        )
        if review is None:
            raise RuntimeError("Conversation review could not be persisted.")
        self.run.emit("review", {"review": review})

    def fail_process_exit(self, message: str) -> None:
        self._fail_review(message)

    def record_internal_error(self, message: str) -> None:
        self.run.emit("agent", {"type": "error", "name": "reviewer_internal_error", "message": message})
        self._fail_review(message)

    def fail_internal(self, message: str) -> None:
        self._fail_review(message)

    def _fail_review(self, message: str) -> None:
        portal_store.fail_frame_review(
            str(self.run.frame_id or ""),
            review_run_id=self.run.id,
            error=message,
        )


def _run_presentation(run: PortalRun) -> HostAgentRunPresentation:
    if run.kind == "conversation_review":
        return ConversationReviewRunPresentation(run)
    return HostAgentRunPresentation(run)


def _event_with_permission_request(event: JsonObject) -> JsonObject:
    event_type = str(event.get("type") or "")
    if event_type not in {"tool_result", "error"} or isinstance(event.get("permission_request"), dict):
        return event
    permission = portal_agents.permission_request_from_message(
        str(event.get("content") or event.get("message") or "")
    )
    return {**event, "permission_request": permission} if permission else event


def run_agent(run: PortalRun) -> None:
    agent_id = str(run.agent_id or "")
    presentation = _run_presentation(run)
    run.status = "running"
    run.emit(
        "start",
        {
            "status": "running",
            "agentId": agent_id,
            "workspace": portal_workspaces.run_workspace_metadata(run.project_id),
        },
    )
    if run.frame_id and run.kind != "conversation_review":
        portal_store.attach_run(run.frame_id, run_id=run.id, agent_id=agent_id)
    command = portal_agents.agent_invocation(agent_id, approved_tools=run.approved_tools)
    if command is None:
        message = f"Unsupported or unavailable agent: {agent_id}"
        run.emit("agent", {"type": "error", "message": message})
        presentation.fail_process_exit(message)
        run.finish("failed", error=message)
        return
    prompt = _run_prompt(run)
    try:
        presentation.emit_diagnostic("spawn_agent", agent_id=agent_id)
    except Exception as exc:
        message = f"Host-agent stream failed: {exc}"
        run.error = message
        presentation.fail_internal(message)
        run.finish("failed", error=message)
        return
    try:
        cwd = _run_working_directory(run)
        workspace_snapshot = portal_workspace_files.workspace_file_snapshot(cwd) if run.project_id else {}
        presentation.configure_workspace_tracking(cwd, workspace_snapshot)
        environment = _run_environment(run.project_id, run.frame_id)
        if agent_id == "codex" and Path(command[0]).name == "codex":
            command = [
                *command,
                *portal_codex_runtime.exec_config_args(environment),
            ]
        use_codex_app_server = agent_id == "codex" and Path(command[0]).name == "codex"
        try:
            process = _spawn_agent_process(
                [command[0], "app-server"] if use_codex_app_server else command,
                cwd=cwd,
                environment=environment,
            )
        except OSError as exc:
            if not use_codex_app_server:
                raise
            presentation.emit_diagnostic(
                "codex_app_server_fallback",
                agent_id=agent_id,
                message=str(exc),
            )
            use_codex_app_server = False
            process = _spawn_agent_process(command, cwd=cwd, environment=environment)
    except Exception as exc:
        run.emit("agent", {"type": "error", "message": str(exc)})
        presentation.fail_process_exit(str(exc))
        run.finish("failed", error=str(exc))
        return
    run.process = process
    stderr_queue: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_read_stderr, args=(process, stderr_queue), daemon=True).start()
    code: int | None = None
    try:
        try:
            if use_codex_app_server:
                try:
                    _consume_codex_app_server(
                        process,
                        prompt,
                        cwd,
                        presentation,
                        environment,
                    )
                    code = 0
                except portal_codex_app_server.CodexAppServerUnavailable as exc:
                    _terminate_process(process)
                    presentation.emit_diagnostic(
                        "codex_app_server_fallback",
                        agent_id=agent_id,
                        message=str(exc),
                    )
                    process = _spawn_agent_process(command, cwd=cwd, environment=environment)
                    run.process = process
                    stderr_queue = queue.Queue()
                    threading.Thread(target=_read_stderr, args=(process, stderr_queue), daemon=True).start()
                    code = _consume_exec_stream(process, agent_id, prompt, presentation)
            else:
                code = _consume_exec_stream(process, agent_id, prompt, presentation)
        finally:
            presentation.drain_stderr(stderr_queue)
    except Exception as exc:
        _terminalize_internal_exception(run, presentation, process, exc)
        return
    if run.status in {"canceled", "awaiting_permission"}:
        return
    try:
        if presentation.permission_request is not None:
            presentation.pause_for_permission()
            run.finish("awaiting_permission")
        elif code == 0:
            presentation.complete_success()
            if run.kind != "conversation_review":
                presentation.materialize_workspace_files()
            run.finish("succeeded")
        else:
            message = f"{agent_id} exited with code {code}"
            if run.error:
                message = f"{message}: {run.error}"
            presentation.fail_process_exit(message)
            run.finish("failed", error=message)
    except Exception as exc:
        _terminalize_internal_exception(run, presentation, process, exc)


def _spawn_agent_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd),
        env=environment,
        bufsize=1,
    )


def _consume_codex_app_server(
    process: subprocess.Popen[str],
    prompt: str,
    cwd: Path,
    presentation: HostAgentRunPresentation,
    environment: dict[str, str],
) -> None:
    if process.stdin is None or process.stdout is None:
        raise portal_codex_app_server.CodexAppServerUnavailable(
            "Codex app-server did not expose stdio"
        )
    session = portal_codex_app_server.CodexAppServerSession(
        stdin=process.stdin,
        stdout=process.stdout,
        on_event=presentation.handle_agent_event,
    )
    session.run(
        prompt=prompt,
        cwd=str(cwd),
        genomi_mcp_server=portal_codex_runtime.genomi_mcp_server_config(
            environment
        ),
    )
    _terminate_process(process)


def _consume_exec_stream(
    process: subprocess.Popen[str],
    agent_id: str,
    prompt: str,
    presentation: HostAgentRunPresentation,
) -> int:
    if process.stdin:
        process.stdin.write(prompt)
        process.stdin.close()
    assert process.stdout is not None
    for line in process.stdout:
        parsed_line = portal_agents.parse_agent_line(agent_id, line)
        if parsed_line.events:
            for event in parsed_line.events:
                presentation.handle_agent_event(event)
        elif parsed_line.kind == "plain_text_fallback":
            presentation.handle_plain_text_fallback(parsed_line.stdout or line)
    return process.wait()


def _run_working_directory(run: PortalRun) -> Path:
    if run.project_id:
        return portal_workspaces.ensure_project_workspace(run.project_id)
    return Path.cwd()


def _run_prompt(run: PortalRun) -> str:
    if run.kind == "conversation_review":
        return portal_conversation_reviews.review_prompt(run.conversation_history)
    return compose_prompt(
        run.message,
        selected_evidence=run.selected_evidence,
        conversation_history=run.conversation_history,
        genome_context_mode=run.genome_context_mode,
        active_context=run.active_context,
        project_id=run.project_id,
    )


def _emit_workspace_file_artifacts(
    run: PortalRun,
    presentation: HostAgentRunPresentation,
    cwd: Path,
    before: portal_workspace_files.WorkspaceSnapshot,
) -> portal_workspace_files.WorkspaceSnapshot:
    if not run.project_id:
        return before
    try:
        artifacts = portal_workspace_files.materialize_run_workspace_files(
            project_id=run.project_id,
            frame_id=run.frame_id,
            run_id=run.id,
            workspace=cwd,
            before=before,
        )
    except Exception as exc:
        presentation.emit_diagnostic("workspace_file_import_failed", message=str(exc))
        return before
    for artifact in artifacts:
        event = run.emit("artifact", {"artifact": portal_store.public_artifact_summary(artifact)})
        portal_store.attach_artifact_producing_event(
            str(artifact.get("id") or ""),
            run_id=run.id,
            event_id=event.id,
        )
    return portal_workspace_files.workspace_file_snapshot(cwd)


def cancel_run(run: PortalRun) -> None:
    if run.status in portal_run_events.TERMINAL_RUN_STATUSES:
        return
    run.status = "canceled"
    if run.process and run.process.poll() is None:
        try:
            run.process.terminate()
        except Exception:
            pass
    if run.frame_id and run.kind == "conversation_review":
        portal_store.fail_frame_review(
            run.frame_id,
            review_run_id=run.id,
            error="Review canceled.",
        )
    elif run.frame_id:
        portal_store.finish_frame(run.frame_id, status="canceled", output=run.output, error="Run canceled.", run_id=run.id)
    run.finish("canceled")


def pause_run_for_permission(run: PortalRun) -> None:
    if run.status in portal_run_events.TERMINAL_RUN_STATUSES:
        return
    run.status = "awaiting_permission"
    if run.process and run.process.poll() is None:
        _terminate_process(run.process)
    if run.frame_id:
        portal_store.finish_frame(
            run.frame_id,
            status="needs_input",
            output=run.output,
            run_id=run.id,
        )
    run.finish("awaiting_permission")


def compose_prompt(
    message: str,
    *,
    selected_evidence: list[JsonObject] | None = None,
    conversation_history: list[JsonObject] | None = None,
    genome_context_mode: str | None = None,
    active_context: JsonObject | None = None,
    project_id: str | None = None,
) -> str:
    context_section = portal_context.prompt_context_section(project_id)
    history_section = portal_turns.conversation_history_prompt_section(conversation_history)
    genome_boundary_section = _genome_context_mode_prompt_section(genome_context_mode)
    active_context_section = portal_active_context.active_context_prompt_section(active_context)
    workspace_section = portal_workspaces.project_workspace_prompt_section(project_id)
    evidence_section = portal_turns.selected_evidence_prompt_section(selected_evidence)
    lab_skill_section = portal_lab_skill_context.prompt_section()
    lab_resume_section = _lab_resume_prompt_section(project_id)
    return (
        "You are operating inside GenomiLab, a local-first genomics workspace.\n"
        "Use the Genomi MCP tools already installed in this assistant session when evidence is needed.\n"
        "When the underlying intent requires durable patient-specific synthesis across observations or data sources, competing explanations, evidence revised over time, bounded specialist research, or a versioned brief, use the focused Lab guidance already included below and invoke canonical lab.* operations through genomi.invoke in this same conversation. Decide this semantically; never use keyword, phrase, prompt-template, or disease-name matching. Do not start another orchestration thread or Lab runner.\n"
        "Answer from evidence. Preserve Genomi privacy boundaries. Use informational medical language and recommend clinical confirmation for clinical decisions.\n\n"
        f"{lab_skill_section}"
        f"{lab_resume_section}"
        f"{context_section}"
        f"{history_section}"
        f"{genome_boundary_section}"
        f"{active_context_section}"
        f"{workspace_section}"
        f"{evidence_section}"
        "# User request\n"
        f"{message}\n"
    )


def _lab_resume_prompt_section(project_id: str | None) -> str:
    if not project_id:
        return ""
    try:
        projection = portal_genomilab.project_resume_context(project_id)
    except (portal_genomilab.PortalGenomiLabError, OSError, ValueError):
        return ""
    investigation = projection.get("active_investigation")
    if not isinstance(investigation, dict):
        return ""

    def clean(value: object) -> str:
        return " ".join(portal_turns.prompt_safe_text(str(value or "")).split())[:300]

    investigation_id = clean(investigation.get("investigation_id"))
    if not investigation_id:
        return ""
    lines = [
        "# Current Lab continuation state",
        "This compact identifier and lifecycle summary comes from the canonical Lab store. Resume this investigation with canonical lab.* operations; do not inspect portal logs, files, or shell history to recover Lab state. Do not create a replacement investigation unless the user asks to start a new one.",
        f"- Active investigation: {investigation_id}",
        f"- Investigation status: {clean(investigation.get('status'))}",
        f"- Expected domain revision: {clean(investigation.get('domain_revision'))}",
    ]
    latest_cycle = investigation.get("latest_cycle")
    if isinstance(latest_cycle, dict) and latest_cycle.get("cycle_id"):
        lines.append(
            f"- Latest cycle: {clean(latest_cycle.get('cycle_id'))} (ordinal {clean(latest_cycle.get('ordinal'))})"
        )
    assignments = investigation.get("specialist_assignments")
    if isinstance(assignments, list) and assignments:
        lines.append("- Specialist assignments:")
        for item in assignments:
            if not isinstance(item, dict):
                continue
            parts = [
                clean(item.get("specialist_assignment_id")),
                f"state={clean(item.get('state'))}",
                f"assignment_revision={clean(item.get('revision'))}",
                f"cycle={clean(item.get('cycle_id'))}",
                f"brief={clean(item.get('specialist_brief_id'))}",
            ]
            if item.get("specialist_analysis_id"):
                parts.append(f"analysis={clean(item.get('specialist_analysis_id'))}")
            lines.append("  - " + " | ".join(part for part in parts if part))
    hypotheses = investigation.get("latest_hypothesis_versions")
    if isinstance(hypotheses, list) and hypotheses:
        lines.append("- Current hypothesis versions:")
        for item in hypotheses:
            if not isinstance(item, dict):
                continue
            lines.append(
                "  - "
                + " | ".join(
                    (
                        clean(item.get("logical_hypothesis_id")),
                        f"version_id={clean(item.get('hypothesis_version_id'))}",
                        f"version={clean(item.get('version'))}",
                        f"status={clean(item.get('status'))}",
                        f"cycle={clean(item.get('cycle_id'))}",
                        f"evidence_snapshot={clean(item.get('evidence_snapshot_id')) or 'none'}",
                    )
                )
            )
    latest_evidence = investigation.get("latest_evidence_snapshot")
    if isinstance(latest_evidence, dict) and latest_evidence.get(
        "evidence_snapshot_id"
    ):
        lines.append(
            f"- Latest evidence snapshot: {clean(latest_evidence.get('evidence_snapshot_id'))} (version {clean(latest_evidence.get('version'))})"
        )
    latest_brief = investigation.get("latest_brief_version")
    if isinstance(latest_brief, dict) and latest_brief.get("brief_version_id"):
        lines.append(
            f"- Latest doctor brief: {clean(latest_brief.get('brief_version_id'))} (version {clean(latest_brief.get('version'))})"
        )
    return "\n".join(lines) + "\n\n"


def _genome_context_mode_prompt_section(mode: str | None) -> str:
    clean = str(mode or "").strip().lower().replace("_", "-")
    if clean in {"public", "public-only", "public-sources"}:
        return (
            "# Genome context boundary\n"
            "The user selected Public sources only for this turn. Do not use the active genome, imported Active Genome Index, or sample-specific Genomi context unless the user explicitly attached genome facts in this message. If the question would require personal genome evidence, explain that this turn is public-only and ask before using the active genome.\n\n"
        )
    return (
        "# Genome context boundary\n"
        "Use public evidence first. Use the approved active genome only when it is directly relevant to the user's request, and keep public evidence separate from sample-specific evidence.\n\n"
    )


def _run_environment(project_id: str | None, frame_id: str | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    if project_id:
        environment.update(portal_project_genomes.agent_environment(project_id))
        # Portal conversations are the durable user-facing session boundary.
        # Host CLIs may be recreated for each turn, but Genomi and GenomiLab
        # approvals must remain scoped to the same project/frame rather than to
        # a transient child-process identifier.
        environment[GENOMI_SESSION_ENV] = (
            f"portal:{project_id}:{frame_id}" if frame_id else f"portal:{project_id}"
        )
        environment[GENOMILAB_PORTAL_PROJECT_ENV] = project_id
        if frame_id:
            environment[GENOMILAB_PORTAL_FRAME_ENV] = frame_id
    return environment


def _read_stderr(process: subprocess.Popen[str], stderr_queue: queue.Queue[str]) -> None:
    if process.stderr is None:
        return
    for line in process.stderr:
        stderr_queue.put(line)


def _terminalize_internal_exception(
    run: PortalRun,
    presentation: HostAgentRunPresentation,
    process: subprocess.Popen[str],
    exc: Exception,
) -> None:
    if run.status == "canceled":
        return
    message = f"Host-agent stream failed: {exc}"
    run.error = message
    _terminate_process(process)
    presentation.record_internal_error(message)
    presentation.fail_internal(message)
    run.finish("failed", error=message)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        running = process.poll() is None
    except Exception:
        running = False
    if not running:
        return
    try:
        process.terminate()
    except Exception:
        return
    try:
        process.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        process.kill()
        process.wait(timeout=2)
    except Exception:
        pass
