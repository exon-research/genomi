"""Host-neutral GenomiLab setup, verification, and synthetic demo seeding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..operations import all_operations
from ..runtime import host_skills
from ..runtime.paths import genomi_data_root
from ..runtime.private_storage import ensure_private_directory
from .demo_ctla4 import (
    DEMO_USER_ID,
    seed_ctla4_demo,
)
from .store import GenomiLabStore, default_store_path, lab_root


JsonObject = dict[str, Any]

_ENCRYPTED_DATABASE_MAGIC = b"GENOMILAB-ENCRYPTED-SQLITE\x00"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _skill_check(
    source_root: Path,
    *,
    parents: list[Path] | None = None,
) -> JsonObject:
    planned = host_skills.planned_links(source_root)
    target_parents = (
        host_skills.default_existing_parents() if parents is None else parents
    )
    host_dirs: list[JsonObject] = []
    missing = 0
    conflicts = 0
    for parent in target_parents:
        entries: list[JsonObject] = []
        for name, target in planned:
            link = parent / name
            if link.is_symlink():
                try:
                    state = (
                        "ok"
                        if link.resolve(strict=True) == target.resolve()
                        else "stale"
                    )
                except (OSError, RuntimeError):
                    state = "dangling"
            elif link.exists():
                state = "conflict"
            else:
                state = "missing"
            missing += int(state in {"missing", "stale", "dangling"})
            conflicts += int(state == "conflict")
            entries.append({"name": name, "state": state, "target": str(target)})
        host_dirs.append({"path": str(parent), "links": entries})
    return {
        "status": "ready"
        if target_parents and not missing and not conflicts
        else "needs_setup",
        "source_root": str(source_root),
        "host_dirs": host_dirs,
        "summary": {
            "host_dir_count": len(target_parents),
            "planned_link_count": len(planned),
            "missing_or_stale": missing,
            "conflicts": conflicts,
        },
    }


def _storage_check(root: Path) -> JsonObject:
    private_root = genomi_data_root(root)
    target_root = lab_root(private_root)
    database = default_store_path(private_root)
    database_state = "missing"
    if database.is_symlink():
        database_state = "unsafe_symlink"
    elif database.is_file():
        try:
            with database.open("rb") as handle:
                database_state = (
                    "encrypted"
                    if handle.read(len(_ENCRYPTED_DATABASE_MAGIC))
                    == _ENCRYPTED_DATABASE_MAGIC
                    else "unsupported_format"
                )
        except OSError:
            database_state = "unreadable"

    key_directory = target_root / ".keys"
    key_directory_state = (
        "private_directory_available" if key_directory.is_dir() else "missing"
    )

    return {
        "status": (
            "ready"
            if target_root.is_dir()
            and database_state == "encrypted"
            and key_directory_state == "private_directory_available"
            else "needs_setup"
        ),
        "root": str(target_root),
        "root_exists": target_root.is_dir(),
        "database": str(database),
        "database_state": database_state,
        "local_key_state": key_directory_state,
        "local_threat_model": "private_posix_user",
        "read_only_probe": True,
    }


def _record_mcp_check() -> JsonObject:
    names = sorted(
        str(tool.get("name"))
        for tool in all_operations()
        if str(tool.get("name") or "").startswith("lab.")
    )
    return {
        "status": "ready" if names else "needs_setup",
        "transport": "existing_genomi_serve_mcp",
        "operations": names,
    }


def run_lab_setup(
    *,
    check: bool = False,
    demo: bool | str = False,
    source_root: str | Path | None = None,
    root: str | Path | None = None,
    host_skill_parents: list[str | Path] | None = None,
) -> JsonObject:
    """Install or inspect the host-neutral GenomiLab local surfaces."""

    checkout = Path(source_root) if source_root is not None else _source_root()
    data_root = genomi_data_root(root)
    parents = (
        None
        if host_skill_parents is None
        else [Path(parent).expanduser() for parent in host_skill_parents]
    )
    demo_fixture = "ctla4" if demo is True else str(demo or "").strip()
    if demo_fixture and demo_fixture != "ctla4":
        raise ValueError("the supported GenomiLab demo fixture is 'ctla4'")
    if check:
        if demo:
            raise ValueError("--check and --demo are mutually exclusive")
        components = {
            "skills": _skill_check(checkout, parents=parents),
            "record_mcp": _record_mcp_check(),
            "storage": _storage_check(data_root),
        }
        return {
            "status": (
                "ready"
                if all(item["status"] == "ready" for item in components.values())
                else "needs_setup"
            ),
            "mode": "check",
            "read_only": True,
            "host_neutral_v1": True,
            "components": components,
            "deferred": ["specialist_agent_profiles", "provider_integrations"],
        }

    skill_result = host_skills.reconcile_host_skill_links(
        checkout,
        parents=parents,
    )
    ensure_private_directory(data_root)
    ensure_private_directory(lab_root(data_root), private_root=data_root)
    store = GenomiLabStore(path=default_store_path(data_root))
    components = {
        "skills": skill_result,
        "record_mcp": _record_mcp_check(),
        "storage": _storage_check(data_root),
    }
    result: JsonObject = {
        "status": "completed",
        "mode": "demo" if demo else "setup",
        "read_only": False,
        "host_neutral_v1": True,
        "components": components,
        "deferred": ["specialist_agent_profiles", "provider_integrations"],
    }
    if demo_fixture:
        result["demo"] = seed_ctla4_demo(store)
    return result


__all__ = ["DEMO_USER_ID", "run_lab_setup"]
