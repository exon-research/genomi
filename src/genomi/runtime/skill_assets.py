"""Locate the canonical Genomi agent-skill tree in source and wheel installs.

Source checkouts keep the canonical documents at ``<repo>/SKILL.md`` and
``<repo>/skills/**``.  Wheels install that same tree as data files under
``<environment>/share/genomi``.  Runtime discovery and host-skill linking use
this module so neither surface has to guess whether Genomi came from git or a
package manager.
"""

from __future__ import annotations

import sysconfig
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePosixPath


_DISTRIBUTION_NAME = "genomi"
_PACKAGED_SKILL_SUFFIX = ("share", "genomi", "SKILL.md")


def is_skill_root(path: Path | str | None) -> bool:
    """Return whether ``path`` contains the umbrella and focused skill tree."""

    if path is None:
        return False
    candidate = Path(path)
    return (candidate / "SKILL.md").is_file() and (candidate / "skills").is_dir()


def source_checkout_skill_root() -> Path | None:
    """Return the repository skill root when running from a source checkout."""

    candidate = Path(__file__).resolve().parents[3]
    return candidate if is_skill_root(candidate) else None


def packaged_skill_root() -> Path | None:
    """Return the wheel-installed ``share/genomi`` skill tree, when present."""

    try:
        distribution = importlib_metadata.distribution(_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        distribution = None

    if distribution is not None:
        for entry in distribution.files or ():
            parts = PurePosixPath(str(entry)).parts
            if tuple(parts[-3:]) != _PACKAGED_SKILL_SUFFIX:
                continue
            candidate = Path(distribution.locate_file(entry)).resolve().parent
            if is_skill_root(candidate):
                return candidate

    # ``pip --target`` installs data files beside the package tree, but
    # importlib.metadata intentionally omits RECORD entries containing ``..``.
    # Walking package ancestors also covers ordinary virtual environments,
    # where code lives under ``lib/pythonX/site-packages`` and data under the
    # environment's ``share`` directory.
    package_path = Path(__file__).resolve()
    for ancestor in package_path.parents:
        candidate = ancestor / "share" / "genomi"
        if is_skill_root(candidate):
            return candidate

    # Some package installers omit data-file entries from distribution
    # metadata.  The wheel destination is still the interpreter's data prefix.
    data_root = sysconfig.get_path("data")
    if data_root:
        candidate = Path(data_root) / "share" / "genomi"
        if is_skill_root(candidate):
            return candidate
    return None


def resolve_skill_root(preferred: Path | str | None = None) -> Path | None:
    """Resolve a usable skill root, preferring an explicitly supplied checkout."""

    if is_skill_root(preferred):
        return Path(preferred).resolve()
    return source_checkout_skill_root() or packaged_skill_root()


def skill_document_path(
    relative_path: str,
    *,
    preferred_root: Path | str | None = None,
) -> Path | None:
    """Resolve one declared skill document without allowing path traversal."""

    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = resolve_skill_root(preferred_root)
    if root is None:
        return None
    candidate = root.joinpath(*relative.parts)
    return candidate if candidate.is_file() else None
