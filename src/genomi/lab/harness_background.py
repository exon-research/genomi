"""Host-neutral handles for long-running harness work.

The installed harness owns the actual task and turn.  These objects expose only
the minimum identity and lifecycle state GenomiLab needs to remain responsive,
replay progress, and request a confirmed cancellation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .harness_events import HarnessResponse
from .harness_transport import required_identifier


class HarnessJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HarnessJobIdentity:
    job_id: str
    task_id: str
    run_id: str

    def __post_init__(self) -> None:
        for name in ("job_id", "task_id", "run_id"):
            object.__setattr__(
                self, name, required_identifier(getattr(self, name), name)
            )


@dataclass(frozen=True, slots=True)
class HarnessJobSubmission:
    job_id: str
    state: HarnessJobState
    task_id: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", required_identifier(self.job_id, "job_id"))
        object.__setattr__(self, "state", HarnessJobState(self.state))
        if (self.task_id is None) != (self.run_id is None):
            raise ValueError("task_id and run_id must be supplied together")
        for name in ("task_id", "run_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, required_identifier(value, name))

    def to_dict(self) -> dict[str, str | None]:
        return {
            "job_id": self.job_id,
            "state": self.state.value,
            "task_id": self.task_id,
            "run_id": self.run_id,
        }


HarnessIdentityCallback = Callable[[HarnessJobIdentity], None]
HarnessSubmissionCallback = Callable[[HarnessJobSubmission], None]


class HarnessCompletionCallback(Protocol):
    """Durably acknowledge a terminal result or raise without acknowledging it."""

    def __call__(
        self,
        job_id: str,
        job_state: HarnessJobState,
        response: HarnessResponse,
    ) -> None: ...
