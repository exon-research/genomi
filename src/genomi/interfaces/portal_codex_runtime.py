from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


_RUN_SCOPED_ENVIRONMENT = (
    "GENOMI_CONTEXT",
    "GENOMI_CONTEXT_POLICY",
    "GENOMI_SESSION_ID",
    "GENOMILAB_PORTAL_PROJECT_ID",
    "GENOMILAB_PORTAL_FRAME_ID",
    "PAPERCLIP_API_KEY",
    "BIOHUB_API_KEY",
    "ESM_API_KEY",
    "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET",
)


def genomi_mcp_server_config(
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Bind portal Codex turns to the Genomi runtime serving this WebUI."""

    source_root = Path(__file__).resolve().parents[2]
    python_path = str(source_root)
    inherited_python_path = str(os.environ.get("PYTHONPATH") or "").strip()
    if inherited_python_path:
        python_path = os.pathsep.join((python_path, inherited_python_path))
    mcp_environment = {"PYTHONPATH": python_path}
    if environment is not None:
        for name in _RUN_SCOPED_ENVIRONMENT:
            value = str(environment.get(name) or "").strip()
            if value:
                mcp_environment[name] = value
    return {
        "command": sys.executable,
        "args": ["-m", "genomi", "serve", "--transport", "stdio"],
        "env": mcp_environment,
    }


def exec_config_args(
    environment: dict[str, str] | None = None,
) -> list[str]:
    config = genomi_mcp_server_config(environment)
    args = [
        "-c",
        f"mcp_servers.genomi.command={json.dumps(config['command'])}",
        "-c",
        f"mcp_servers.genomi.args={json.dumps(config['args'], separators=(',', ':'))}",
    ]
    for name, value in config["env"].items():
        args.extend(
            [
                "-c",
                f"mcp_servers.genomi.env.{name}={json.dumps(value)}",
            ]
        )
    return args
