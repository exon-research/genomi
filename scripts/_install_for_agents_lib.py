"""Core metadata, configuration, and host-wiring helpers for the Genomi
agent installer.

This module holds the bulk of the installer implementation so that the
``scripts/install_for_agents.py`` entry point stays small. It is imported both
when the entry point is run as a CLI and when the test suite loads
``scripts/install_for_agents.py`` directly via ``importlib``.

Download/verify/install-library helpers live in
``_install_for_agents_downloads`` to keep every module under the line budget.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# Every reference-library fact (ids, sizes, purposes, URLs, sha256/versions,
# transforms, paths, freshness) lives once in the central registry
# (``genomi.runtime.libraries.registry``); the installer drives the manager and
# no longer keeps its own catalog. Only the install-script user agent stays here.
GENOMI_USER_AGENT = "Genomi installer/0.1 (+https://www.genomiagent.com/)"


def _library_manager():
    """Import the central library manager, ensuring src/ is importable first."""
    _ensure_src_on_path()
    from genomi.runtime.libraries import manager

    return manager


def genomi_home_path() -> Path:
    _ensure_src_on_path()
    from genomi.runtime.paths import genomi_data_root

    return genomi_data_root().resolve(strict=False)


def install_genomi_command_shim() -> Path:
    """Install a stable `genomi` launcher independent of pip's script dir."""

    genomi_home = genomi_home_path()
    bin_dir = genomi_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "genomi"
    # Use the running interpreter as-is — do NOT resolve symlinks. In a
    # virtualenv (including the `uv venv` / `python -m venv` fallback the docs
    # recommend on PEP 668 hosts) the venv's `python` is normally a symlink back
    # to the base interpreter. Path.resolve()/realpath would follow it out of the
    # venv to a base Python that lacks the editable `genomi` install — it only
    # lives in the venv's site-packages — so the shim would launch the wrong
    # interpreter and fail with "No module named genomi". abspath() normalizes
    # the path (absolute, no `..`) without dereferencing the symlink, keeping the
    # shim pointed at the venv interpreter. `python -m venv --copies` (real file,
    # not a symlink) also works either way.
    python = Path(os.path.abspath(os.path.expanduser(sys.executable)))
    # The runtime updates itself: `genomi update` runs `git pull --ff-only` on
    # the checkout it lives in (an editable `pip install -e` install picks up the
    # pulled source directly). No update command is exported here — and we must
    # not export the legacy GENOMI_RUNTIME_UPDATE, which now signals "skip the
    # git pull" and would defeat self-update for this git checkout.
    content = (
        "#!/usr/bin/env sh\n"
        'if [ -z "${GENOMI_HOME:-}" ]; then\n'
        f"  GENOMI_HOME={shlex.quote(str(genomi_home))}\n"
        "fi\n"
        "export GENOMI_HOME\n"
        f"exec {shlex.quote(str(python))} -m genomi \"$@\"\n"
    )
    shim.write_text(content, encoding="utf-8")
    shim.chmod(0o755)
    return shim


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Genomi for agent use.")
    parser.add_argument(
        "--libraries",
        help=(
            "Public data purpose to install (e.g. everything, common-questions, "
            "medication-response), or exact comma-separated library IDs. See "
            "genomi.runtime.libraries.registry for the full catalog."
        ),
    )
    parser.add_argument("--skip-package", action="store_true", help="Skip editable package installation.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip post-install verification commands.")
    parser.add_argument("--genomi-home", help="Set GENOMI_HOME for installed libraries and runtime state.")
    parser.add_argument("--force", action="store_true", help="Re-download selected libraries even if present.")
    parser.add_argument(
        "--msigdb-gmt",
        help="Path to an official MSigDB Hallmark GMT export to copy when msigdb-hallmark is selected.",
    )
    parser.add_argument(
        "--msigdb-gmt-url",
        help="Download URL for an official MSigDB Hallmark GMT export when msigdb-hallmark is selected.",
    )
    parser.add_argument(
        "--pharmcat-version",
        help=(
            "Pin a specific PharmCAT release tag (e.g. 'v2.15.5'). When omitted, "
            "the installer queries GitHub for the latest stable release."
        ),
    )
    parser.add_argument(
        "--ancestry-panel-dir",
        help="Copy a prebuilt compact ancestry panel directory instead of downloading the released tarball.",
    )
    parser.add_argument(
        "--ancestry-panel-url",
        help="Override the ancestry panel tarball URL (escape hatch for mirrors or unreleased builds).",
    )
    parser.add_argument(
        "--genome-source",
        help="Optional genome source to import after setup, such as VCF, gVCF, BAM, 23andMe, or AncestryDNA raw data.",
    )
    parser.add_argument(
        "--user-nickname",
        default=None,
        help=(
            "User/profile nickname for --genome-source. Defaults to 'Default user' only when no "
            "users exist. Required when users already exist."
        ),
    )
    parser.add_argument(
        "--set-default-user",
        action="store_true",
        help="Make the user/profile the default auto-selected user.",
    )
    parser.add_argument(
        "--host-skill-dir",
        action="append",
        default=None,
        help=(
            "Install the Genomi host-agent skill into this skills directory. "
            "Can be repeated. Defaults to auto-detecting common host and "
            "shared Agent Skills directories when they already exist."
        ),
    )
    parser.add_argument(
        "--skip-host-skill",
        action="store_true",
        help="Do not install the Genomi host-agent skill.",
    )
    return parser.parse_args(argv)


def resolve_library_selection(value: str | None) -> list[str]:
    if value is None:
        raise SystemExit(
            "Library selection requires an explicit --libraries value. "
            "Pass one exact purpose (e.g. everything) or exact library IDs."
        )
    return parse_library_selection(value)


def parse_library_selection(value: str) -> list[str]:
    """Resolve a purpose name or comma-separated library IDs through the central
    registry (the single source of truth for the catalog)."""
    if not value.strip():
        raise SystemExit("Choose one exact purpose (e.g. everything) or exact library IDs.")
    try:
        return _library_manager().resolve_selection(value.strip().lower())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


HOST_AGENT_SKILL_DIR = REPO_ROOT
CAPABILITY_SKILLS_ROOT = REPO_ROOT / "skills"
CAPABILITY_SKILL_DIRS_TO_SKIP = frozenset({"host-agent", "conventions"})
# Host-agent skill directories that follow the Anthropic SKILL.md convention.
# Hosts differ in how they invoke installed skills, so the installer only links
# SKILL.md into known skill directories. Invocation must come from the active
# host's own skill list/help instead of being inferred from a directory name.
DEFAULT_HOST_SKILL_PARENTS = (
    Path("~/.claude/skills"),
    Path("~/.codex/skills"),
    Path("~/.openclaw/skills"),
    Path("~/.hermes/skills"),
    Path("~/.agents/skills"),
)


def install_host_agent_skill(args: argparse.Namespace) -> None:
    """Symlink the in-repo Genomi skill into each detected host-agent skills dir.

    Symlinks (rather than copies) so updates to the canonical skill in the
    Genomi repo propagate to every host without re-running the installer.
    """
    if getattr(args, "skip_host_skill", False):
        return
    if not HOST_AGENT_SKILL_DIR.is_dir() or not (HOST_AGENT_SKILL_DIR / "SKILL.md").is_file():
        print(
            f"Skipping host-agent skill: canonical source not found at {HOST_AGENT_SKILL_DIR}",
            file=sys.stderr,
        )
        return

    raw_targets = getattr(args, "host_skill_dir", None)
    if raw_targets:
        parents = [Path(p).expanduser() for p in raw_targets]
    else:
        parents = [p.expanduser() for p in DEFAULT_HOST_SKILL_PARENTS if p.expanduser().exists()]

    if not parents:
        print(
            "No host-agent skill directories detected. "
            "Pass --host-skill-dir <path> to install the Genomi skill explicitly, "
            "or --skip-host-skill to silence this notice.",
            file=sys.stderr,
        )
        return

    source = HOST_AGENT_SKILL_DIR.resolve()
    installed_any = False
    for parent in parents:
        link = parent / "genomi"
        parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == source:
                print(f"Genomi host skill already linked: {link} -> {source}")
                installed_any = True
                continue
            link.unlink()
        elif link.exists():
            if getattr(args, "force", False):
                shutil.rmtree(link)
            else:
                print(
                    f"Skipping {link}: a non-symlink directory or file already exists. "
                    "Pass --force to replace it.",
                    file=sys.stderr,
                )
                continue
        link.symlink_to(source, target_is_directory=True)
        print(f"Genomi host skill installed: {link} -> {source}")
        installed_any = True
    if installed_any:
        print("Host skill invocation:")
        print("  Invocation is controlled by the active host, not by this installer.")
        print("  Ask the host to list installed skills, then use that host's documented skill syntax.")
        print("  Do not assume /genomi works in every host.")
    install_capability_skills(args)


def _capability_skill_sources() -> list[tuple[str, Path]]:
    """Return (capability_name, abs_skill_dir) for every per-capability skill."""
    out: list[tuple[str, Path]] = []
    if not CAPABILITY_SKILLS_ROOT.is_dir():
        return out
    for entry in sorted(CAPABILITY_SKILLS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in CAPABILITY_SKILL_DIRS_TO_SKIP:
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        out.append((entry.name, entry.resolve()))
    return out


def install_capability_skills(args: argparse.Namespace) -> None:
    """Symlink each per-capability skill dir into every detected host skill dir.

    Per-capability skills (e.g. ``skills/decode``, ``skills/clinvar``) land at
    ``~/.claude/skills/genomi-<name>/`` so the host's skill matcher can read
    each one's ``description:`` frontmatter and route on it. The monolithic
    ``~/.claude/skills/genomi`` skill remains as the umbrella entry.
    """
    if getattr(args, "skip_host_skill", False):
        return
    sources = _capability_skill_sources()
    if not sources:
        return

    raw_targets = getattr(args, "host_skill_dir", None)
    if raw_targets:
        parents = [Path(p).expanduser() for p in raw_targets]
    else:
        parents = [p.expanduser() for p in DEFAULT_HOST_SKILL_PARENTS if p.expanduser().exists()]
    if not parents:
        return

    force = bool(getattr(args, "force", False))
    installed = 0
    for parent in parents:
        parent.mkdir(parents=True, exist_ok=True)
        for cap_name, cap_source in sources:
            link = parent / f"genomi-{cap_name}"
            if link.is_symlink():
                if link.resolve() == cap_source:
                    installed += 1
                    continue
                link.unlink()
            elif link.exists():
                if force:
                    shutil.rmtree(link)
                else:
                    print(
                        f"Skipping {link}: non-symlink already exists. "
                        "Pass --force to replace it.",
                        file=sys.stderr,
                    )
                    continue
            link.symlink_to(cap_source, target_is_directory=True)
            installed += 1
    if installed:
        print(f"Genomi per-capability skills linked: {installed} symlinks across {len(parents)} host dir(s).")


def configure_genome_source(
    args: argparse.Namespace,
    *,
    load_existing_users: Callable[[], list[dict[str, object]]] | None = None,
) -> None:
    source = args.genome_source
    user_nickname = args.user_nickname.strip() if args.user_nickname else None
    set_default_user = bool(args.set_default_user)

    if not source:
        return

    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise SystemExit(f"Genome source does not exist: {source_path}")
    _ensure_src_on_path()
    existing_users = (load_existing_users or _load_existing_users)()
    user_nickname = resolve_genome_source_user_nickname(
        user_nickname,
        existing_users=existing_users,
    )
    from genomi.operations import call_operation

    print(f"Importing genome source as Active Genome Index: {source_path}")
    params = {
        "source": str(source_path),
        "user_nickname": user_nickname,
        "set_default_user": set_default_user,
    }
    result = call_operation("genomi.parse_source", params)
    active = result.get("active_genome_index") if isinstance(result, dict) else {}
    if isinstance(active, dict):
        default = " [default user]" if set_default_user else ""
        print(f"  Active Genome Index: {active.get('agi_id') or '(unknown)'} for {user_nickname}{default}")
    print_summary(result if isinstance(result, dict) else {"status": "completed", "output": ""})


def _ensure_src_on_path() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


def _load_existing_users() -> list[dict[str, object]]:
    _ensure_src_on_path()
    from genomi.runtime import context as runtime_context

    return [user for user in runtime_context.list_users() if isinstance(user, dict)]


def resolve_genome_source_user_nickname(
    provided_nickname: str | None,
    *,
    existing_users: list[dict[str, object]],
) -> str:
    nickname = (provided_nickname or "").strip()
    if nickname:
        return nickname
    if not existing_users:
        return "Default user"
    raise SystemExit(
        "GENOMI_HOME already has users. Pass --user-nickname to assign this genome source "
        "to an existing user or a new user."
    )


def print_summary(payload: dict[str, object]) -> None:
    status = payload.get("status") or "completed"
    output = payload.get("output") or payload.get("manifest_path") or ""
    print(f"  {status}: {output}")
