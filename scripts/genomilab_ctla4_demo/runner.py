"""Orchestrator for the modular synthetic CTLA4 recording journey."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .brief import BriefMixin
from .constants import JsonObject
from .followup import FollowupMixin
from .round_one import RoundOneMixin
from .round_three import RoundThreeMixin
from .round_two import RoundTwoMixin
from .runtime import RuntimeMixin
from .support import FlowSupportMixin


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class DemoRun(
    RuntimeMixin,
    FlowSupportMixin,
    RoundOneMixin,
    FollowupMixin,
    RoundTwoMixin,
    RoundThreeMixin,
    BriefMixin,
):
    run_dir: Path
    step_delay: float
    wait_for_viewer: bool
    viewer_timeout: float
    port: int
    dry_run: bool
    fixture_mode: bool
    capture_handshake: bool = False
    capture_timeout: float = 60.0
    genomi_home: Path = field(init=False)
    timeline_path: Path = field(init=False)
    viewer_ready_path: Path = field(init=False)
    launch_url_path: Path = field(init=False)
    manifest_path: Path = field(init=False)
    report_path: Path = field(init=False)
    service: Any = field(init=False, default=None)
    server: Any = field(init=False, default=None)
    investigation_id: str = field(init=False, default="")
    observation_ids: dict[str, str] = field(init=False, default_factory=dict)
    hypothesis_ids: dict[str, str] = field(init=False, default_factory=dict)
    operation_results: dict[str, JsonObject] = field(init=False, default_factory=dict)
    timeline_event_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.run_dir = self.run_dir.resolve()
        self.genomi_home = self.run_dir / "private-genomi-home"
        self.timeline_path = self.run_dir / "timeline.jsonl"
        self.viewer_ready_path = self.run_dir / "viewer-ready"
        self.launch_url_path = self.run_dir / "launch-url.txt"
        self.manifest_path = self.run_dir / "run-manifest.json"
        self.report_path = self.run_dir / "final-report.json"

    def emit(
        self,
        stage: str,
        title: str,
        detail: str,
        *,
        scroll_target: str = "#investigation-detail",
        pause: bool = True,
    ) -> None:
        event = {
            "at": _now(),
            "stage": stage,
            "title": title,
            "detail": detail,
            "scroll_target": scroll_target,
        }
        with self.timeline_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        self.timeline_event_count += 1
        print(f"[{stage}] {title}: {detail}", flush=True)
        if self.capture_handshake and self.viewer_ready_path.exists():
            acknowledgement = (
                self.run_dir
                / "capture-acks"
                / f"event-{self.timeline_event_count:04d}.seen"
            )
            deadline = time.monotonic() + self.capture_timeout
            while time.monotonic() < deadline:
                if acknowledgement.exists():
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError(
                    f"capture did not acknowledge timeline event "
                    f"{self.timeline_event_count} within {self.capture_timeout:g}s"
                )
        if pause and self.step_delay > 0:
            time.sleep(self.step_delay)

    def run_scenario(self) -> JsonObject:
        self.wait_for_viewer_signal()
        self.emit(
            "patient_question_visible",
            "The patient starts with one plain-language question",
            "The investigation opens from the patient's history of low platelets, Crohn disease, recurrent infections, and a medication concern.",
            scroll_target="#investigation-detail",
        )
        self._round_one()
        self._followup_a()
        self._round_two()
        self._followup_b()
        self._request_followup_c()
        self._followup_c()
        self._round_three()
        brief = self._publish_brief()
        self.emit(
            "clinician_questions_ready",
            "Case-specific questions for the doctor are ready",
            "The brief now carries four questions grounded in the chronology, function repeats, healthy carrier, and unresolved alternatives.",
            scroll_target="#brief-clinician-questions",
        )
        report = self._final_report(brief)
        self.report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.emit(
            "demo_complete",
            "Doctor brief is ready",
            "The brief preserves Q76H as a VUS and asks case-specific clinician questions.",
            scroll_target="#brief-export-actions",
            pause=False,
        )
        return report
