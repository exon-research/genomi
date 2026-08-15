"""Genomi Lab setup and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..runtime import host_skills
from ..runtime.paths import genomi_data_root
from ..runtime.private_storage import (
    atomic_write_private_text,
    ensure_private_directory,
)
from .specialist_policies import (
    SpecialistPolicyError,
    policy_manifest_bytes,
    policy_manifest_sha256,
    read_installed_policy,
)
from .store import GenomiLabStore, default_store_path, lab_root


JsonObject = dict[str, Any]
INSTALLED_POLICY_FILENAME = "specialist-policies.json"
_SQLITE_DATABASE_MAGIC = b"SQLite format 3\x00"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def lab_setup_root(root: str | Path | None = None) -> Path:
    return genomi_data_root(root) / "lab" / "setup"


def installed_policy_path(root: str | Path | None = None) -> Path:
    return lab_setup_root(root) / INSTALLED_POLICY_FILENAME


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
    lab_planned = any(name == "genomi-lab" for name, _target in planned)
    return {
        "status": (
            "ready"
            if lab_planned and not missing and not conflicts
            else "needs_setup"
        ),
        "source_root": str(source_root),
        "host_dirs": host_dirs,
        "summary": {
            "host_dir_count": len(target_parents),
            "planned_link_count": len(planned),
            "lab_skill_planned": lab_planned,
            "missing_or_stale": missing,
            "conflicts": conflicts,
        },
    }


def _storage_check(root: Path) -> JsonObject:
    target_root = lab_root(root)
    database = default_store_path(root)
    database_state = _private_file_state(database, magic=_SQLITE_DATABASE_MAGIC)
    ready = (
        target_root.is_dir()
        and database_state == "private_file"
    )
    if database_state == "private_file":
        database_state = "sqlite"
    return {
        "status": "ready" if ready else "needs_setup",
        "root": str(target_root),
        "database": str(database),
        "database_state": database_state,
        "local_threat_model": "private_posix_user",
        "read_only_probe": True,
    }


def _private_file_state(path: Path, *, magic: bytes | None = None) -> str:
    if path.is_symlink():
        return "unsafe_symlink"
    if not path.is_file():
        return "missing"
    try:
        if path.stat().st_mode & 0o777 != 0o600:
            return "unsafe_permissions"
        if magic is not None:
            with path.open("rb") as handle:
                if handle.read(len(magic)) != magic:
                    return "unsupported_format"
    except OSError:
        return "unreadable"
    return "private_file"


def _policy_check(root: Path) -> JsonObject:
    path = installed_policy_path(root)
    if not path.is_file() or path.is_symlink():
        return {"status": "needs_setup", "path": str(path), "state": "missing"}
    try:
        read_installed_policy(path)
    except (OSError, ValueError, SpecialistPolicyError):
        return {
            "status": "needs_setup",
            "path": str(path),
            "state": "invalid_or_stale",
        }
    return {
        "status": "ready",
        "path": str(path),
        "state": "verified",
        "sha256": policy_manifest_sha256(),
    }


def _operation_check() -> JsonObject:
    from ..operations import all_operations

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


def _portal_assets_check() -> JsonObject:
    static = Path(__file__).resolve().parent / "static"
    required = ("index.html", "app.js", "styles.css")
    available = [name for name in required if static.joinpath(name).is_file()]
    return {
        "status": "ready" if len(available) == len(required) else "needs_setup",
        "required": list(required),
        "available": available,
    }


def run_lab_setup(
    *,
    check: bool = False,
    source_root: str | Path | None = None,
    root: str | Path | None = None,
    host_skill_parents: list[str | Path] | None = None,
) -> JsonObject:
    """Install or inspect local Lab surfaces without patient-derived probes."""

    checkout = Path(source_root) if source_root is not None else _source_root()
    data_root = genomi_data_root(root)
    parents = (
        None
        if host_skill_parents is None
        else [Path(parent).expanduser() for parent in host_skill_parents]
    )
    if not check:
        host_skills.reconcile_host_skill_links(checkout, parents=parents)
        ensure_private_directory(data_root)
        ensure_private_directory(lab_root(data_root), private_root=data_root)
        GenomiLabStore(path=default_store_path(data_root))
        policy_root = lab_setup_root(data_root)
        ensure_private_directory(policy_root, private_root=data_root)
        atomic_write_private_text(
            installed_policy_path(data_root),
            policy_manifest_bytes().decode("utf-8"),
            private_root=data_root,
        )

    components = {
        "skills": _skill_check(checkout, parents=parents),
        "specialist_policies": _policy_check(data_root),
        "record_mcp": _operation_check(),
        "storage": _storage_check(data_root),
        "portal_assets": _portal_assets_check(),
    }
    ready = all(item["status"] == "ready" for item in components.values())
    result: JsonObject = {
        "status": (
            "ready"
            if check and ready
            else "needs_setup"
            if check
            else "completed"
            if ready
            else "action_required"
        ),
        "mode": "check" if check else "setup",
        "read_only": check,
        "components": components,
        "privacy": {
            "patient_context_accessed": False,
            "provider_probe_input": "fixed_public_or_synthetic_only",
        },
    }
    return result


__all__ = ["installed_policy_path", "lab_setup_root", "run_lab_setup"]
