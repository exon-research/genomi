"""Public facade for the host-neutral GenomiLab harness protocol.

The implementation is split by ownership: transport safety, typed contracts,
event replay, lifecycle semantics, simulated conformance, and installed-host
integration.  No module in this boundary opens the GenomiLab domain store.
"""

from .harness_adapter import HarnessAdapter, HarnessDynamicToolCall
from .harness_background import (
    HarnessJobIdentity,
    HarnessJobState,
    HarnessJobSubmission,
)
from .harness_codex import InstalledCodexAppServerAdapter
from .harness_events import (
    AgentProgressPayload,
    AgentStartedPayload,
    ArtifactReference,
    CancellationResult,
    EventAcceptance,
    EventReplay,
    HarnessEvent,
    HarnessEventBuffer,
    HarnessProtocolError,
    HarnessResponse,
    TaskRunResult,
)
from .harness_simulated import SimulatedHarnessAdapter
from .harness_transport import PROTOCOL_VERSION, safe_json_dumps, safe_json_value
from .harness_types import (
    BindingStatus,
    CancelTaskWorkPayload,
    CancellationOutcome,
    HarnessArtifactKind,
    HarnessCapabilityManifest,
    HarnessCommand,
    HarnessErrorCode,
    HarnessEventKind,
    HarnessEventStatus,
    HarnessOperation,
    ReplayStatus,
    ReplaceTaskBindingPayload,
    ResumeTaskRunPayload,
    SendTaskMessagePayload,
    StartTaskRunPayload,
)

__all__ = [
    "AgentProgressPayload",
    "AgentStartedPayload",
    "ArtifactReference",
    "BindingStatus",
    "CancelTaskWorkPayload",
    "CancellationOutcome",
    "CancellationResult",
    "EventAcceptance",
    "EventReplay",
    "HarnessAdapter",
    "HarnessDynamicToolCall",
    "HarnessArtifactKind",
    "HarnessCapabilityManifest",
    "HarnessCommand",
    "HarnessErrorCode",
    "HarnessEvent",
    "HarnessEventBuffer",
    "HarnessEventKind",
    "HarnessEventStatus",
    "HarnessJobIdentity",
    "HarnessJobState",
    "HarnessJobSubmission",
    "HarnessOperation",
    "HarnessProtocolError",
    "HarnessResponse",
    "InstalledCodexAppServerAdapter",
    "PROTOCOL_VERSION",
    "ReplayStatus",
    "ReplaceTaskBindingPayload",
    "ResumeTaskRunPayload",
    "SendTaskMessagePayload",
    "SimulatedHarnessAdapter",
    "StartTaskRunPayload",
    "TaskRunResult",
    "safe_json_dumps",
    "safe_json_value",
]
