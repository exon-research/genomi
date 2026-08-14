from __future__ import annotations

import queue
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from . import (
    portal_active_context,
    portal_agents,
    portal_context,
    portal_conversation_reviews,
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


class HostAgentRunPresentation:
    def __init__(self, run: PortalRun) -> None:
        self.run = run
        self.visible_streamed_content = False
        self.permission_request: JsonObject | None = None
        self.workspace: Path | None = None
        self.workspace_snapshot: portal_workspace_files.WorkspaceSnapshot = {}
        self._tool_names_by_id: dict[str, str] = {}

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

    def _completed_workspace_write(self, event: JsonObject) -> bool:
        if event.get("type") != "tool_result" or event.get("isError"):
            return False
        tool_id = str(event.get("id") or "").strip()
        tool_name = str(event.get("name") or "").strip()
        if not tool_name and tool_id:
            tool_name = self._tool_names_by_id.pop(tool_id, "")
        return tool_name in {"Write", "Edit"}


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
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd),
            env=_run_environment(run.project_id),
            bufsize=1,
        )
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
            code = process.wait()
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
    return (
        "You are operating inside Genomi Portal, a local-first genomics workspace.\n"
        "Use the Genomi MCP tools already installed in this assistant session when evidence is needed.\n"
        "Answer from evidence. Preserve Genomi privacy boundaries. Use informational medical language and recommend clinical confirmation for clinical decisions.\n\n"
        f"{context_section}"
        f"{history_section}"
        f"{genome_boundary_section}"
        f"{active_context_section}"
        f"{workspace_section}"
        f"{evidence_section}"
        "# User request\n"
        f"{message}\n"
    )


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


def _run_environment(project_id: str | None) -> dict[str, str]:
    environment = dict(os.environ)
    if project_id:
        environment.update(portal_project_genomes.agent_environment(project_id))
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
        pass
