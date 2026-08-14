from __future__ import annotations

import json
import shlex
from typing import Any

from . import portal_turns

JsonObject = dict[str, Any]
READY_STATUS = "ready"
PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS = "partial_private_parameters_redacted"
_PUBLIC_STATUSES = {READY_STATUS, PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS}
_PUBLIC_RECIPE_KIND = "operation_rebuild_recipe"
_COMMAND_FIELDS = ("label", "language", "command", "purpose")
_HOST_AGENT_FIELDS = ("tool", "params", "instruction", "guidance")


def operation_rebuild_recipe(
    *,
    operation: str,
    renderer: str,
    params: JsonObject,
    artifact_family: str,
) -> JsonObject:
    """Build a public rebuild recipe for a portal-owned artifact operation."""

    safe_operation = portal_turns.prompt_safe_text(operation).strip()
    safe_renderer = portal_turns.prompt_safe_text(renderer).strip()
    safe_params = _safe_params(params)
    params_redacted = _json_fingerprint(params) != _json_fingerprint(safe_params)
    limitations = [
        "Rebuilds the Genomi operation result and portal-owned report recipe, not the full assistant conversation.",
        "External public sources and installed Genomi libraries may have changed since the artifact version was created.",
    ]
    host_agent: JsonObject = {
        "tool": safe_operation,
        "params": safe_params,
        "instruction": "Ask the assistant to call this Genomi operation through MCP, then render the returned evidence report.",
        "guidance": ["ready:call_operation_through_mcp_then_render_artifact"],
    }
    recipe: JsonObject = {
        "status": READY_STATUS,
        "kind": _PUBLIC_RECIPE_KIND,
        "artifact_family": portal_turns.prompt_safe_text(artifact_family).strip(),
        "operation": safe_operation,
        "renderer": safe_renderer,
        "params": safe_params,
        "params_redacted": params_redacted,
        "host_agent": host_agent,
        "limitations": limitations,
    }
    if params_redacted:
        limitations.append("Private or local-path parameters were redacted from this public rebuild recipe.")
        limitations.append("This recipe is not executable until the redacted parameters are supplied in the current session.")
        host_agent["instruction"] = (
            "Ask the user to re-supply the redacted private or local parameters in this session before rerunning "
            "the Genomi operation through MCP."
        )
        host_agent["guidance"] = [
            "partial_private_parameters_redacted:ask_user_to_supply_redacted_parameters_before_rebuild"
        ]
        recipe["status"] = PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS
        return recipe

    params_json = json.dumps(safe_params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    command = f"genomi call {shlex.quote(safe_operation)} --params {shlex.quote(params_json)}"
    recipe["commands"] = [
        {
            "label": "Genomi operation",
            "language": "shell",
            "command": command,
            "purpose": "Recreate the operation result JSON used by the portal renderer.",
        }
    ]
    recipe["script"] = "\n".join(
        [
            "# Rebuild the Genomi operation result that produced this artifact.",
            "# This does not replay the assistant reasoning turn or external source drift.",
            command,
        ]
    )
    return recipe


def public_reproduction(value: Any) -> JsonObject | None:
    recipe = value if isinstance(value, dict) else {}
    status = str(recipe.get("status") or "").strip()
    if status not in _PUBLIC_STATUSES:
        return None
    safe_recipe = portal_turns.prompt_safe_value(recipe)
    sensitive_redacted = _json_fingerprint(recipe) != _json_fingerprint(safe_recipe)
    params = _safe_params(recipe.get("params") if isinstance(recipe.get("params"), dict) else {})
    params_redacted = (
        bool(recipe.get("params_redacted"))
        or sensitive_redacted
        or status == PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS
    )
    public_status = PARTIAL_PRIVATE_PARAMETERS_REDACTED_STATUS if params_redacted else READY_STATUS
    public: JsonObject = {
        "status": public_status,
        "kind": _safe_text(recipe.get("kind")) or _PUBLIC_RECIPE_KIND,
        "artifact_family": _safe_text(recipe.get("artifact_family")),
        "operation": _safe_text(recipe.get("operation")),
        "renderer": _safe_text(recipe.get("renderer")),
        "params": params,
        "params_redacted": params_redacted,
        "host_agent": _public_host_agent(recipe.get("host_agent"), fallback_tool=recipe.get("operation"), fallback_params=params),
        "limitations": _public_limitations(recipe.get("limitations"), params_redacted=params_redacted),
    }
    if public_status == READY_STATUS:
        commands = _public_commands(recipe.get("commands"))
        script = _safe_text(recipe.get("script"))
        if commands:
            public["commands"] = commands
        if script:
            public["script"] = script
    return _compact(public)


def _safe_params(params: JsonObject) -> JsonObject:
    safe = portal_turns.prompt_safe_value(params if isinstance(params, dict) else {})
    return safe if isinstance(safe, dict) else {}


def _public_commands(value: Any) -> list[JsonObject]:
    items = value if isinstance(value, list) else []
    commands: list[JsonObject] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        command = {
            field: _safe_text(item.get(field))
            for field in _COMMAND_FIELDS
            if _safe_text(item.get(field))
        }
        if command.get("command"):
            commands.append(command)
    return commands


def _public_host_agent(value: Any, *, fallback_tool: Any, fallback_params: JsonObject) -> JsonObject:
    source = value if isinstance(value, dict) else {}
    host_agent: JsonObject = {}
    for field in _HOST_AGENT_FIELDS:
        if field == "params":
            params = _safe_params(source.get("params") if isinstance(source.get("params"), dict) else fallback_params)
            if params:
                host_agent["params"] = params
            continue
        if field == "guidance":
            guidance = [_safe_text(item) for item in source.get("guidance", [])] if isinstance(source.get("guidance"), list) else []
            guidance = [item for item in guidance if item]
            if guidance:
                host_agent["guidance"] = guidance
            continue
        text = _safe_text(source.get(field))
        if text:
            host_agent[field] = text
    if not host_agent.get("tool"):
        tool = _safe_text(fallback_tool)
        if tool:
            host_agent["tool"] = tool
    return host_agent


def _public_limitations(value: Any, *, params_redacted: bool) -> list[str]:
    limitations = [_safe_text(item) for item in value] if isinstance(value, list) else []
    limitations = [item for item in limitations if item]
    if params_redacted:
        for limitation in (
            "Private or local-path parameters were redacted from this public rebuild recipe.",
            "This recipe is not executable until the redacted parameters are supplied in the current session.",
        ):
            if limitation not in limitations:
                limitations.append(limitation)
    return limitations


def _compact(value: JsonObject) -> JsonObject:
    return {
        key: child
        for key, child in value.items()
        if child not in (None, "", [], {})
    }


def _safe_text(value: Any) -> str:
    return portal_turns.prompt_safe_text(str(value or "")).strip()


def _json_fingerprint(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=True)
