from __future__ import annotations

import json
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
TOOL_CATALOG_FILENAME = "tool catalog fragments"
CATALOG_BASE_PACKAGE = "genomi.operations"
CATALOG_BASE_FILENAME = "catalog_base.json"
CATALOG_FRAGMENT_FILENAME = "tool_catalog.json"
CATALOG_FRAGMENT_PACKAGES = (
    "genomi.runtime",
    "genomi.lab",
    "genomi.active_genome_index",
    "genomi.capabilities.clinvar",
    "genomi.capabilities.variant",
    "genomi.capabilities.phenotype",
    "genomi.capabilities.pharmacogenomics",
    "genomi.capabilities.gwas",
    "genomi.capabilities.functional_genomics",
    "genomi.capabilities.ancestry",
    "genomi.capabilities.gnomad",
    "genomi.capabilities.prs",
    "genomi.capabilities.nutrigenomics",
    "genomi.capabilities.sequence",
    "genomi.capabilities.analytical_grounding",
    "genomi.capabilities.research",
    "genomi.capabilities.journal",
    "genomi.capabilities.decode",
)


def load_tool_catalog() -> JsonObject:
    payload = _read_json_resource(CATALOG_BASE_PACKAGE, CATALOG_BASE_FILENAME)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{CATALOG_BASE_FILENAME} must be a JSON object")
    if not isinstance(payload.get("capability_order"), list):
        raise RuntimeError(f"{CATALOG_BASE_FILENAME} capability_order must be an array")
    if not isinstance(payload.get("namespace_order"), list):
        raise RuntimeError(f"{CATALOG_BASE_FILENAME} namespace_order must be an array")
    if not isinstance(payload.get("schema_fragments"), dict):
        raise RuntimeError(f"{CATALOG_BASE_FILENAME} schema_fragments must be an object")

    capabilities: dict[str, Any] = {}
    operations: dict[str, Any] = {}
    for package in CATALOG_FRAGMENT_PACKAGES:
        fragment = _read_json_resource(package, CATALOG_FRAGMENT_FILENAME)
        _merge_catalog_fragment(package, fragment, capabilities=capabilities, operations=operations)

    missing_capabilities = set(payload["capability_order"]) - set(capabilities)
    extra_capabilities = set(capabilities) - set(payload["capability_order"])
    if missing_capabilities or extra_capabilities:
        raise RuntimeError(
            "tool catalog capability fragments do not match capability_order: "
            f"missing={sorted(missing_capabilities)} extra={sorted(extra_capabilities)}"
        )
    _validate_catalog_relationships(capabilities, operations)

    payload["capabilities"] = {
        capability_id: capabilities[capability_id]
        for capability_id in payload["capability_order"]
    }
    payload["operations"] = operations
    return payload


def _merge_catalog_fragment(
    package: str,
    fragment: JsonObject,
    *,
    capabilities: dict[str, Any],
    operations: dict[str, Any],
) -> None:
    if not isinstance(fragment, dict):
        raise RuntimeError(f"{package}:{CATALOG_FRAGMENT_FILENAME} must be a JSON object")
    fragment_capabilities = fragment.get("capabilities")
    fragment_operations = fragment.get("operations")
    if not isinstance(fragment_capabilities, dict):
        raise RuntimeError(f"{package}:{CATALOG_FRAGMENT_FILENAME} capabilities must be an object")
    if not isinstance(fragment_operations, dict):
        raise RuntimeError(f"{package}:{CATALOG_FRAGMENT_FILENAME} operations must be an object")

    duplicate_capabilities = set(capabilities) & set(fragment_capabilities)
    duplicate_operations = set(operations) & set(fragment_operations)
    if duplicate_capabilities or duplicate_operations:
        raise RuntimeError(
            f"{package}:{CATALOG_FRAGMENT_FILENAME} duplicates catalog entries: "
            f"capabilities={sorted(duplicate_capabilities)} operations={sorted(duplicate_operations)}"
        )

    for capability_id, capability in fragment_capabilities.items():
        if not isinstance(capability, dict):
            raise RuntimeError(f"{package}:{CATALOG_FRAGMENT_FILENAME} capability {capability_id!r} must be an object")
        declared_operations = capability.get("operations")
        if not isinstance(declared_operations, list) or not all(isinstance(item, str) for item in declared_operations):
            raise RuntimeError(
                f"{package}:{CATALOG_FRAGMENT_FILENAME} capability {capability_id!r} operations must be a string list"
            )
    for operation_name, operation in fragment_operations.items():
        if not isinstance(operation, dict):
            raise RuntimeError(f"{package}:{CATALOG_FRAGMENT_FILENAME} operation {operation_name!r} must be an object")
        if not isinstance(operation.get("capability"), str):
            raise RuntimeError(
                f"{package}:{CATALOG_FRAGMENT_FILENAME} operation {operation_name!r} must declare a capability"
            )

    capabilities.update(fragment_capabilities)
    operations.update(fragment_operations)


def _validate_catalog_relationships(capabilities: dict[str, Any], operations: dict[str, Any]) -> None:
    for operation_name, operation in operations.items():
        capability_id = operation.get("capability")
        if capability_id not in capabilities:
            raise RuntimeError(
                f"{operation_name!r} declares unknown capability {capability_id!r}"
            )

    for capability_id, capability in capabilities.items():
        declared_operations = set(capability.get("operations") or ())
        actual_operations = {
            name
            for name, operation in operations.items()
            if operation.get("capability") == capability_id
        }
        if declared_operations != actual_operations:
            raise RuntimeError(
                f"capability {capability_id!r} operation list mismatch: "
                f"missing={sorted(declared_operations - actual_operations)} "
                f"extra={sorted(actual_operations - declared_operations)}"
            )
        entry_operations = capability.get("entry_operations") or []
        if not isinstance(entry_operations, list) or not all(isinstance(item, str) for item in entry_operations):
            raise RuntimeError(f"capability {capability_id!r} entry_operations must be a string list")
        missing_entries = set(entry_operations) - actual_operations
        if missing_entries:
            raise RuntimeError(
                f"capability {capability_id!r} entry_operations are not declared operations: "
                f"{sorted(missing_entries)}"
            )


def _read_json_resource(package: str, filename: str) -> JsonObject:
    try:
        text = (
            importlib_resources.files(package)
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        package_path = Path(__file__).resolve().parents[1].joinpath(*package.split(".")[1:])
        text = (package_path / filename).read_text(encoding="utf-8")
    return json.loads(text)
