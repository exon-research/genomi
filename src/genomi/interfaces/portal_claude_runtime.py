from __future__ import annotations

import json
from typing import Any

from ..lab.specialist_policies import policy_manifest
from . import portal_codex_runtime

JsonObject = dict[str, Any]

GENOMI_INVOKE_TOOL = "mcp__genomi__genomi_invoke"

_POLICY_WORK = {
    "reasoning_only": (
        "analyse a de-identified research brief with no tools and no external sources"
    ),
    "public_literature": "review public biomedical literature through Paperclip",
    "protein_model_research": (
        "compare approved public reference protein sequences through BioHub ESMC"
    ),
    "experiment_design": (
        "plan and run bounded nonclinical Proto computational-biology tools"
    ),
}


def runtime_args(environment: dict[str, str] | None = None) -> list[str]:
    """Bind a portal Claude turn to this WebUI's Genomi runtime and specialists."""

    servers = {
        "mcpServers": {
            "genomi": portal_codex_runtime.genomi_mcp_server_config(environment)
        }
    }
    return [
        "--mcp-config",
        _compact(servers),
        # Without this, the operator's ambient ~/.claude MCP configuration is
        # merged in and unrelated connectors reach the portal turn.
        "--strict-mcp-config",
        "--agents",
        _compact(specialist_agent_definitions()),
    ]


def command_with_runtime(
    command: list[str],
    environment: dict[str, str] | None = None,
) -> list[str]:
    """Insert runtime binding before the trailing variadic --allowedTools list."""

    return [command[0], *runtime_args(environment), *command[1:]]


def specialist_agent_definitions() -> dict[str, JsonObject]:
    """Publish each fixed specialist policy as one native Claude subagent."""

    definitions: dict[str, JsonObject] = {}
    for profile in policy_manifest()["profiles"]:
        policy = str(profile["id"])
        operations = [str(operation) for operation in profile["allowed_operations"]]
        definitions[policy] = {
            "description": _description(policy, operations),
            "prompt": _prompt(policy, operations),
            "tools": [GENOMI_INVOKE_TOOL] if operations else [],
        }
    return definitions


def _description(policy: str, operations: list[str]) -> str:
    work = _POLICY_WORK.get(policy, "run one bounded GenomiLab research assignment")
    scope = ", ".join(operations) if operations else "no tools"
    return (
        f"GenomiLab specialist for the {policy} execution policy: {work}. "
        f"Permitted operations: {scope}."
    )


def _prompt(policy: str, operations: list[str]) -> str:
    if operations:
        tools = (
            f"Your only permitted tool is the Genomi MCP tool {GENOMI_INVOKE_TOOL}, "
            "called as {\"tool\": \"<operation>\", \"params\": {...}}, and only for "
            f"these operations: {', '.join(operations)}."
        )
        receipts = (
            "Return your analysis together with the exact result_receipt_id that each "
            "provider operation returned."
        )
    else:
        tools = "You have no tools. Answer from your own reasoning over the brief."
        receipts = "Return your analysis as plain text."
    return (
        f"You are a GenomiLab native specialist running under the fixed {policy} "
        "execution policy.\n"
        "Work only from the de-identified research brief you were given. Never ask for "
        "or infer patient identity, and never read local files, run shell commands, "
        "browse the web, or use any tool outside this policy.\n"
        f"{tools}\n"
        "Any other tool call violates this policy, is reported to the portal, and "
        "voids your result.\n"
        f"{receipts}"
    )


def _compact(value: JsonObject) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
