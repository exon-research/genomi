from __future__ import annotations

from pathlib import Path
from typing import Any

from ....runtime import context as runtime_context
from ....runtime.paths import shared_evidence_db_path

JsonObject = dict[str, Any]


def _selected_runs(
    *,
    agi_id: str | None,
    include_active_genome_index: bool,
    include_known_active_genome_indexes: bool,
    warnings: list[str],
) -> list[tuple[JsonObject, str]]:
    selected: list[tuple[JsonObject, str]] = []
    seen: set[str] = set()

    registry = runtime_context.load_registry()
    active = runtime_context.active_accessible_run()
    if agi_id:
        run = runtime_context.find_agi(str(agi_id))
        if not isinstance(run, dict) and active and str(active.get("agi_id")) == str(agi_id):
            run = active
        if isinstance(run, dict) and runtime_context.agi_access_approved(run):
            _append_run(selected, seen, run, "explicit_active_genome_index")
        elif isinstance(run, dict):
            warnings.append(f"Known genomi agi is not approved for this session: {agi_id}")
        else:
            warnings.append(f"Known genomi agi not found: {agi_id}")

    if include_active_genome_index and isinstance(active, dict) and runtime_context.agi_access_approved(active):
        _append_run(selected, seen, active, "active_genome_index")

    if include_known_active_genome_indexes:
        for run in registry.get("agis", {}).values():
            if isinstance(run, dict) and runtime_context.agi_access_approved(run):
                _append_run(selected, seen, run, "known_active_genome_index")

    return selected


def _append_run(selected: list[tuple[JsonObject, str]], seen: set[str], run: JsonObject, selection: str) -> None:
    run_key = str(run.get("agi_id") or run.get("sample_slug") or id(run))
    if run_key in seen:
        return
    seen.add(run_key)
    selected.append((run, selection))


def _selected_evidence_dbs(
    *,
    db: str | Path | None,
    shared_db: str | Path | None,
    runs: list[JsonObject],
) -> list[JsonObject]:
    selected: list[JsonObject] = []
    seen: set[str] = set()

    if db:
        _append_db(selected, seen, Path(db), "explicit_db", shared=False)
    for run in runs:
        agi_id = str(run.get("agi_id") or run.get("sample_slug") or "agi")
        if run.get("evidence_db"):
            _append_db(selected, seen, Path(str(run["evidence_db"])), f"agi:{agi_id}", shared=False)
        if run.get("shared_evidence_db"):
            _append_db(selected, seen, Path(str(run["shared_evidence_db"])), "shared_db", shared=True)
    if shared_db:
        _append_db(selected, seen, Path(shared_db), "shared_db", shared=True)
    _append_db(selected, seen, shared_evidence_db_path(), "shared_db", shared=True)
    return selected


def _append_db(selected: list[JsonObject], seen: set[str], path: Path, label: str, *, shared: bool) -> None:
    resolved = str(path.expanduser().resolve(strict=False))
    if resolved in seen or not Path(resolved).exists():
        return
    seen.add(resolved)
    selected.append({"path": resolved, "label": label, "shared": shared})


def _run_summary(run: JsonObject, selection: str) -> JsonObject:
    described = runtime_context.describe_run(run) or {}
    availability = described.get("availability") if isinstance(described.get("availability"), dict) else {}
    return {
        "agi_id": run.get("agi_id"),
        "sample_slug": run.get("sample_slug"),
        "status": run.get("status"),
        "selection": selection,
        "digitized": bool(described.get("digitized")),
        "source_format": run.get("source_format"),
        "source_kind": run.get("source_kind"),
        "genome_build": run.get("genome_build"),
        "availability": {key: bool(value) for key, value in availability.items() if key not in {"source", "vcf"}},
    }


def _public_db_descriptor(database: JsonObject) -> JsonObject:
    path = Path(database["path"])
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = None
    return {
        "label": database["label"],
        "shared": bool(database.get("shared")),
        "available": path.exists(),
        "size_bytes": size_bytes,
    }
