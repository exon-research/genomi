from __future__ import annotations

from ...capabilities.biohub import compare_protein_embeddings
from ...capabilities.paperclip import search_biomedical
from ...capabilities.proto import describe_tool_schema, run_tool, search_tools
from .coerce import _bool, _int, _list_str, _str
from .errors import JsonObject, OperationError


def _paperclip_search_biomedical(params: JsonObject) -> JsonObject:
    return search_biomedical(
        query=_str(params, "query"),
        sources=_list_str(params, "sources") or None,
        limit=_int(params, "limit", 10),
    )


def _biohub_compare_protein_embeddings(params: JsonObject) -> JsonObject:
    return compare_protein_embeddings(
        reference_sequence=_str(params, "reference_sequence"),
        alternate_sequence=_str(params, "alternate_sequence"),
        sequence_scope=_str(params, "sequence_scope"),
        external_transfer_approved=_bool(params, "external_transfer_approved"),
        model=_str(params, "model", "esmc-600m-2024-12"),
    )


def _proto_search_tools(params: JsonObject) -> JsonObject:
    category = params.get("category")
    return search_tools(
        query=_str(params, "query"),
        limit=_int(params, "limit", 10),
        category=str(category).strip() if category not in (None, "") else None,
    )


def _proto_describe_tool_schema(params: JsonObject) -> JsonObject:
    return describe_tool_schema(tool_key=_str(params, "tool_key"))


def _proto_run_tool(params: JsonObject) -> JsonObject:
    inputs = params.get("inputs")
    config = params.get("config")
    if not isinstance(inputs, dict):
        raise OperationError("invalid_params", "inputs must be an object")
    if config is not None and not isinstance(config, dict):
        raise OperationError("invalid_params", "config must be an object")
    return run_tool(
        tool_key=_str(params, "tool_key"),
        inputs=inputs,
        config=config,
        input_scope=_str(params, "input_scope"),
        external_transfer_approved=_bool(params, "external_transfer_approved"),
    )


__all__ = [
    "_biohub_compare_protein_embeddings",
    "_paperclip_search_biomedical",
    "_proto_describe_tool_schema",
    "_proto_run_tool",
    "_proto_search_tools",
]
