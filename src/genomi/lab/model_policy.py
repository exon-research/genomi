"""Eligibility policy for optional Proto and ESM computation in GenomiLab."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping


class ModelSystem(str, Enum):
    ESM = "esm"
    PROTO = "proto"


class ModelTask(str, Enum):
    EXACT_PROTEIN_ANALYTICAL_ARTIFACT = "exact_protein_analytical_artifact"
    SEQUENCE_DESIGN = "sequence_design"
    DIAGNOSIS = "diagnosis"
    PATHOGENICITY_CLASSIFICATION = "pathogenicity_classification"
    TREATMENT_SELECTION = "treatment_selection"
    TRIAL_ELIGIBILITY = "trial_eligibility"


class ExecutionLocation(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class ModelPolicyState(str, Enum):
    ALLOWED = "allowed"
    REFUSED_PATIENT_SEQUENCE_REMOTE = "refused_patient_sequence_remote"
    REFUSED_PATIENT_WORKFLOW_SEQUENCE_DESIGN = (
        "refused_patient_workflow_sequence_design"
    )
    REFUSED_CLINICAL_DECISION_TASK = "refused_clinical_decision_task"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    OPERATION_NOT_ALLOWLISTED = "operation_not_allowlisted"
    UNSUPPORTED_TASK_FOR_SYSTEM = "unsupported_task_for_system"
    REQUIRES_GROUNDED_EXACT_PROTEIN = "requires_grounded_exact_protein"
    REQUIRES_VALIDATED_DOWNSTREAM_READOUT = (
        "requires_validated_downstream_readout"
    )
    REQUIRES_LOCAL_NETWORK_DISABLED_BACKEND = (
        "requires_local_network_disabled_backend"
    )
    REQUIRES_EXPERT_RESEARCH_MODE = "requires_expert_research_mode"
    TASK_NOT_VALIDATED = "task_not_validated"


_CLINICAL_DECISION_TASKS = frozenset(
    {
        ModelTask.DIAGNOSIS,
        ModelTask.PATHOGENICITY_CLASSIFICATION,
        ModelTask.TREATMENT_SELECTION,
        ModelTask.TRIAL_ELIGIBILITY,
    }
)


def _required_text(value: object, field: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return text


@dataclass(frozen=True)
class ModelRequest:
    system: ModelSystem
    task: ModelTask
    operation: str
    execution_location: ExecutionLocation = ExecutionLocation.LOCAL
    patient_derived_sequence: bool = False
    patient_workflow: bool = True
    grounded_candidate: bool = False
    exact_sequence_or_isoform: bool = False
    interpretation_requested: bool = False
    downstream_readout: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.system, ModelSystem):
            object.__setattr__(self, "system", ModelSystem(self.system))
        if not isinstance(self.task, ModelTask):
            object.__setattr__(self, "task", ModelTask(self.task))
        if not isinstance(self.execution_location, ExecutionLocation):
            object.__setattr__(
                self, "execution_location", ExecutionLocation(self.execution_location)
            )
        object.__setattr__(
            self, "operation", _required_text(self.operation, "operation", 200)
        )
        if self.downstream_readout is not None:
            object.__setattr__(
                self,
                "downstream_readout",
                _required_text(self.downstream_readout, "downstream_readout"),
            )


@dataclass(frozen=True)
class ModelDeployment:
    system: ModelSystem
    available: bool = False
    enabled: bool = False
    allowlisted_operations: frozenset[str] = frozenset()
    local_backend: bool = False
    network_disabled_during_inference: bool = False
    exact_task_validated: bool = False
    expert_research_mode: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.system, ModelSystem):
            object.__setattr__(self, "system", ModelSystem(self.system))
        object.__setattr__(
            self,
            "allowlisted_operations",
            frozenset(
                _required_text(item, "allowlisted_operation", 200)
                for item in self.allowlisted_operations
            ),
        )


@dataclass(frozen=True)
class ModelPolicyDecision:
    state: ModelPolicyState

    @property
    def eligible(self) -> bool:
        return self.state is ModelPolicyState.ALLOWED


def evaluate_model_request(
    request: ModelRequest, deployment: ModelDeployment
) -> ModelPolicyDecision:
    """Evaluate immutable safety refusals before availability or feature gates."""

    if request.system is not deployment.system:
        return ModelPolicyDecision(ModelPolicyState.UNSUPPORTED_TASK_FOR_SYSTEM)
    if (
        request.patient_derived_sequence
        and request.execution_location is ExecutionLocation.REMOTE
    ):
        return ModelPolicyDecision(ModelPolicyState.REFUSED_PATIENT_SEQUENCE_REMOTE)
    if request.patient_workflow and request.task is ModelTask.SEQUENCE_DESIGN:
        return ModelPolicyDecision(
            ModelPolicyState.REFUSED_PATIENT_WORKFLOW_SEQUENCE_DESIGN
        )
    if request.task in _CLINICAL_DECISION_TASKS:
        return ModelPolicyDecision(ModelPolicyState.REFUSED_CLINICAL_DECISION_TASK)
    if not deployment.available:
        return ModelPolicyDecision(ModelPolicyState.UNAVAILABLE)
    if not deployment.enabled:
        return ModelPolicyDecision(ModelPolicyState.DISABLED)
    if request.operation not in deployment.allowlisted_operations:
        return ModelPolicyDecision(ModelPolicyState.OPERATION_NOT_ALLOWLISTED)

    if request.system is ModelSystem.ESM:
        if request.task is not ModelTask.EXACT_PROTEIN_ANALYTICAL_ARTIFACT:
            return ModelPolicyDecision(ModelPolicyState.UNSUPPORTED_TASK_FOR_SYSTEM)
        if not request.grounded_candidate or not request.exact_sequence_or_isoform:
            return ModelPolicyDecision(
                ModelPolicyState.REQUIRES_GROUNDED_EXACT_PROTEIN
            )
        if request.interpretation_requested and not request.downstream_readout:
            return ModelPolicyDecision(
                ModelPolicyState.REQUIRES_VALIDATED_DOWNSTREAM_READOUT
            )
        if not deployment.exact_task_validated:
            return ModelPolicyDecision(ModelPolicyState.TASK_NOT_VALIDATED)

    if request.system is ModelSystem.PROTO:
        if request.task is not ModelTask.SEQUENCE_DESIGN:
            return ModelPolicyDecision(ModelPolicyState.UNSUPPORTED_TASK_FOR_SYSTEM)
        if not deployment.expert_research_mode:
            return ModelPolicyDecision(ModelPolicyState.REQUIRES_EXPERT_RESEARCH_MODE)

    if request.patient_derived_sequence and (
        request.execution_location is not ExecutionLocation.LOCAL
        or not deployment.local_backend
        or not deployment.network_disabled_during_inference
    ):
        return ModelPolicyDecision(
            ModelPolicyState.REQUIRES_LOCAL_NETWORK_DISABLED_BACKEND
        )
    return ModelPolicyDecision(ModelPolicyState.ALLOWED)


ModelRunner = Callable[[ModelRequest], Mapping[str, object]]


@dataclass(frozen=True)
class ModelRunResult:
    policy: ModelPolicyDecision
    output: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": {
                "state": self.policy.state.value,
                "eligible": self.policy.eligible,
            },
            "output": dict(self.output) if self.output is not None else None,
            "artifact_class": "model_assisted_analytical_artifact",
            "independent_clinical_claim_ready": False,
            "may_raise_answer_readiness": False,
            "eligible_for_agi_ingestion": False,
            "eligible_for_treatment_content": False,
            "eligible_for_clinician_export": False,
        }


def execute_model_request(
    request: ModelRequest,
    deployment: ModelDeployment,
    runner: ModelRunner,
) -> ModelRunResult:
    """Invoke the supplied model runner only after the policy decision allows it."""

    decision = evaluate_model_request(request, deployment)
    if not decision.eligible:
        return ModelRunResult(policy=decision)
    return ModelRunResult(policy=decision, output=dict(runner(request)))
