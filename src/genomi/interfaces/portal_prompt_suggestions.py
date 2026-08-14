from __future__ import annotations

from typing import Any

from . import portal_selected_context_catalog
from . import portal_turns

JsonObject = dict[str, Any]

_OPERATION_LABELS = {
    "genomi.parse_source": "genome preparation",
    "genomi.portal.workspace_file": "project file",
    "genomi.search_indexes": "Genomi resource search",
    "genomi.check_libraries": "library readiness check",
    "pharmacogenomics.review_medication": "medication-response review",
    "research.build_target_packet": "target evidence report",
    "variant.resolve": "variant lookup",
}
_NAMESPACE_LABELS = {
    "cell_type": "cell type",
    "clinvar": "ClinVar",
    "functional_genomics": "functional genomics",
    "genomi": "Genomi",
    "gwas": "GWAS",
    "pathway": "pathway",
    "pharmacogenomics": "pharmacogenomics",
    "phenotype": "phenotype",
    "prs": "PRS",
    "region": "region",
    "research": "research",
    "variant": "variant",
}


def prompt_suggestion_payload(payload: JsonObject | None) -> JsonObject:
    selected_evidence = portal_turns.clean_selected_evidence(_selected_evidence_value(payload or {}))
    prompt = suggested_prompt_for_selected_evidence(selected_evidence)
    return {
        "prompt": prompt,
        "selected_evidence": selected_evidence,
        "context_count": len(selected_evidence),
    }


def suggested_prompt_for_selected_evidence(selected_evidence: list[JsonObject] | None) -> str:
    contexts = [item for item in selected_evidence or [] if isinstance(item, dict)]
    if not contexts:
        return ""
    kinds = {_context_kind(item) for item in contexts}
    if kinds == {"genome_context"}:
        return ""
    for kind in portal_selected_context_catalog.PRIORITY_PROMPT_KIND_ORDER:
        if kind in kinds:
            return portal_selected_context_catalog.PRIORITY_PROMPTS[kind]
    request_operations = _selected_operations(
        contexts,
        kinds=portal_selected_context_catalog.source_request_kinds(),
        require_nodes=False,
    )
    if request_operations:
        return (
            "Use this "
            + portal_selected_context_catalog.source_request_prompt_label()
            + _operation_phrase(request_operations)
            + " to decide the next assistant action. Use only the supplied request parameters, ask for missing required "
            "inputs before using it, and preserve source limits, default assumptions, and genome privacy boundaries."
        )
    result_groups = _selected_result_operation_groups(contexts)
    if result_groups:
        group_text = " and the ".join(
            group["label"] + " from " + _operation_list_text(group["operations"]) for group in result_groups
        )
        selected_items = _selected_group_items(result_groups)
        selected_ops = _operation_list_text(
            _unique_operation_list(
                operation
                for group in result_groups
                for operation in group["operations"]
            )
        )
        item_detail = f" Selected items: {_item_list_text(selected_items)}." if selected_items else ""
        detail = f" Selected sources: {selected_ops}." if len(result_groups) > 1 and selected_ops else ""
        return (
            f"Use the {group_text} to answer my question."
            f"{item_detail}{detail} Preserve source limits and source priors, "
            "and report what the selected evidence supports, what remains missing, and what is out of scope."
        )
    return portal_selected_context_catalog.GENERIC_PROMPT


def _selected_evidence_value(payload: JsonObject) -> Any:
    for key in ("selectedEvidence", "selected_evidence", "contexts", "items"):
        value = payload.get(key)
        if value is not None:
            return value
    input_data = payload.get("input_data")
    if isinstance(input_data, dict):
        return _selected_evidence_value(input_data)
    return None


def _selected_result_operation_groups(contexts: list[JsonObject]) -> list[JsonObject]:
    groups = portal_selected_context_catalog.result_operation_groups()
    for item in contexts:
        operation = _source_operation(item)
        if not operation or not _has_selected_nodes(item):
            continue
        for group in groups:
            if group["kind"] == _context_kind(item) and operation not in group["operations"]:
                group["operations"].append(operation)
            if group["kind"] == _context_kind(item):
                group.setdefault("items", [])
                for label in _selected_node_labels(item):
                    if label not in group["items"]:
                        group["items"].append(label)
    return [
        {**group, "operations": group["operations"][:4], "items": group.get("items", [])[:4]}
        for group in groups
        if group["operations"]
    ]


def _selected_operations(contexts: list[JsonObject], *, kinds: set[str], require_nodes: bool) -> list[str]:
    operations: list[str] = []
    for item in contexts:
        if _context_kind(item) not in kinds:
            continue
        if require_nodes and not _has_selected_nodes(item):
            continue
        operation = _source_operation(item)
        if operation and operation not in operations:
            operations.append(operation)
    return operations[:4]


def _context_kind(item: JsonObject) -> str:
    return portal_turns.prompt_safe_text(str(item.get("context_kind") or "")).strip().lower()


def _source_operation(item: JsonObject) -> str:
    operation = portal_turns.prompt_safe_text(str(item.get("source_operation") or "")).strip()
    return operation if "." in operation else ""


def _has_selected_nodes(item: JsonObject) -> bool:
    return bool(item.get("selected_nodes"))


def _selected_node_labels(item: JsonObject) -> list[str]:
    labels: list[str] = []
    for node in item.get("selected_nodes") or []:
        if not isinstance(node, dict):
            continue
        label = portal_turns.prompt_safe_text(str(node.get("label") or "")).strip()
        if label and label not in labels:
            labels.append(label)
    return labels[:4]


def _selected_group_items(groups: list[JsonObject]) -> list[str]:
    items: list[str] = []
    for group in groups:
        for label in group.get("items") or []:
            if label and label not in items:
                items.append(label)
    return items[:4]


def _item_list_text(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _operation_phrase(operations: list[str]) -> str:
    if len(operations) == 1:
        return " for " + _operation_label(operations[0])
    return "s for " + _operation_list_text(operations)


def _operation_list_text(operations: list[str]) -> str:
    labels = [_operation_label(operation) for operation in operations[:4]]
    return labels[0] if len(labels) == 1 else ", ".join(labels)


def _unique_operation_list(operations: Any) -> list[str]:
    unique: list[str] = []
    for operation in operations:
        if operation and operation not in unique:
            unique.append(operation)
    return unique[:4]


def _operation_label(operation: str) -> str:
    clean = portal_turns.prompt_safe_text(str(operation or "")).strip()
    if not clean:
        return "evidence source"
    if clean in _OPERATION_LABELS:
        return _OPERATION_LABELS[clean]
    if "." not in clean:
        return clean.replace("_", " ")
    namespace, rest = clean.split(".", 1)
    namespace_label = _NAMESPACE_LABELS.get(namespace, namespace.replace("_", " "))
    action = rest.replace("_", " ").replace(".", " ").strip()
    return " ".join(part for part in (namespace_label, action) if part)
