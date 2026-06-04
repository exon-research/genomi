from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..catalog import TOOL_CATALOG_FILENAME, load_tool_catalog
from .errors import JsonObject

PROJECT_ROOT = Path(__file__).resolve().parents[4]
TOOL_CATALOG = load_tool_catalog()
TOOL_CATALOG_OPERATIONS: dict[str, JsonObject] = {
    str(name): value
    for name, value in (TOOL_CATALOG.get("operations") or {}).items()
    if isinstance(value, dict)
}


WRITE_OPERATIONS = {
    "active_genome_index.approve_access",
    "active_genome_index.revoke_access",
    "active_genome_index.select_user",
    "active_genome_index.rename_user",
    "active_genome_index.assign_user_genome",
    "active_genome_index.set_default_user",
    "genomi.set_response_profile",
    "genomi.install",
    "active_genome_index.clear_default_user",
    "active_genome_index.clear_selection",
    "genomi.parse_source",
    "active_genome_index.classify_callset_qc",
    "active_genome_index.classify_genotype_support",
    "active_genome_index.classify_region_callability",
    "clinvar.match_variants",
    "clinvar.scan_candidates",
    "gnomad.fetch_population_frequency",
    "research.record",
    "pharmacogenomics.prepare_outside_call_tsv",
    "pharmacogenomics.run_pharmcat",
    "prs.import_scoring_file",
    "journal.append_entry",
    "decode.build_dashboard_evidence",
    "decode.render_dashboard",
}


TOP_LEVEL_FUNCTION_SCHEMA_KEYWORDS = ("oneOf", "anyOf", "allOf", "enum", "not")


def _without_top_level_schema_combinators(schema: JsonObject) -> JsonObject:
    compatible = dict(schema)
    notes: list[str] = []
    for keyword in TOP_LEVEL_FUNCTION_SCHEMA_KEYWORDS:
        if keyword not in compatible:
            continue
        value = compatible.pop(keyword)
        note = _schema_constraint_note(keyword, value)
        if note:
            notes.append(note)
    if notes:
        description = str(compatible.get("description") or "").strip()
        note_text = " ".join(notes)
        compatible["description"] = f"{description} {note_text}".strip()
    return compatible


def _schema_constraint_note(keyword: str, value: Any) -> str:
    if keyword == "not":
        return "Input constraint: see operation documentation for unsupported parameter combinations."
    if keyword == "enum" and isinstance(value, list):
        return f"Input constraint: schema allowed values were {', '.join(map(str, value))}."
    if keyword not in {"oneOf", "anyOf", "allOf"} or not isinstance(value, list):
        return ""

    alternatives: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        required = item.get("required")
        if isinstance(required, list) and required:
            alternatives.append(", ".join(str(field) for field in required))
    if not alternatives:
        return "Input constraint: see operation documentation for accepted parameter combinations."
    if keyword == "allOf":
        return f"Input constraint: all of these requirement groups apply: {'; '.join(alternatives)}."
    return f"Input constraint: provide at least one of these requirement groups: {'; '.join(alternatives)}."


def _operation_scope(name: str) -> str:
    return "write" if name in WRITE_OPERATIONS else "read"


def _data_access(privacy_scope: str) -> tuple[str, ...]:
    return {
        "local_private": ("local_private_artifact",),
        "public_target_only": ("selected_public_targets",),
        "public_variant_only": ("selected_public_variant_targets",),
        "public_metadata": ("public_catalog_metadata",),
        "metadata_only": ("local_artifact_metadata", "public_catalog_metadata"),
        "target_scoped": ("selected_public_targets", "active_genome_index_when_selected"),
        "local_reference_panel_private_projection": (
            "active_genome_index",
            "installed_public_reference_panel",
        ),
    }.get(privacy_scope, ("operation_parameters",))


LOCAL_SOURCE_DEPENDENCIES = frozenset(
    {
        "local_gencode_gtf",
        "local_encode_ccre_bed",
        "msigdb_hallmark_gmt",
        "source_marker_table",
    }
)


def _operation_dependency_contract(
    *,
    optional_libraries: tuple[str, ...],
    external_io: tuple[str, ...],
    library_check_operation: str,
) -> JsonObject:
    contract: JsonObject = {}
    local_resources = [item for item in external_io if item in LOCAL_SOURCE_DEPENDENCIES]
    external_network = [item for item in external_io if item not in LOCAL_SOURCE_DEPENDENCIES]
    if optional_libraries:
        contract["installedLibraries"] = list(optional_libraries)
        contract["missingInstalledLibraryStatus"] = "requires_library_install"
        contract["libraryCheckOperation"] = library_check_operation or "genomi.check_libraries"
    if external_network:
        contract["externalNetwork"] = external_network
        contract["externalUnavailableStatus"] = "source_unavailable"
    if local_resources:
        contract["localResources"] = local_resources
        contract["localResourceUnavailableStatuses"] = ["requires_library_install", "source_unavailable"]
    return contract


JOURNAL_ENTRY_TYPES = [
    "observation",
    "hypothesis",
    "decision",
    "contradiction",
    "unresolved_question",
    "protocol_note",
    "plan",
    "summary",
]
CAPABILITY_ORDER = [str(item) for item in TOOL_CATALOG.get("capability_order", [])]
NAMESPACE_ORDER = [str(item) for item in TOOL_CATALOG.get("namespace_order", [])]
CAPABILITY_METADATA: dict[str, JsonObject] = {
    str(capability): {
        "title": str(payload.get("title") or capability),
        "start_when": str(payload.get("start_when") or ""),
        "skill_documents": [str(path) for path in payload.get("skill_documents") or []],
        "optional_libraries": list(payload.get("optional_libraries") or []),
        "library_check_operation": str(payload.get("library_check_operation") or ""),
    }
    for capability, payload in (TOOL_CATALOG.get("capabilities") or {}).items()
    if isinstance(payload, dict)
}
CAPABILITY_ENTRY_OPERATIONS = {
    str(capability): tuple(str(name) for name in payload.get("entry_operations", []))
    for capability, payload in (TOOL_CATALOG.get("capabilities") or {}).items()
    if isinstance(payload, dict)
}
CAPABILITY_ENTRY_OPERATION_NAMES = {
    operation_name
    for operation_names in CAPABILITY_ENTRY_OPERATIONS.values()
    for operation_name in operation_names
}


def _operation_catalog_entry(name: str) -> JsonObject:
    try:
        return TOOL_CATALOG_OPERATIONS[name]
    except KeyError as exc:
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} is missing operation {name!r}") from exc


def _catalog_input_schema(catalog: JsonObject) -> JsonObject:
    return _expand_schema_property_groups(_resolve_schema_refs(catalog.get("input_schema") or {}))


def _expand_schema_property_groups(schema: JsonObject) -> JsonObject:
    group_names = schema.pop("x_genomi_property_groups", [])
    if not group_names:
        return schema
    if not isinstance(group_names, list):
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} x_genomi_property_groups must be an array")
    fragments = TOOL_CATALOG.get("schema_fragments") or {}
    property_groups = fragments.get("property_groups") or {}
    if not isinstance(property_groups, dict):
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} schema_fragments.property_groups must be an object")
    grouped_properties: JsonObject = {}
    for name in group_names:
        group_name = str(name)
        group = property_groups.get(group_name)
        if not isinstance(group, dict):
            raise RuntimeError(f"{TOOL_CATALOG_FILENAME} has unresolved property group {group_name!r}")
        properties = group.get("properties")
        if not isinstance(properties, dict):
            raise RuntimeError(f"{TOOL_CATALOG_FILENAME} property group {group_name!r} must define properties")
        grouped_properties.update(_resolve_schema_refs(properties))
    direct_properties = schema.get("properties") or {}
    if not isinstance(direct_properties, dict):
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} input_schema.properties must be an object")
    schema["properties"] = {**grouped_properties, **direct_properties}
    return schema


def _resolve_schema_refs(value: Any, *, seen: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [_resolve_schema_refs(item, seen=seen) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    if "$ref" not in value:
        return {str(key): _resolve_schema_refs(item, seen=seen) for key, item in value.items()}

    ref = str(value["$ref"])
    if ref in seen:
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} has a circular schema reference: {' -> '.join((*seen, ref))}")
    resolved = _resolve_catalog_ref(ref, seen=(*seen, ref))
    overrides = {key: item for key, item in value.items() if key != "$ref"}
    if not overrides:
        return resolved
    if not isinstance(resolved, dict):
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} schema reference {ref!r} cannot be merged with overrides")
    merged = dict(resolved)
    merged.update(_resolve_schema_refs(overrides, seen=(*seen, ref)))
    return merged


def _resolve_catalog_ref(ref: str, *, seen: tuple[str, ...]) -> Any:
    if not ref.startswith("#/"):
        raise RuntimeError(f"{TOOL_CATALOG_FILENAME} only supports local schema references, got {ref!r}")
    current: Any = TOOL_CATALOG
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise RuntimeError(f"{TOOL_CATALOG_FILENAME} has unresolved schema reference {ref!r}")
        current = current[part]
    return _resolve_schema_refs(deepcopy(current), seen=seen)


def _catalog_tuple(catalog: JsonObject, key: str) -> tuple[Any, ...]:
    value = catalog.get(key)
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, tuple):
        return value
    if value in (None, ""):
        return ()
    return (value,)


def _operation_namespace(name: str) -> str:
    return name.split(".", 1)[0] if "." in name else name


# Capabilities whose tools are ALWAYS in tools/list. Capability tools outside
# this set are reached via genomi.invoke after the agent reads the relevant
# skill markdown. Keep this list in sync with the base-set filter in
# `_select_operations`.
BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST = frozenset({"genomi", "journal"})
