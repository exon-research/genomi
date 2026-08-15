"""Authorization boundary for installed-harness dynamic capability calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .harness import HarnessAdapter, HarnessDynamicToolCall
from .models import JsonObject
from .store import GenomiLabStore


@dataclass(frozen=True, slots=True)
class HarnessToolBoundary:
    """Validate one host callback before invoking an accepted plan request."""

    store: GenomiLabStore
    session_id: str
    harness_adapter: HarnessAdapter
    current_context: Callable[[], tuple[JsonObject, str]]
    accepted_plan: Callable[[str], JsonObject]
    active_context_receipt: Callable[[JsonObject, JsonObject], JsonObject]
    require_authorized_disclosure: Callable[[str, str, str], JsonObject]
    execute_request: Callable[[str, JsonObject], JsonObject]

    def execute(self, call: object) -> JsonObject:
        if not isinstance(call, HarnessDynamicToolCall):
            raise ValueError("invalid harness dynamic tool call")
        command = self.store.harness_command(call.command_id)
        binding = self.store.active_harness_binding(call.investigation_id)
        job = self.store.harness_job_for_command(call.command_id)
        if (
            not isinstance(command, dict)
            or command.get("investigation_id") != call.investigation_id
            or command.get("workspace_session_id") != self.session_id
            or command.get("command_state") != "dispatching"
            or command.get("operation") != "replace_task_binding"
            or (
                isinstance(job, dict)
                and (
                    job.get("command_id") != call.command_id
                    or job.get("task_id") != call.thread_id
                    or job.get("run_id") != call.turn_id
                    or job.get("job_state") not in {"queued", "running"}
                )
            )
        ):
            raise ValueError(
                "dynamic tool call is not bound to an active harness command"
            )
        if isinstance(job, dict) and (
            not isinstance(binding, dict)
            or binding.get("command_id") != call.command_id
            or binding.get("task_id") != call.thread_id
            or binding.get("run_id") != call.turn_id
        ):
            raise ValueError("dynamic tool call is not bound to its active harness job")
        if job is None and self.harness_adapter.manifest.background_job_attach:
            raise ValueError("dynamic tool call has no durable harness job")
        receipt_id = str(command.get("disclosure_receipt_id") or "")
        if not receipt_id:
            raise ValueError("dynamic tool call has no approved harness disclosure")
        receipt = self.store.outbound_disclosure_receipt(receipt_id)
        investigation = self.accepted_plan(call.investigation_id)
        _, current_user_id = self.current_context()
        if command.get("user_id") != current_user_id:
            raise ValueError(
                "dynamic tool call is not bound to the current Genomi user"
            )
        manifest = self.harness_adapter.capability_manifest()
        self.store.require_outbound_disclosure(
            receipt_id,
            workspace_session_id=self.session_id,
            user_id=current_user_id,
            investigation_id=call.investigation_id,
            recipient_kind="installed_harness",
            recipient_id=manifest.adapter_id,
            purpose=f"{command['operation']} for disease investigation",
            destination=manifest.execution_location,
            data_categories=list(receipt.get("data_categories") or []),
            payload=receipt.get("payload"),
            policy_versions={"harness_protocol": "genomilab.harness.v1"},
        )
        self.require_authorized_disclosure(
            call.investigation_id,
            receipt_id,
            "execute_accepted_plan",
        )
        disclosed = receipt.get("payload")
        approved_context = (
            disclosed.get("approved_context") if isinstance(disclosed, dict) else None
        )
        accepted_plan = (
            approved_context.get("accepted_plan")
            if isinstance(approved_context, dict)
            else None
        )
        current = investigation.get("current_plan_version")
        if (
            not isinstance(accepted_plan, dict)
            or not isinstance(current, dict)
            or accepted_plan.get("plan_version_id") != current.get("plan_version_id")
            or accepted_plan.get("plan_sha256") != current.get("plan_sha256")
            or accepted_plan.get("plan") != current.get("plan")
        ):
            raise ValueError("dynamic tool call is not bound to the exact accepted plan")
        self._require_private_context_authority(
            investigation, approved_context=approved_context
        )
        plan = investigation.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("dynamic tool calls require the current accepted plan")
        requests = [
            request
            for request in plan.get("capability_requests") or []
            if isinstance(request, dict) and request.get("id") == call.request_id
        ]
        if len(requests) != 1 or requests[0].get("capability") != call.capability:
            raise ValueError(
                "dynamic tool identity must exactly match its current plan request"
            )
        if job is None:
            binding = self._bind_synchronous_identity(
                call, disclosed=disclosed, binding=binding
            )
        result = self.execute_request(
            call.investigation_id, {"request_id": call.request_id}
        )
        if result.get("capability") != call.capability:
            raise ValueError(
                "dynamic capability identity does not match the current plan"
            )
        return result

    def _require_private_context_authority(
        self,
        investigation: JsonObject,
        *,
        approved_context: object,
    ) -> None:
        snapshot_id = investigation.get("patient_molecular_snapshot_id")
        if not snapshot_id:
            return
        snapshot = self.store.get_profile_snapshot(str(snapshot_id))
        consent = self.active_context_receipt(investigation, snapshot)
        authority = (
            approved_context.get("private_context_authority")
            if isinstance(approved_context, dict)
            else None
        )
        if (
            not isinstance(authority, dict)
            or authority.get("patient_molecular_snapshot_id") != snapshot_id
            or authority.get("consent_receipt_id")
            != consent.get("consent_receipt_id")
            or consent.get("workspace_session_id") != self.session_id
            or consent.get("revoked_at")
        ):
            raise ValueError(
                "dynamic tool call is not bound to the active molecular context"
            )

    def _bind_synchronous_identity(
        self,
        call: HarnessDynamicToolCall,
        *,
        disclosed: object,
        binding: JsonObject | None,
    ) -> JsonObject:
        command_context = (
            disclosed.get("command_context") if isinstance(disclosed, dict) else None
        )
        if not isinstance(command_context, dict) or not isinstance(binding, dict):
            raise ValueError("synchronous dynamic tool call has no prior harness binding")
        already_bound = (
            binding.get("command_id") == call.command_id
            and binding.get("task_id") == call.thread_id
            and binding.get("run_id") == call.turn_id
        )
        if not already_bound:
            if (
                command_context.get("task_id") != binding.get("task_id")
                or command_context.get("run_id") != binding.get("run_id")
                or command_context.get("current_binding_revision")
                != binding.get("harness_revision")
            ):
                raise ValueError(
                    "synchronous dynamic tool call is not replacing the disclosed binding"
                )
            binding = self.store.bind_harness_task(
                call.investigation_id,
                command_id=call.command_id,
                host_id=self.harness_adapter.manifest.adapter_id,
                task_id=call.thread_id,
                run_id=call.turn_id,
                harness_status="running",
                harness_revision=int(command_context["expected_revision"]) + 1,
            )
        if (
            binding.get("command_id") != call.command_id
            or binding.get("task_id") != call.thread_id
            or binding.get("run_id") != call.turn_id
        ):
            raise ValueError("synchronous dynamic tool identity was not durably bound")
        return binding
