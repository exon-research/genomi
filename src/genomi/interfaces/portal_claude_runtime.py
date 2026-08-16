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
        # A portal turn is a private genomics inquiry workspace, so the portal
        # decides what the host may touch. Loading no setting sources leaves
        # this process's own flags -- permission mode, allowed tools, MCP
        # servers, specialist agents -- as the whole policy. `--settings` only
        # merges more settings on top of the discovered sources, so it cannot
        # revoke an operator allow rule and is not a substitute for this.
        "--setting-sources",
        "",
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
        budget = int(profile["max_provider_calls"])
        definitions[policy] = {
            "description": _description(policy, operations),
            "prompt": _prompt(policy, operations, budget),
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


def _prompt(policy: str, operations: list[str], budget: int) -> str:
    if operations:
        tools = (
            f"Your only permitted tool is the Genomi MCP tool {GENOMI_INVOKE_TOOL}, "
            "called as {\"tool\": \"<operation>\", \"params\": {...}}, and only for "
            f"these operations: {', '.join(operations)}."
        )
        work = (
            f"You have a budget of {budget} provider calls for this whole assignment. "
            "You answer one bounded question; you are not running an exhaustive "
            "review. Plan your calls up front, and stop calling providers once you "
            "reach the budget or once you can answer, whichever comes first."
        )
        receipts = (
            "Before you run out of room, write your analysis and the exact "
            "result_receipt_id each provider operation returned. Nothing you did "
            "counts until you write it: a partial analysis with its receipts is far "
            "more valuable than a complete analysis you never returned. If you are "
            "running low on budget or context, stop researching immediately and "
            "write what you already have, naming what you did not get to."
        )
    else:
        tools = "You have no tools. Answer from your own reasoning over the brief."
        work = (
            "You answer one bounded question from the brief; you are not running an "
            "exhaustive review."
        )
        receipts = (
            "Return your analysis as plain text. Write it before you run out of "
            "room: a partial analysis returned is worth more than a complete one "
            "that is never delivered."
        )
    return (
        f"You are a GenomiLab native specialist running under the fixed {policy} "
        "execution policy.\n"
        "Work only from the de-identified research brief you were given. Never ask for "
        "or infer patient identity, and never read local files, run shell commands, "
        "browse the web, or use any tool outside this policy.\n"
        f"{tools}\n"
        "Any other tool call violates this policy, is reported to the portal, and "
        "voids your result.\n"
        f"{work}\n"
        f"{receipts}"
    )


def _compact(value: JsonObject) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
