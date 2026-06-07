from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import active_genome_index_readiness
from .normalize import JsonObject, _normalize_agi_record, _normalize_user_record
from .storage import load_registry


def describe_agi_record(run: JsonObject | None) -> JsonObject | None:
    if run is None:
        return None
    run = _normalize_agi_record(run)
    active_genome_index_state = _active_genome_index_state(run)
    digitized = _is_digitized_agi_record(run)
    path_keys = [
        "agi_intake_source_path",
        "evidence_db",
        "shared_evidence_db",
        "agi_path",
        "matches",
        "candidate_inventory",
        "agi_comparable_variant_export",
        "reference_fasta",
        "genotype_reference_fasta",
    ]
    availability = {
        key: Path(value).exists()
        for key in path_keys
        if (value := run.get(key))
    }
    payload = {**run, "availability": availability, "digitized": digitized}
    if active_genome_index_state is not None:
        payload["active_genome_index_readiness"] = active_genome_index_state
    agi_intake_source_path = payload.pop("agi_intake_source_path", None)
    payload["availability"] = {
        key: value
        for key, value in availability.items()
        if key != "agi_intake_source_path"
    }
    if agi_intake_source_path:
        payload["intake_source"] = {
            "role": "ingestion_source_for_digitization",
            "hidden_after_digitization": True,
            "available_for_rebuild": bool(
                agi_intake_source_path
                and Path(str(agi_intake_source_path)).exists()
            ),
        }
    return payload


def list_agis(root: str | Path | None = None) -> list[JsonObject]:
    registry = load_registry(root)
    records = [agi for agi in registry.get("agis", {}).values() if isinstance(agi, dict)]
    return [
        describe_agi_record(agi) or {}
        for agi in sorted(records, key=lambda item: str(item.get("updated_at", "")), reverse=True)
    ]


def describe_user(user: JsonObject | None, *, registry: JsonObject | None = None, include_genomes: bool = True) -> JsonObject | None:
    if not isinstance(user, dict):
        return None
    normalized = _normalize_user_record(user)
    payload: JsonObject = {
        "user_id": normalized.get("user_id"),
        "nickname": normalized.get("nickname"),
        "default": bool(normalized.get("default")),
        "active_agi_id": normalized.get("active_agi_id"),
        "agi_ids": list(normalized.get("agi_ids") or []),
        "created_at": normalized.get("created_at"),
        "updated_at": normalized.get("updated_at"),
    }
    if include_genomes:
        reg = registry if registry is not None else load_registry()
        payload["active_genome_index"] = describe_agi_record(reg.get("agis", {}).get(str(normalized.get("active_agi_id") or "")))
        payload["genomes"] = [
            describe_agi_record(reg.get("agis", {}).get(str(agi_id))) or {"agi_id": str(agi_id)}
            for agi_id in normalized.get("agi_ids", [])
        ]
    return payload


def _is_digitized_agi_record(run: JsonObject) -> bool:
    if str(run.get("status") or "") == "parsed":
        active_genome_index_state = _active_genome_index_state(run)
        return bool(active_genome_index_state.get("complete")) if active_genome_index_state is not None else True
    if str(run.get("agi_source_format") or "") in {"vcf", "gvcf"}:
        active_genome_index_state = _active_genome_index_state(run)
        return bool(active_genome_index_state and active_genome_index_state.get("complete"))
    for key in ("agi_path", "matches", "candidate_inventory"):
        value = run.get(key)
        if value and Path(str(value)).exists():
            return True
    return False


def _active_genome_index_state(run: JsonObject) -> JsonObject | None:
    agi_path = run.get("agi_path")
    if not agi_path:
        return None
    path = Path(str(agi_path))
    return active_genome_index_readiness(path)
