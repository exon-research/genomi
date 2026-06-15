"""Reconcile the host-agent skill symlinks that point at a Genomi checkout.

A Genomi checkout ships an umbrella ``SKILL.md`` at its root plus one
per-capability skill under ``skills/<name>/``. Hosts that follow the Anthropic
``SKILL.md`` convention (Claude Code, Codex, OpenClaw, Hermes, and the generic
``~/.agents`` location) discover skills by symlink:

    ~/.claude/skills/genomi            -> <checkout>
    ~/.claude/skills/genomi-<name>     -> <checkout>/skills/<name>

This module is the single owner of that wiring. Both the first-time bootstrap
(``scripts/install_for_agents.py``) and the in-place updater
(``genomi install``) call :func:`reconcile_host_skill_links`, so a link that was
correct at bootstrap but later went stale — e.g. a checkout that moved off
``/tmp`` — is repaired on the next update instead of silently dangling.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Host-agent skill directories that follow the Anthropic SKILL.md convention.
# Hosts differ in how they invoke installed skills, so we only link SKILL.md
# into known skill directories; invocation must come from the active host's own
# skill list rather than being inferred from a directory name.
DEFAULT_HOST_SKILL_PARENTS: tuple[Path, ...] = (
    Path("~/.claude/skills"),
    Path("~/.codex/skills"),
    Path("~/.openclaw/skills"),
    Path("~/.hermes/skills"),
    Path("~/.agents/skills"),
)

# Skill directories that are not host-agent capabilities and must not be linked.
CAPABILITY_SKILL_DIRS_TO_SKIP = frozenset({"host-agent", "conventions"})

# The umbrella link name and the per-capability link prefix.
ROOT_SKILL_LINK_NAME = "genomi"
CAPABILITY_SKILL_LINK_PREFIX = "genomi-"


def default_existing_parents() -> list[Path]:
    """Default host skill dirs that already exist on this machine.

    Updates link only into host directories that are present, so a machine that
    has never installed (say) Codex does not get a ``~/.codex/skills`` tree
    created for it.
    """
    return [p.expanduser() for p in DEFAULT_HOST_SKILL_PARENTS if p.expanduser().exists()]


def capability_skill_sources(source_root: Path) -> list[tuple[str, Path]]:
    """``(capability_name, absolute_skill_dir)`` for each per-capability skill.

    A directory under ``<source_root>/skills`` qualifies when it ships a
    ``SKILL.md`` and is not in :data:`CAPABILITY_SKILL_DIRS_TO_SKIP`.
    """
    skills_root = source_root / "skills"
    out: list[tuple[str, Path]] = []
    if not skills_root.is_dir():
        return out
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or entry.name in CAPABILITY_SKILL_DIRS_TO_SKIP:
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        out.append((entry.name, entry.resolve()))
    return out


def planned_links(source_root: Path) -> list[tuple[str, Path]]:
    """``(link_name, target)`` pairs: the umbrella skill plus one per capability."""
    links: list[tuple[str, Path]] = [(ROOT_SKILL_LINK_NAME, source_root.resolve())]
    for cap_name, cap_source in capability_skill_sources(source_root):
        links.append((f"{CAPABILITY_SKILL_LINK_PREFIX}{cap_name}", cap_source))
    return links


def _link_state(link: Path, target: Path) -> str:
    """Classify ``link`` against its intended ``target``.

    Returns one of ``ok`` (already a symlink to target), ``stale`` (symlink to
    the wrong existing path), ``dangling`` (symlink whose target is gone),
    ``conflict`` (a real file/dir occupying the name), or ``missing``.
    """
    if link.is_symlink():
        try:
            return "ok" if link.resolve(strict=True) == target.resolve() else "stale"
        except (OSError, RuntimeError):
            return "dangling"
    if link.exists():
        return "conflict"
    return "missing"


def _replace_with_symlink(link: Path, target: Path) -> None:
    if link.is_dir() and not link.is_symlink():
        shutil.rmtree(link)
    else:
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def _is_genomi_capability_link(link: Path) -> bool:
    return link.name.startswith(CAPABILITY_SKILL_LINK_PREFIX)


def _remove_orphaned_capability_links(parent: Path, planned_names: set[str]) -> list[dict[str, str]]:
    """Remove obsolete Genomi-owned capability symlinks from ``parent``.

    Genomi owns the ``genomi-<capability>`` prefix inside host skill dirs. If a
    capability skill is deleted or renamed, keeping its old symlink installed
    would let the host keep loading stale skill guidance after an update.
    Non-symlink conflicts are left alone and reported only when their name is a
    planned current link.
    """
    removed: list[dict[str, str]] = []
    for link in sorted(parent.iterdir()):
        if link.name in planned_names:
            continue
        if not link.is_symlink() or not _is_genomi_capability_link(link):
            continue
        previous = os.readlink(link)
        link.unlink()
        removed.append({"name": link.name, "previous_target": previous})
    return removed


def reconcile_host_skill_links(
    source_root: Path | str,
    *,
    parents: list[Path | str] | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Create, repair, or leave host-agent skill symlinks for ``source_root``.

    ``parents`` selects the host skill directories to populate; when omitted,
    only the default host dirs that already exist are used. Each parent is
    created if needed. Correct links are left untouched; stale or dangling links
    are re-pointed; a non-symlink occupying a link name is left in place unless
    ``force`` replaces it. Returns a structured report of what changed.
    """
    source_root = Path(source_root)
    if not source_root.is_dir() or not (source_root / "SKILL.md").is_file():
        return {
            "status": "skipped",
            "reason": "source_skill_not_found",
            "source_root": str(source_root),
        }

    target_parents = (
        default_existing_parents()
        if parents is None
        else [Path(p).expanduser() for p in parents]
    )

    links = planned_links(source_root)
    planned_names = {name for name, _target in links}
    host_dirs: list[dict[str, object]] = []
    totals = {"created": 0, "repaired": 0, "ok": 0, "skipped_conflict": 0, "removed_orphaned": 0}

    for parent in target_parents:
        parent.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        repaired: list[dict[str, str]] = []
        skipped_conflict: list[str] = []
        ok = 0
        for name, target in links:
            link = parent / name
            state = _link_state(link, target)
            if state == "ok":
                ok += 1
            elif state in ("stale", "dangling"):
                previous = os.readlink(link)
                _replace_with_symlink(link, target)
                repaired.append({"name": name, "previous_target": previous, "target": str(target)})
            elif state == "conflict":
                if force:
                    _replace_with_symlink(link, target)
                    created.append(name)
                else:
                    skipped_conflict.append(name)
            else:  # missing
                link.symlink_to(target, target_is_directory=True)
                created.append(name)

        removed_orphaned = _remove_orphaned_capability_links(parent, planned_names)
        totals["created"] += len(created)
        totals["repaired"] += len(repaired)
        totals["ok"] += ok
        totals["skipped_conflict"] += len(skipped_conflict)
        totals["removed_orphaned"] += len(removed_orphaned)

        entry: dict[str, object] = {"path": str(parent), "ok": ok}
        if created:
            entry["created"] = created
        if repaired:
            entry["repaired"] = repaired
        if skipped_conflict:
            entry["skipped_conflict"] = skipped_conflict
        if removed_orphaned:
            entry["removed_orphaned"] = removed_orphaned
        host_dirs.append(entry)

    return {
        "status": "completed",
        "source_root": str(source_root.resolve()),
        "host_dirs": host_dirs,
        "summary": {"host_dir_count": len(target_parents), **totals},
    }
