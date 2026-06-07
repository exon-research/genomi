from __future__ import annotations

import shutil
from pathlib import Path

from ..paths import genomi_data_root
from .agi_inference import infer_agi_record
from .agi_registry import find_agi_by_intake_source
from .agi_summary import describe_context
from .normalize import AGI_ACCESS_KEY, JsonObject, _now
from .storage import load_context, load_registry, save_context, save_registry


def remove_active_genome_index(
    *,
    agi_id: str | None = None,
    agi_ids: list[str] | None = None,
    source: str | Path | None = None,
    sources: list[str | Path] | None = None,
    remove_artifacts: bool = True,
    root: str | Path | None = None,
) -> JsonObject:
    registry = load_registry(root)
    context = load_context(root)
    targets = _resolve_removal_targets(
        registry,
        context,
        agi_id=agi_id,
        agi_ids=agi_ids,
        source=source,
        sources=sources,
        root=root,
    )
    if not targets:
        raise KeyError("active_genome_index")

    cleanup_results: list[tuple[str, JsonObject, JsonObject]] = []
    for target_agi_id, run in targets:
        artifacts = _remove_agi_artifacts(run, root=root) if remove_artifacts else _planned_agi_artifacts(run, root=root)
        cleanup_results.append((target_agi_id, run, artifacts))
    failures = [
        {"agi_id": target_agi_id, "artifact_cleanup": artifacts}
        for target_agi_id, _run, artifacts in cleanup_results
        if artifacts.get("failed_count")
    ]
    if failures:
        return {
            "status": "partial_failure",
            "target_count": len(targets),
            "removed_count": 0,
            "removed": [],
            "artifact_failures": failures,
            "context": describe_context(root),
        }

    removed: list[JsonObject] = []
    for target_agi_id, _run, artifacts in cleanup_results:
        removed_from_registry = bool(registry.get("agis", {}).pop(target_agi_id, None))
        removed_from_session = bool(context.get("agis", {}).pop(target_agi_id, None))
        _remove_agi_access_grant(context, target_agi_id)
        if str(context.get("active_agi_id") or "") == target_agi_id:
            context["active_agi_id"] = None
            context["active_user_id"] = None
        _remove_agi_from_users(registry, target_agi_id)
        removed.append(
            {
                "agi_id": target_agi_id,
                "removed_from_registry": removed_from_registry,
                "removed_from_session": removed_from_session,
                "artifact_cleanup": artifacts,
            }
        )

    save_registry(registry, root)
    save_context(context, root)
    return {
        "status": "completed",
        "removed_count": len(removed),
        "removed": removed,
        "artifacts_removed": remove_artifacts,
        "context": describe_context(root),
    }


def _resolve_removal_targets(
    registry: JsonObject,
    context: JsonObject,
    *,
    agi_id: str | None,
    agi_ids: list[str] | None,
    source: str | Path | None,
    sources: list[str | Path] | None,
    root: str | Path | None,
) -> list[tuple[str, JsonObject]]:
    requested_ids = [str(item) for item in ([agi_id] if agi_id else []) + list(agi_ids or []) if str(item)]
    requested_sources: list[str | Path] = ([source] if source is not None else []) + list(sources or [])
    targets: list[tuple[str, JsonObject]] = []
    seen: set[str] = set()
    for target_id in requested_ids:
        run = _resolve_removal_target(registry, context, agi_id=target_id, source=None, root=root)
        if not isinstance(run, dict):
            raise KeyError(target_id)
        resolved_id = str(run.get("agi_id") or target_id)
        if resolved_id and resolved_id not in seen:
            seen.add(resolved_id)
            targets.append((resolved_id, run))
    for target_source in requested_sources:
        run = _resolve_removal_target(registry, context, agi_id=None, source=target_source, root=root)
        if not isinstance(run, dict):
            raise KeyError(str(target_source))
        resolved_id = str(run.get("agi_id") or "")
        if not resolved_id:
            raise KeyError(str(target_source))
        if resolved_id not in seen:
            seen.add(resolved_id)
            targets.append((resolved_id, run))
    return targets


def _resolve_removal_target(
    registry: JsonObject,
    context: JsonObject,
    *,
    agi_id: str | None,
    source: str | Path | None,
    root: str | Path | None,
) -> JsonObject | None:
    if agi_id:
        target = str(agi_id)
        run = registry.get("agis", {}).get(target) or context.get("agis", {}).get(target)
        return run if isinstance(run, dict) else None
    if source:
        existing = find_agi_by_intake_source(source, root=root)
        if isinstance(existing, dict):
            return existing
        return infer_agi_record(source, status="not_registered", root=root)
    return None


def _remove_agi_access_grant(context: JsonObject, agi_id: str) -> None:
    grants = context.get(AGI_ACCESS_KEY)
    if isinstance(grants, dict):
        grants.pop(agi_id, None)


def _remove_agi_from_users(registry: JsonObject, agi_id: str) -> None:
    for user in registry.get("users", {}).values():
        if not isinstance(user, dict):
            continue
        user["agi_ids"] = [str(item) for item in user.get("agi_ids", []) if str(item) and str(item) != agi_id]
        if str(user.get("active_agi_id") or "") == agi_id:
            user["active_agi_id"] = user["agi_ids"][0] if user["agi_ids"] else None
        user["updated_at"] = _now()


def _planned_agi_artifacts(run: JsonObject, *, root: str | Path | None) -> JsonObject:
    entries = [
        {"kind": kind, "state": state}
        for kind, state, _path in _iter_agi_artifact_paths(run, root=root)
    ]
    return {
        "removed_count": 0,
        "missing_count": sum(1 for item in entries if item["state"] == "missing"),
        "skipped_count": sum(1 for item in entries if item["state"] not in {"present", "missing"}),
        "failed_count": 0,
        "entries": entries,
    }


def _remove_agi_artifacts(run: JsonObject, *, root: str | Path | None) -> JsonObject:
    removed_count = 0
    missing_count = 0
    skipped_count = 0
    failed_count = 0
    entries: list[JsonObject] = []
    for kind, state, path in _iter_agi_artifact_paths(run, root=root):
        if state == "missing":
            missing_count += 1
            entries.append({"kind": kind, "state": state})
            continue
        if state != "present":
            skipped_count += 1
            entries.append({"kind": kind, "state": state})
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            missing_count += 1
            entries.append({"kind": kind, "state": "missing"})
            continue
        except OSError as exc:
            failed_count += 1
            entries.append({"kind": kind, "state": "failed", "error": str(exc)})
            continue
        removed_count += 1
        entries.append({"kind": kind, "state": "removed"})
    return {
        "removed_count": removed_count,
        "missing_count": missing_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "entries": entries,
    }


def _iter_agi_artifact_paths(run: JsonObject, *, root: str | Path | None) -> list[tuple[str, str, Path]]:
    genomi_root = genomi_data_root(root).resolve(strict=False)
    expected_project_dir = _expected_agi_project_dir(run, root=root)
    project_dir = _artifact_path(run.get("project_dir"))
    if project_dir is not None:
        state = _owned_artifact_state(project_dir, genomi_root, expected_project_dir)
        if state in {"present", "missing"}:
            return [("project_dir", state, project_dir)]

    artifacts: list[tuple[str, Path]] = []
    if project_dir is not None:
        artifacts.append(("project_dir", project_dir))
    for key in (
        "work_dir",
        "evidence_dir",
        "reference_dir",
        "agi_path",
        "matches",
        "candidate_inventory",
        "agi_comparable_variant_export",
        "evidence_db",
    ):
        path = _artifact_path(run.get(key))
        if path is not None:
            artifacts.append((key, path))
    outputs = run.get("outputs")
    if isinstance(outputs, dict):
        for key, value in outputs.items():
            path = _artifact_path(value)
            if path is not None:
                artifacts.append((f"outputs.{key}", path))

    seen: set[str] = set()
    result: list[tuple[str, str, Path]] = []
    for kind, path in artifacts:
        marker = str(path.resolve(strict=False))
        if marker in seen:
            continue
        seen.add(marker)
        result.append((kind, _owned_artifact_state(path, genomi_root, expected_project_dir), path))
    return result


def _artifact_path(value: object) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser()


def _owned_artifact_state(path: Path, genomi_root: Path, expected_project_dir: Path | None) -> str:
    resolved = path.resolve(strict=False)
    if resolved == genomi_root or not resolved.is_relative_to(genomi_root):
        return "outside_genomi_home"
    if expected_project_dir is None:
        return "outside_expected_agi_project"
    expected = expected_project_dir.resolve(strict=False)
    if resolved != expected and not resolved.is_relative_to(expected):
        return "outside_expected_agi_project"
    return "present" if resolved.exists() else "missing"


def _expected_agi_project_dir(run: JsonObject, *, root: str | Path | None) -> Path | None:
    slug = str(run.get("sample_slug") or run.get("agi_id") or "")
    if not slug:
        return None
    return genomi_data_root(root) / slug
