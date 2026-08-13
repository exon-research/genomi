"""Host-process policy for the restricted Codex app-server adapter."""

from __future__ import annotations

import os


DISABLED_CODEX_FEATURES = (
    "shell_tool",
    "unified_exec",
    "code_mode",
    "code_mode_host",
    "js_repl",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "in_app_browser",
    "computer_use",
    "apps",
    "enable_mcp_apps",
    "image_generation",
    "plugins",
    "remote_plugin",
    "workspace_dependencies",
    "skill_search",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "hooks",
    "auth_elicitation",
    "standalone_web_search",
    "request_permissions_tool",
)

CODEX_BASE_INSTRUCTIONS = (
    "You are the installed reasoning and multi-agent harness for GenomiLab. "
    "You have no filesystem, shell, browser, app, plugin, MCP, environment, or direct "
    "evidence-provider authority. Collaboration and the explicitly registered GenomiLab "
    "dynamic tools are the only tools you may use."
)

CODEX_DEVELOPER_INSTRUCTIONS = (
    "Keep patient facts, source evidence, and inference separate. Use only approved "
    "context. Return schema-valid research artifacts and never diagnosis or treatment "
    "directives."
)


def processing_destination(value: object) -> str | None:
    """Accept only an explicit, human-readable processing destination."""

    if not isinstance(value, str):
        return None
    destination = value.strip()
    if not destination or len(destination) > 300:
        return None
    if destination.lower() in {
        "unknown",
        "host_configured",
        "configured",
        "default",
        "local",
        "remote",
    }:
        return None
    if any(ord(character) < 32 for character in destination):
        return None
    return destination


def sanitized_host_environment(*, codex_home: str | None = None) -> dict[str, str]:
    """Keep only process essentials; provider secrets never enter the child."""

    allowed = {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    if codex_home is not None:
        environment["CODEX_HOME"] = codex_home
    return environment


__all__ = [
    "CODEX_BASE_INSTRUCTIONS",
    "CODEX_DEVELOPER_INSTRUCTIONS",
    "DISABLED_CODEX_FEATURES",
    "processing_destination",
    "sanitized_host_environment",
]
