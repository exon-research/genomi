"""Install-time helpers for the Genomi agent installer that are NOT library
materialization.

All reference-library downloading, verification, transformation, and freshness
tracking now lives in the central library manager
(``genomi.runtime.libraries.manager``); the installer drives it in-process. What
remains here is the install-script plumbing: noting an already-populated
GENOMI_HOME, running the post-install verify, and the editable-package install.
"""

from __future__ import annotations

import os
import subprocess
import sys

from _install_for_agents_lib import genomi_home_path


def _report_existing_install(selected: list[str], *, force: bool) -> None:
    """Note that GENOMI_HOME is already populated; install is idempotent.

    The manager skips a library whose files already exist and are current
    (returning ``cached``/``up_to_date``) unless ``--force`` is passed, so
    re-running an install simply fills in whatever is missing and refreshes the
    rest. This is informational only — it never aborts.
    """
    if not selected:
        return
    home = genomi_home_path()
    if not home.exists():
        return
    populated = [child for child in ("resources", "reference", "tools") if (home / child).is_dir() and any((home / child).iterdir())]
    if not populated:
        return
    if force:
        print(f"GENOMI_HOME {home} already contains {', '.join(populated)}; --force will re-download selected libraries.")
    else:
        print(f"GENOMI_HOME {home} already contains {', '.join(populated)}; installing only missing or changed libraries (pass --force to re-download).")


def _verify(label: str, command: list[str]) -> None:
    """Run a verify command quietly. Print one OK/FAIL line; on failure dump output.

    Sets GENOMI_CLI=1 so the install-time verify shells past the CLI gate.
    Host agents at runtime should not set this and should use the MCP tools.
    """
    env = {**os.environ, "GENOMI_CLI": "1"}
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    if result.returncode == 0:
        print(f"verify: {label} ok")
        return
    print(f"verify: {label} FAILED (exit {result.returncode})", file=sys.stderr)
    if result.stdout:
        sys.stderr.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    raise SystemExit(result.returncode)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)
