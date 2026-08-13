"""Dynamic tool projection for one exact accepted GenomiLab plan."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .capability_registry import capability_definition
from .harness_transport import required_identifier, safe_json_dumps


def dynamic_tools(
    approved_context_value: object,
) -> tuple[dict[str, str], list[dict[str, Any]], str]:
    """Expose only registered capabilities named by the exact accepted plan."""

    if not isinstance(approved_context_value, Mapping):
        raise ValueError("approved_context must be an object")
    accepted_plan = approved_context_value.get("accepted_plan")
    if accepted_plan is None:
        return {}, [], hashlib.sha256(b"tool-free-planning-turn").hexdigest()
    if not isinstance(accepted_plan, Mapping):
        raise ValueError("accepted_plan must be an object")
    plan = accepted_plan.get("plan")
    if not isinstance(plan, Mapping):
        raise ValueError("accepted_plan.plan must be an object")
    requests = plan.get("capability_requests")
    if not isinstance(requests, (list, tuple)):
        raise ValueError("accepted plan capability_requests must be an array")
    catalog = approved_context_value.get("capability_catalog")
    if not isinstance(catalog, Mapping):
        raise ValueError("capability_catalog must be an object")

    request_ids_by_capability: dict[str, list[str]] = {}
    for request in requests:
        if not isinstance(request, Mapping):
            raise ValueError("accepted plan capability requests must be objects")
        request_id = required_identifier(request.get("id"), "request_id")
        capability = required_identifier(request.get("capability"), "capability")
        definition = capability_definition(capability)
        entry = catalog.get(definition.name)
        if not isinstance(entry, Mapping) or entry.get("available") is not True:
            raise ValueError(
                "accepted plan capability is unavailable in the current catalog"
            )
        request_ids_by_capability.setdefault(definition.name, []).append(request_id)

    capability_by_tool: dict[str, str] = {}
    tools: list[dict[str, Any]] = []
    for capability in sorted(request_ids_by_capability):
        definition = capability_definition(capability)
        tool_name = _tool_name(definition.name)
        if tool_name in capability_by_tool:
            raise ValueError("capability names collide after dynamic-tool normalization")
        capability_by_tool[tool_name] = definition.name
        request_ids = sorted(request_ids_by_capability[definition.name])
        tools.append(
            {
                "type": "function",
                "name": tool_name,
                "description": definition.dynamic_tool_description,
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request_id"],
                    "properties": {
                        "request_id": {"type": "string", "enum": request_ids}
                    },
                },
                "deferLoading": False,
            }
        )
    tool_contract = {
        "namespace": "genomilab",
        "plan_version_id": accepted_plan.get("plan_version_id"),
        "plan_sha256": accepted_plan.get("plan_sha256"),
        "requests": [
            {"request_id": request_id, "capability": capability}
            for capability in sorted(request_ids_by_capability)
            for request_id in sorted(request_ids_by_capability[capability])
        ],
    }
    digest = hashlib.sha256(safe_json_dumps(tool_contract).encode("utf-8")).hexdigest()
    namespaces = (
        [
            {
                "type": "namespace",
                "name": "genomilab",
                "description": (
                    "Validated GenomiLab gateway for only the exact accepted plan "
                    "requests."
                ),
                "tools": tools,
            }
        ]
        if tools
        else []
    )
    return capability_by_tool, namespaces, digest


def _tool_name(capability: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]", "__", capability.strip())
    if not normalized or not normalized[0].isalpha():
        normalized = f"capability__{normalized}"
    return normalized[:120]


__all__ = ["dynamic_tools"]
