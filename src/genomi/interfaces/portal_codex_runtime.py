from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def genomi_mcp_server_config() -> dict[str, Any]:
    """Bind portal Codex turns to the Genomi runtime serving this WebUI."""

    source_root = Path(__file__).resolve().parents[2]
    python_path = str(source_root)
    inherited_python_path = str(os.environ.get("PYTHONPATH") or "").strip()
    if inherited_python_path:
        python_path = os.pathsep.join((python_path, inherited_python_path))
    return {
        "command": sys.executable,
        "args": ["-m", "genomi", "serve", "--transport", "stdio"],
        "env": {"PYTHONPATH": python_path},
    }


def exec_config_args() -> list[str]:
    config = genomi_mcp_server_config()
    return [
        "-c",
        f"mcp_servers.genomi.command={json.dumps(config['command'])}",
        "-c",
        f"mcp_servers.genomi.args={json.dumps(config['args'], separators=(',', ':'))}",
        "-c",
        f"mcp_servers.genomi.env.PYTHONPATH={json.dumps(config['env']['PYTHONPATH'])}",
    ]
