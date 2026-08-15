"""Fixed, fail-closed specialist execution policies for GenomiLab."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any, Mapping


JsonObject = dict[str, Any]
POLICY_RESOURCE = "specialist_policies.json"
EXPECTED_CONNECTORS: Mapping[str, tuple[str, ...]] = {
    "reasoning_only": (),
    "public_literature": ("paperclip",),
    "protein_model_research": ("esm",),
    "experiment_design": ("proto",),
}
EXPECTED_OPERATIONS: Mapping[str, tuple[str, ...]] = {
    "reasoning_only": (),
    "public_literature": (
        "paperclip.search_biomedical",
        "paperclip.retrieve_document_evidence",
    ),
    "protein_model_research": ("biohub.compare_protein_embeddings",),
    "experiment_design": (
        "proto.search_tools",
        "proto.describe_tool_schema",
        "proto.run_tool",
    ),
}
ISOLATION_FIELDS = (
    "inherit_environment",
    "inherit_mcp",
    "inherit_project",
    "inherit_skills",
    "inherit_workspace",
)


class SpecialistPolicyError(ValueError):
    """The specialist manifest does not prove the required isolation."""


def policy_manifest_bytes() -> bytes:
    return resources.files("genomi.lab").joinpath(POLICY_RESOURCE).read_bytes()


def policy_manifest() -> JsonObject:
    value = json.loads(policy_manifest_bytes())
    if not isinstance(value, dict):
        raise SpecialistPolicyError("specialist policy manifest must be an object")
    validate_policy_manifest(value)
    return value


def policy_manifest_sha256(payload: bytes | None = None) -> str:
    source = payload if payload is not None else policy_manifest_bytes()
    return hashlib.sha256(source).hexdigest()


def validate_policy_manifest(value: Mapping[str, object]) -> None:
    profiles = value.get("profiles")
    if not isinstance(profiles, list):
        raise SpecialistPolicyError("specialist policies must contain a profiles array")
    by_id: dict[str, Mapping[str, object]] = {}
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise SpecialistPolicyError("each specialist profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or profile_id in by_id:
            raise SpecialistPolicyError("specialist profile ids must be unique strings")
        by_id[profile_id] = profile
    if set(by_id) != set(EXPECTED_CONNECTORS):
        raise SpecialistPolicyError(
            "specialist policy inventory is incomplete or contains an unknown profile"
        )
    for profile_id, expected in EXPECTED_CONNECTORS.items():
        profile = by_id[profile_id]
        connectors = profile.get("allowed_connectors")
        if not isinstance(connectors, list) or tuple(connectors) != expected:
            raise SpecialistPolicyError(
                f"{profile_id} must expose exactly the declared connector inventory"
            )
        operations = profile.get("allowed_operations")
        if (
            not isinstance(operations, list)
            or tuple(operations) != EXPECTED_OPERATIONS[profile_id]
        ):
            raise SpecialistPolicyError(
                f"{profile_id} must expose exactly the declared operation inventory"
            )
        input_classes = profile.get("allowed_input_classes")
        if (
            not isinstance(input_classes, list)
            or "deidentified_research_brief" not in input_classes
        ):
            raise SpecialistPolicyError(
                f"{profile_id} must accept a de-identified brief contract"
            )
        for field in ISOLATION_FIELDS:
            if profile.get(field) is not False:
                raise SpecialistPolicyError(f"{profile_id}.{field} must be false")


def read_installed_policy(path: str | Path) -> JsonObject:
    payload = Path(path).read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise SpecialistPolicyError(
            "installed specialist policy manifest must be an object"
        )
    validate_policy_manifest(value)
    if policy_manifest_sha256(payload) != policy_manifest_sha256():
        raise SpecialistPolicyError(
            "installed specialist policy manifest differs from this runtime"
        )
    return value


__all__ = [
    "EXPECTED_CONNECTORS",
    "EXPECTED_OPERATIONS",
    "ISOLATION_FIELDS",
    "SpecialistPolicyError",
    "policy_manifest",
    "policy_manifest_bytes",
    "policy_manifest_sha256",
    "read_installed_policy",
    "validate_policy_manifest",
]
