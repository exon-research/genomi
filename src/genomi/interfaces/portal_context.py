from __future__ import annotations

from typing import Any

from .. import __version__
from ..operations import call_operation
from ..runtime import portal_routes
from . import portal_genomes, portal_privacy

JsonObject = dict[str, Any]


def context_payload(project_id: str | None = None) -> JsonObject:
    context = _describe_context()
    return _context_payload(context, project_id=project_id)


def _context_payload(context: JsonObject, *, project_id: str | None = None) -> JsonObject:
    public_context = _public_context(context)
    if project_id:
        public_context = _project_scoped_context(public_context, project_id)
    return {
        "genomiVersion": __version__,
        "context": public_context,
        "mcp": {
            "endpoint": portal_routes.MCP_ENDPOINT,
            "transport": "streamable-http",
        },
    }


def prompt_context_payload(project_id: str | None = None) -> JsonObject:
    context = _describe_context()
    payload = _context_payload(context, project_id=project_id)
    public_context = payload["context"] if isinstance(payload.get("context"), dict) else {}
    policy = public_context.get("context_policy") if isinstance(public_context.get("context_policy"), dict) else {}
    access = public_context.get("active_genome_index_access") if isinstance(public_context.get("active_genome_index_access"), dict) else {}
    active = public_context.get("active_genome_index") if isinstance(public_context.get("active_genome_index"), dict) else {}
    readiness = active.get("active_genome_index_readiness") if isinstance(active.get("active_genome_index_readiness"), dict) else {}
    return {
        "genomiVersion": payload.get("genomiVersion"),
        "contextPolicy": {
            "mode": policy.get("mode") or policy.get("default") or "explicit",
            "implicitArtifactSelection": bool(policy.get("implicit_artifact_selection")),
        },
        "activeGenomeIndex": {
            "available": bool(public_context.get("has_active_genome_index")),
            "accessApproved": bool(access.get("approved")),
            "scope": access.get("scope"),
            "status": active.get("status"),
            "genomeBuild": active.get("genome_build"),
            "readiness": {
                "status": readiness.get("status"),
                "complete": bool(readiness.get("complete")),
                "variantsReady": bool(readiness.get("variants_ready")),
            },
        },
    }


def prompt_context_section(project_id: str | None = None) -> str:
    payload = prompt_context_payload(project_id)
    genome = payload.get("activeGenomeIndex") if isinstance(payload.get("activeGenomeIndex"), dict) else {}
    readiness = genome.get("readiness") if isinstance(genome.get("readiness"), dict) else {}
    policy = payload.get("contextPolicy") if isinstance(payload.get("contextPolicy"), dict) else {}
    lines = [
        "# Current Genomi context",
        f"- Genomi version: {_public_text(payload.get('genomiVersion') or '')}",
        "- Genome context: " + ("available" if genome.get("available") else "not available"),
        "- Genome access approved: " + ("yes" if genome.get("accessApproved") else "no"),
    ]
    if genome.get("scope"):
        lines.append(f"- Genome access scope: {_public_text(genome.get('scope'))}")
    if genome.get("status"):
        lines.append(f"- Genome status: {_public_text(genome.get('status'))}")
    if genome.get("genomeBuild"):
        lines.append(f"- Genome build: {_public_text(genome.get('genomeBuild'))}")
    if readiness:
        state = readiness.get("status") or ("complete" if readiness.get("complete") else "unknown")
        variants = "yes" if readiness.get("variantsReady") else "no"
        lines.append(f"- Genome readiness: {_public_text(state)}; variants ready: {variants}")
    if policy:
        mode = _public_text(policy.get("mode") or "explicit")
        implicit = "yes" if policy.get("implicitArtifactSelection") else "no"
        lines.append(f"- Privacy mode: {mode}; implicit artifact selection: {implicit}")
    return "\n".join(line for line in lines if line.strip()) + "\n\n"


def _describe_context() -> JsonObject:
    try:
        return call_operation("genomi.describe_context", {})
    except Exception as exc:
        return {"status": "unavailable", "error": _public_text(str(exc))}


def _public_context(context: JsonObject) -> JsonObject:
    policy = context.get("context_policy") if isinstance(context.get("context_policy"), dict) else {}
    access = context.get("active_genome_index_access") if isinstance(context.get("active_genome_index_access"), dict) else {}
    active = context.get("active_genome_index") if isinstance(context.get("active_genome_index"), dict) else {}
    active_user = context.get("active_user") if isinstance(context.get("active_user"), dict) else {}
    readiness = active.get("active_genome_index_readiness") if isinstance(active.get("active_genome_index_readiness"), dict) else {}
    registry = context.get("active_genome_index_registry") if isinstance(context.get("active_genome_index_registry"), dict) else {}
    axes = context.get("context_axes") if isinstance(context.get("context_axes"), dict) else {}
    active_axis = axes.get("active_genome_index") if isinstance(axes.get("active_genome_index"), dict) else {}
    response_profile = context.get("active_response_profile") if isinstance(context.get("active_response_profile"), dict) else {}
    return {
        "status": context.get("status") or "available",
        "error": _public_text(context.get("error")) if context.get("error") else None,
        "has_active_genome_index": bool(context.get("has_active_genome_index")),
        "context_policy": {
            "mode": policy.get("mode") or policy.get("default") or "explicit",
            "implicit_artifact_selection": bool(policy.get("implicit_artifact_selection")),
        },
        "active_genome_index_access": {
            "approved": bool(access.get("approved")),
            "scope": access.get("scope"),
        },
        "active_genome_index": {
            "agi_id": active.get("agi_id"),
            "display_name": active.get("nickname") or active_user.get("nickname") or active.get("sample_slug"),
            "sample_slug": active.get("sample_slug"),
            "status": active.get("status"),
            "genome_build": active.get("genome_build"),
            "source_type": active.get("source_type") or active.get("agi_source_format") or active.get("agi_source_kind"),
            "source_format": active.get("agi_source_format"),
            "source_provider": active.get("agi_source_provider"),
            "active_genome_index_readiness": {
                "status": readiness.get("status"),
                "complete": bool(readiness.get("complete")),
                "variants_ready": bool(readiness.get("variants_ready")),
            },
        },
        "active_genome_index_registry": {
            "known_agi_count": registry.get("known_agi_count") or 0,
            "known_user_count": registry.get("known_user_count") or 0,
            "resume_requires": registry.get("resume_requires"),
        },
        "selection_source": context.get("selection_source"),
        "default_auto_selected": bool(context.get("default_auto_selected")),
        "context_axes": {
            "active_genome_index": {
                "current_state": active_axis.get("current_state"),
                "known_agis": active_axis.get("known_agis") or 0,
            }
        },
        "active_response_profile": {
            "id": response_profile.get("id"),
            "label": response_profile.get("label"),
        },
    }


def _project_scoped_context(context: JsonObject, project_id: str) -> JsonObject:
    inventory = portal_genomes.genome_inventory_payload(project_id)
    active = inventory.get("active") if isinstance(inventory.get("active"), dict) else {}
    active_agi_id = str(active.get("agi_id") or "").strip()
    genomes = inventory.get("genomes") if isinstance(inventory.get("genomes"), list) else []
    genome = next(
        (
            item
            for item in genomes
            if isinstance(item, dict) and str(item.get("agi_id") or "").strip() == active_agi_id
        ),
        {},
    )
    source = genome.get("source") if isinstance(genome.get("source"), dict) else {}
    readiness = genome.get("readiness") if isinstance(genome.get("readiness"), dict) else {}
    scoped = dict(context)
    scoped["has_active_genome_index"] = bool(active_agi_id and genome)
    scoped["active_genome_index_access"] = {
        "approved": bool(active_agi_id and genome),
        "scope": "portal_project" if active_agi_id and genome else None,
    }
    scoped["active_genome_index"] = {
        "agi_id": active_agi_id or None,
        "display_name": genome.get("display_name"),
        "sample_slug": genome.get("sample_slug"),
        "status": genome.get("status"),
        "genome_build": genome.get("genome_build"),
        "source_type": source.get("format") or source.get("kind") or source.get("provider"),
        "source_format": source.get("format"),
        "source_provider": source.get("provider"),
        "active_genome_index_readiness": {
            "status": readiness.get("status"),
            "complete": bool(readiness.get("complete")),
            "variants_ready": bool(readiness.get("variants_ready")),
        },
    }
    scoped["selection_source"] = "portal_project" if active_agi_id and genome else "public_only"
    scoped["default_auto_selected"] = False
    axes = dict(scoped.get("context_axes") or {})
    axis = dict(axes.get("active_genome_index") or {})
    axis["current_state"] = "approved" if active_agi_id and genome else "none"
    axes["active_genome_index"] = axis
    scoped["context_axes"] = axes
    return scoped


def _public_text(value: object) -> str:
    return portal_privacy.prompt_safe_text(value)
