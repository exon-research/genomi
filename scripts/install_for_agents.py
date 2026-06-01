#!/usr/bin/env python3
"""Genomi agent installer entry point.

The bulk of the implementation lives in sibling modules
(``_install_for_agents_lib`` and ``_install_for_agents_downloads``) to keep
each file small. Reference-library materialization is delegated entirely to the
central library manager (``genomi.runtime.libraries.manager``) — this script
only does package/skill/host wiring and then drives the manager per library.

``main`` is defined here so that the helpers it calls by name resolve against
this module's namespace — that keeps ``mock.patch.object(install_for_agents,
"run")`` and friends working in the test suite.
"""
# pyright: reportUnusedImport=false
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the sibling helper modules importable regardless of how this file is
# loaded (direct ``python scripts/install_for_agents.py``, or ``importlib``
# exec with ``scripts/`` not on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _install_for_agents_lib import *  # noqa: F401,F403  (re-export public API)
from _install_for_agents_lib import (  # noqa: F401  (explicit; incl. underscore names)
    CAPABILITY_SKILL_DIRS_TO_SKIP,
    CAPABILITY_SKILLS_ROOT,
    DEFAULT_HOST_SKILL_PARENTS,
    GENOMI_USER_AGENT,
    HOST_AGENT_SKILL_DIR,
    REPO_ROOT,
    SRC_DIR,
    _capability_skill_sources,
    _ensure_src_on_path,
    _load_existing_users,
    configure_genome_source,
    genomi_home_path,
    install_capability_skills,
    install_genomi_command_shim,
    install_host_agent_skill,
    parse_args,
    parse_library_selection,
    print_summary,
    resolve_genome_source_user_nickname,
    resolve_library_selection,
)
from _install_for_agents_downloads import (  # noqa: F401  (explicit; incl. underscore names)
    _report_existing_install,
    _verify,
    run,
)

# Per-library override args forwarded to the manager (manual sources, version
# pins, ancestry-panel escape hatches).
_OVERRIDE_ARGS = (
    "msigdb_gmt",
    "msigdb_gmt_url",
    "pharmcat_version",
    "ancestry_panel_url",
    "ancestry_panel_dir",
)


def install_libraries(selected: list[str], *, force: bool, args=None) -> None:
    """Materialize each selected library through the central manager."""
    _ensure_src_on_path()
    from genomi.runtime.libraries import manager as library_manager

    overrides = {
        name: value
        for name in _OVERRIDE_ARGS
        if (value := getattr(args, name, None))
    }
    for library in selected:
        print(f"Installing {library} ...")
        print_summary(library_manager.refresh(library, force=force, **overrides))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.genomi_home:
        os.environ["GENOMI_HOME"] = str(Path(args.genomi_home).expanduser())

    selected = resolve_library_selection(args.libraries)
    print(f"Genomi libraries: {', '.join(selected) if selected else 'no public libraries selected'}")

    _report_existing_install(selected, force=args.force)

    if not args.skip_package:
        command = [sys.executable, "-m", "pip", "install", "-e", str(REPO_ROOT)]
        run(command)

    genomi_command = install_genomi_command_shim()

    if selected:
        install_libraries(selected, force=args.force, args=args)

    configure_genome_source(args)

    install_host_agent_skill(args)

    if not args.skip_verify:
        _verify("$GENOMI_HOME/bin/genomi tools", [str(genomi_command), "tools"])

    genomi_home = genomi_home_path()
    print("")
    print("Genomi install complete.")
    print(f"  GENOMI_HOME: {genomi_home}")
    print(f"  Command:     {genomi_command}")
    print(f"  PATH:        export PATH=\"{genomi_command.parent}:$PATH\"")
    if selected:
        print(f"  Libraries:   {', '.join(selected)}")
    print("  Next:        reload the host MCP server and use the Genomi host skill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
