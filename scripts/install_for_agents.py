#!/usr/bin/env python3
"""Genomi agent installer entry point.

The bulk of the implementation lives in sibling modules
(``_install_for_agents_lib`` and ``_install_for_agents_downloads``) to keep
each file under the line budget. This thin entry point re-exports the public
API so the module stays importable both as a CLI and via ``importlib`` (the
test suite loads this exact file path).

``main`` is defined here so that the helpers it calls by name resolve against
this module's namespace — that keeps ``mock.patch.object(install_for_agents,
"run")`` and friends working in the test suite.
"""
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
    ANCESTRY_PANEL_TARBALL_SHA256,
    ANCESTRY_PANEL_TARBALL_URL,
    ANCESTRY_PANEL_VERSION,
    BWA_MEM2_LINUX_X64_SHA256,
    BWA_MEM2_LINUX_X64_URL,
    BWA_MEM2_VERSION,
    CAPABILITY_SKILL_DIRS_TO_SKIP,
    CAPABILITY_SKILLS_ROOT,
    CELLMARKER_HUMAN_URL,
    DEFAULT_HOST_SKILL_PARENTS,
    DEFAULT_LIBRARIES,
    ENCODE_CCRE_GRCH38_URL,
    GENCODE_GRCH37_URL,
    GENCODE_GRCH38_URL,
    GENOMI_USER_AGENT,
    HOST_AGENT_SKILL_DIR,
    LIBRARIES,
    LIBRARY_PURPOSES,
    LIBRARY_SIZES,
    MANUAL_SOURCE_LIBRARIES,
    MINIMAP2_LINUX_X64_SHA256,
    MINIMAP2_LINUX_X64_URL,
    MINIMAP2_VERSION,
    OPT_IN_LARGE_LIBRARIES,
    PANGLAODB_MARKERS_URL,
    PHARMCAT_RELEASES_API_URL,
    REPO_ROOT,
    SRC_DIR,
    _MCP_HOST_WRITERS,
    _capability_skill_sources,
    _ensure_src_on_path,
    _load_existing_users,
    _mcp_write_codex_toml,
    _mcp_write_hermes_yaml,
    _mcp_write_json_mcpservers,
    _mcp_write_openclaw_json,
    configure_genome_source,
    genomi_home_path,
    install_capability_skills,
    install_genomi_command_shim,
    install_host_agent_skill,
    install_mcp_config,
    parse_args,
    parse_library_selection,
    print_summary,
    resolve_genome_source_user_nickname,
    resolve_library_selection,
)
from _install_for_agents_downloads import (  # noqa: F401  (explicit; incl. underscore names)
    _abort_on_existing_install,
    _copy_ancestry_panel,
    _download_ancestry_panel,
    _fetch_pharmcat_release,
    _select_pharmcat_jar_asset,
    _sha256_file,
    _verify,
    download_library_file,
    install_aligner_binary,
    install_cellmarker_human,
    install_libraries,
    install_msigdb_hallmark,
    install_pharmcat,
    normalize_cellmarker_xlsx,
    run,
    write_manifest,
)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.genomi_home:
        os.environ["GENOMI_HOME"] = str(Path(args.genomi_home).expanduser())

    selected = resolve_library_selection(args.libraries)
    print(f"Genomi libraries: {', '.join(selected) if selected else 'no public libraries selected'}")

    _abort_on_existing_install(selected, force=args.force)

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
