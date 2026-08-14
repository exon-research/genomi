from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path
from typing import Any

from .. import __version__
from ..runtime.libraries import manager as library_manager
from . import portal_turns

JsonObject = dict[str, Any]

ENVIRONMENT_KIND = "artifact_environment_snapshot"
PACKAGE_NAMES = (
    "genomi",
    "biopython",
    "google-genai",
    "numpy",
    "openpyxl",
    "pysam",
    "pyliftover",
    "isal",
    "duckdb",
)
LIBRARY_FIELDS = (
    "library",
    "title",
    "kind",
    "status",
    "installed",
    "manual_source_required",
    "size_class",
)


def artifact_environment_snapshot(
    *,
    artifact_kind: str,
    renderer: str,
    operation: str,
    created_at: str,
    host_agent_id: str | None = None,
    root: str | Path | None = None,
) -> JsonObject:
    inventory = _library_inventory(root=root)
    snapshot: JsonObject = {
        "kind": ENVIRONMENT_KIND,
        "generated_at": created_at,
        "operation": _safe_text(operation),
        "renderer": _safe_text(renderer),
        "artifact_kind": _safe_text(artifact_kind),
        "runtime": {
            "genomi_version": __version__,
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "packages": _package_versions(),
        "libraries": {
            "summary": _library_summary(inventory.get("summary")),
            "items": _library_items(inventory.get("libraries")),
        },
        "limitations": [
            "This captures the local Genomi portal runtime and library availability, not a full assistant process environment.",
        ],
    }
    agent_id = _safe_text(host_agent_id)
    if agent_id:
        snapshot["host_agent"] = {"agent_id": agent_id}
    public = public_environment(snapshot)
    return public if public is not None else {"kind": ENVIRONMENT_KIND}


def public_environment(value: Any) -> JsonObject | None:
    source = value if isinstance(value, dict) else {}
    if _safe_text(source.get("kind")) != ENVIRONMENT_KIND:
        return None
    public: JsonObject = {
        "kind": ENVIRONMENT_KIND,
        "generated_at": _safe_text(source.get("generated_at")),
        "operation": _safe_text(source.get("operation")),
        "renderer": _safe_text(source.get("renderer")),
        "artifact_kind": _safe_text(source.get("artifact_kind")),
        "host_agent": _public_host_agent(source.get("host_agent")),
        "runtime": _public_runtime(source.get("runtime")),
        "packages": _public_packages(source.get("packages")),
        "libraries": _public_libraries(source.get("libraries")),
        "limitations": _public_text_list(source.get("limitations")),
    }
    return _compact(public)


def _library_inventory(*, root: str | Path | None) -> JsonObject:
    try:
        inventory = library_manager.inventory(root=root)
    except Exception as exc:  # pragma: no cover - defensive; inventory is local.
        return {
            "summary": {"status": "unavailable", "error": _safe_text(exc)},
            "libraries": [],
        }
    return inventory if isinstance(inventory, dict) else {}


def _package_versions() -> list[JsonObject]:
    packages: list[JsonObject] = []
    for name in PACKAGE_NAMES:
        version = __version__ if name == "genomi" else _distribution_version(name)
        package: JsonObject = {"name": name, "status": "installed" if version else "not_installed"}
        if version:
            package["version"] = version
        packages.append(package)
    return packages


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _library_summary(value: Any) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    summary: JsonObject = {}
    for key in (
        "library_count",
        "installed_count",
        "missing_count",
        "manual_source_required_count",
        "not_applicable_count",
    ):
        item = source.get(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, int) and item >= 0:
            summary[key] = item
    status = _safe_text(source.get("status"))
    if status:
        summary["status"] = status
    error = _safe_text(source.get("error"))
    if error:
        summary["error"] = error
    return summary


def _library_items(value: Any) -> list[JsonObject]:
    rows = value if isinstance(value, list) else []
    return [
        _public_library_item(row)
        for row in rows
        if isinstance(row, dict)
    ]


def _public_libraries(value: Any) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    libraries = {
        "summary": _library_summary(source.get("summary")),
        "items": _library_items(source.get("items")),
    }
    return _compact(libraries)


def _public_library_item(value: JsonObject) -> JsonObject:
    item: JsonObject = {}
    for key in LIBRARY_FIELDS:
        child = value.get(key)
        if isinstance(child, bool):
            item[key] = child
        elif isinstance(child, (int, float)) and not isinstance(child, bool):
            item[key] = child
        else:
            text = _safe_text(child)
            if "[redacted local path]" in text:
                continue
            if text:
                item[key] = text
    return item


def _public_host_agent(value: Any) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    agent_id = _safe_text(source.get("agent_id"))
    return {"agent_id": agent_id} if agent_id else {}


def _public_runtime(value: Any) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    runtime: JsonObject = {}
    for key in ("genomi_version", "python_version", "python_implementation", "system", "machine"):
        text = _safe_text(source.get(key))
        if text:
            runtime[key] = text
    return runtime


def _public_packages(value: Any) -> list[JsonObject]:
    rows = value if isinstance(value, list) else []
    packages: list[JsonObject] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _safe_text(row.get("name"))
        if not name:
            continue
        package: JsonObject = {"name": name}
        version = _safe_text(row.get("version"))
        status = _safe_text(row.get("status"))
        if version:
            package["version"] = version
        if status:
            package["status"] = status
        packages.append(package)
    return packages


def _public_text_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [text for text in (_safe_text(item) for item in items) if text]


def _compact(value: JsonObject) -> JsonObject:
    return {
        key: child
        for key, child in value.items()
        if child not in (None, "", [], {})
    }


def _safe_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()
