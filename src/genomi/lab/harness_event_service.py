"""Harness event replay, long-polling, and durable event projection."""

from __future__ import annotations

from .harness import (
    HarnessArtifactKind,
    HarnessEvent,
    HarnessEventKind,
    ReplayStatus,
)
from .harness_application_contract import HarnessApplication
from .models import JsonObject
from .service_errors import LabError


class HarnessEventApplicationMixin:
    """Coordinate harness event transport without weakening user authority."""

    def replay_investigation_events(
        self: HarnessApplication,
        investigation_id: str,
        *,
        after_sequence: int = 0,
    ) -> JsonObject:
        self.investigation(investigation_id)
        self._commit_pending_harness_events(investigation_id)
        return {
            "status": "events",
            "events": self.store.replay_harness_events(
                investigation_id, after_sequence=max(0, int(after_sequence))
            ),
        }

    def stream_investigation_events(
        self: HarnessApplication,
        investigation_id: str,
        *,
        after_sequence: int,
        timeout_seconds: float = 20.0,
    ) -> JsonObject:
        """Long-poll without holding patient-authority locks during the wait."""

        after = max(0, int(after_sequence))
        prepared = self._run_current_user_operation(
            self._prepare_investigation_event_stream,
            investigation_id,
            after_sequence=after,
        )
        events = list(prepared["events"])
        if events:
            return dict(prepared["response"])

        # Adapter waits are deliberately outside the global operation lock, the
        # Genomi context-authority lock, and the store authority transaction.
        # No patient data is returned from this phase.  Finalization below
        # revalidates the exact authority epoch before reading or committing.
        self.harness_adapter.wait_for_events(
            investigation_id,
            after_cursor=int(prepared["transport_cursor"]),
            timeout_seconds=min(25.0, max(0.0, float(timeout_seconds))),
        )
        return self._run_current_user_operation(
            self._finalize_investigation_event_stream,
            investigation_id,
            after_sequence=after,
            expected_user_id=str(prepared["user_id"]),
            expected_authority_epoch=int(prepared["authority_epoch"]),
        )

    def _prepare_investigation_event_stream(
        self: HarnessApplication,
        investigation_id: str,
        *,
        after_sequence: int,
    ) -> JsonObject:
        self.investigation(investigation_id)
        _, user_id = self._current_context()
        self._commit_pending_harness_events(investigation_id)
        events = self.store.replay_harness_events(
            investigation_id, after_sequence=after_sequence
        )
        return {
            "user_id": user_id,
            "authority_epoch": int(self._current_user_authority_epoch),
            "transport_cursor": self._latest_transport_cursor(investigation_id),
            "events": events,
            "response": self._event_stream_response(
                investigation_id,
                after_sequence=after_sequence,
                events=events,
            ),
        }

    def _finalize_investigation_event_stream(
        self: HarnessApplication,
        investigation_id: str,
        *,
        after_sequence: int,
        expected_user_id: str,
        expected_authority_epoch: int,
    ) -> JsonObject:
        _, current_user_id = self._current_context()
        if current_user_id != expected_user_id or int(
            self._current_user_authority_epoch
        ) != int(expected_authority_epoch):
            raise LabError(
                "genomi_user_changed",
                (
                    "The current Genomi user changed while this request was in "
                    "progress. No in-flight result was returned or committed."
                ),
                http_status=409,
            )
        self.investigation(investigation_id)
        self._commit_pending_harness_events(investigation_id)
        events = self.store.replay_harness_events(
            investigation_id, after_sequence=after_sequence
        )
        return self._event_stream_response(
            investigation_id,
            after_sequence=after_sequence,
            events=events,
        )

    def _event_stream_response(
        self: HarnessApplication,
        investigation_id: str,
        *,
        after_sequence: int,
        events: list[JsonObject],
    ) -> JsonObject:
        job = self.store.active_harness_job(investigation_id)
        return {
            "status": "events",
            "events": events,
            "after_sequence": after_sequence,
            "latest_sequence": max(
                (int(event["sequence"]) for event in events),
                default=self._latest_domain_event_sequence(investigation_id),
            ),
            "job": job,
        }

    def _latest_transport_cursor(
        self: HarnessApplication, investigation_id: str
    ) -> int:
        events = self.store.replay_harness_events(investigation_id)
        cursors = [
            int((event.get("payload") or {}).get("cursor") or 0)
            for event in events
            if isinstance(event.get("payload"), dict)
            and (event.get("payload") or {}).get("host_id")
            == self.harness_adapter.manifest.adapter_id
        ]
        return max(cursors, default=0)

    def _latest_domain_event_sequence(
        self: HarnessApplication, investigation_id: str
    ) -> int:
        events = self.store.replay_harness_events(investigation_id)
        return max((int(event["sequence"]) for event in events), default=0)

    @staticmethod
    def _persistable_harness_event(event: HarnessEvent) -> JsonObject:
        """Keep unvalidated host artifacts out of the durable event stream.

        Artifact proposal/completion notifications are emitted by a harness before
        GenomiLab has applied its canonical domain validation.  Their durable event
        form is therefore an opaque notification only.  Rebuild that payload from a
        strict allowlist so legacy or custom adapters cannot smuggle a proposed
        artifact through event replay.
        """

        payload = event.to_dict()
        if event.kind not in {
            HarnessEventKind.PLAN_PROPOSED,
            HarnessEventKind.CAPABILITY_EXECUTION_COMPLETED,
            HarnessEventKind.BRIEF_COMPLETED,
        }:
            return payload
        notification: JsonObject = {
            "artifact_kind": {
                HarnessEventKind.PLAN_PROPOSED: HarnessArtifactKind.PLAN.value,
                HarnessEventKind.CAPABILITY_EXECUTION_COMPLETED: (
                    HarnessArtifactKind.EXECUTION_REPORT.value
                ),
                HarnessEventKind.BRIEF_COMPLETED: HarnessArtifactKind.BRIEF_DRAFT.value,
            }[event.kind]
        }
        matching_reference = next(
            (
                reference
                for reference in event.proposed_artifacts
                if reference.kind.value == notification["artifact_kind"]
            ),
            None,
        )
        if matching_reference is not None:
            notification["artifact_reference"] = matching_reference.to_dict()
        payload["payload"] = notification
        return payload

    def _commit_pending_harness_events(
        self: HarnessApplication, investigation_id: str
    ) -> list[JsonObject]:
        binding = self.store.active_harness_binding(investigation_id)
        if binding is None:
            return []
        replay = self.harness_adapter.replay_events(
            investigation_id,
            after_cursor=self._latest_transport_cursor(investigation_id),
        )
        if replay.status != ReplayStatus.EVENTS:
            return []
        return [
            self.store.commit_harness_event(
                investigation_id,
                str(binding["binding_id"]),
                event_id=event.event_id,
                event_type=event.kind.value,
                payload=self._persistable_harness_event(event),
            )
            for event in replay.events
        ]


__all__ = ["HarnessEventApplicationMixin"]
