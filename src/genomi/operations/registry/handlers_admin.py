from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ...active_genome_index import source_intake
from ...runtime import context as runtime_context
from ...runtime import host_response, resources
from ...runtime.library_status import (
    library_inventory,
    library_status,
)
from ...runtime.paths import genomi_data_root
from ...retrieval import hybrid as retrieval_hybrid
from ...retrieval import index as retrieval_index
from ...retrieval import semantic as retrieval_semantic
from ...capabilities.prs import pgs_catalog as prs_pgs_catalog
from .catalog_meta import (
    BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST,
    PROJECT_ROOT,
    TOOL_CATALOG_OPERATIONS,
)
from .coerce import (
    _bool,
    _int,
    _list_str,
    _optional_int,
    _optional_path,
    _optional_str,
    _remember_source_result,
    _str,
    defaults_applied_for_call,
)
from .errors import JsonObject, OperationError

RUNTIME_UPDATE_ENV = "GENOMI_RUNTIME_UPDATE"


def _genomi_describe_context(_: JsonObject) -> JsonObject:
    return runtime_context.describe_context()


def _genomi_approve_agi_access(params: JsonObject) -> JsonObject:
    if not _bool(params, "approved_by_user"):
        raise OperationError(
            "approval_required",
            "Set approved_by_user=true only after the user explicitly approves Active Genome Index access for this chat.",
        )
    try:
        return runtime_context.approve_agi_access(
            agi_id=params.get("agi_id"),
            source=params.get("source"),
            user_id=params.get("user_id"),
            nickname=params.get("nickname"),
            reason=params.get("reason"),
        )
    except KeyError as exc:
        raise OperationError("missing_context", f"Known genomi agi not found for access target: {exc}") from exc


def _genomi_revoke_agi_access(params: JsonObject) -> JsonObject:
    return runtime_context.revoke_agi_access(agi_id=params.get("agi_id"))


def _genomi_list_users(_: JsonObject) -> JsonObject:
    return {
        "status": "completed",
        "active_user_id": runtime_context.describe_context().get("active_user_id"),
        "users": runtime_context.list_users(),
    }


def _genomi_select_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or nickname.")
    try:
        user = runtime_context.select_user(target)
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    return {
        "status": "completed",
        "user": runtime_context.describe_user(user),
        "context": runtime_context.describe_context(),
    }


def _genomi_rename_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or current nickname.")
    try:
        user = runtime_context.rename_user(target, _str(params, "new_nickname"))
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc
    return {"status": "completed", "user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_assign_user_genome(params: JsonObject) -> JsonObject:
    try:
        user = runtime_context.assign_user_genome(
            user_id=params.get("user_id"),
            nickname=params.get("nickname"),
            agi_id=params.get("agi_id"),
            source=params.get("source"),
            db=_optional_path(params, "db"),
            active_genome_index_path=_optional_path(params, "active_genome_index_path"),
            matches=_optional_path(params, "matches"),
            shared_db=_optional_path(params, "shared_db"),
            reference_fasta=_optional_path(params, "reference_fasta"),
            genotype_reference_fasta=_optional_path(params, "genotype_reference_fasta"),
            genome_build=params.get("genome_build"),
            set_active=_bool(params, "set_active", True),
            set_default_user=_bool(params, "set_default_user"),
        )
    except KeyError as exc:
        raise OperationError("missing_context", f"Known genomi agi not found: {exc}") from exc
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc
    return {"status": "completed", "user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_set_default_user(params: JsonObject) -> JsonObject:
    target = _str(params, "user_id", "") or _str(params, "nickname", "")
    if not target:
        raise OperationError("invalid_params", "Provide user_id or nickname.")
    try:
        user = runtime_context.set_default_user(target)
    except KeyError as exc:
        raise OperationError("missing_context", f"Known user not found: {target}") from exc
    return {"status": "completed", "default_user": runtime_context.describe_user(user), "context": runtime_context.describe_context()}


def _genomi_clear_default_user(_: JsonObject) -> JsonObject:
    return runtime_context.clear_default_user()


def _genomi_set_response_profile(params: JsonObject) -> JsonObject:
    profile_id = _str(params, "profile", "") or _str(params, "profile_id", "")
    if not profile_id:
        raise OperationError("invalid_params", "profile is required")
    try:
        registry = runtime_context.set_response_profile_id(profile_id)
    except ValueError as exc:
        raise OperationError("invalid_response_profile", str(exc)) from exc
    return {
        "status": "completed",
        "active_response_profile": host_response.resolve_active_response_profile(
            runtime_context.get_response_profile_id(registry)
        ),
        "context": runtime_context.describe_context(),
    }


def _genomi_install(params: JsonObject) -> JsonObject:
    libraries = _str(params, "libraries", "setup-only").strip()
    if not libraries:
        raise OperationError("invalid_params", "libraries is required. Use setup-only, common-questions, medication-response, or another installer library selection.")

    runtime_update = _runtime_update_step()

    response_profile = _optional_str(params, "response_profile") or _optional_str(params, "profile")
    active_profile: JsonObject | None = None
    if response_profile:
        try:
            registry = runtime_context.set_response_profile_id(response_profile)
        except ValueError as exc:
            raise OperationError("invalid_response_profile", str(exc)) from exc
        active_profile = host_response.resolve_active_response_profile(runtime_context.get_response_profile_id(registry))

    install_result: JsonObject = {"status": "skipped", "reason": "setup-only selected"}
    if libraries.lower() != "setup-only":
        script = _install_for_agents_script()
        genomi_home = genomi_data_root()
        command = [
            sys.executable,
            str(script),
            "--skip-package",
            "--skip-host-skill",
            "--skip-verify",
            "--genomi-home",
            str(genomi_home),
            "--libraries",
            libraries,
        ]
        if _bool(params, "force"):
            command.append("--force")
        for param_name, flag in (
            ("msigdb_gmt", "--msigdb-gmt"),
            ("msigdb_gmt_url", "--msigdb-gmt-url"),
            ("pharmcat_version", "--pharmcat-version"),
            ("ancestry_panel_url", "--ancestry-panel-url"),
            ("ancestry_panel_dir", "--ancestry-panel-dir"),
        ):
            value = _optional_str(params, param_name)
            if value:
                command.extend([flag, value])

        env = os.environ.copy()
        env["GENOMI_HOME"] = str(genomi_home)
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        install_result = {
            "status": "completed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "command": _redacted_install_command(command),
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        }
        if completed.returncode != 0:
            raise OperationError("install_failed", f"Genomi install failed with exit code {completed.returncode}: {_tail(completed.stderr or completed.stdout)}")

    # Newly-installed libraries can change what is searchable in the public
    # retrieval indexes; rebuild them so list_resources / search_indexes return
    # a coherent view immediately after install. setup-only installs don't
    # touch library data, and `skip_reindex=true` is an escape hatch for
    # callers chaining their own refresh.
    reindex_result: JsonObject | None = None
    if (
        libraries.lower() != "setup-only"
        and install_result.get("status") == "completed"
        and not _bool(params, "skip_reindex")
    ):
        refreshed, errors = _refresh_public_retrieval_indexes()
        reindex_result = {
            "schema": "genomi-retrieval-index-refresh",
            "status": "completed" if refreshed and not errors else ("partial" if refreshed else "not_refreshed"),
            "refreshed_indexes": refreshed,
            "errors": errors,
        }

    return {
        "status": "completed",
        "schema": "genomi-install-result-v1",
        "genomi_home": str(genomi_data_root()),
        "libraries_requested": libraries,
        "install_scope": _genomi_install_scope(),
        "runtime_update": runtime_update,
        "install": install_result,
        "reindex": reindex_result,
        "active_response_profile": active_profile,
        "library_inventory": library_inventory(),
    }


def _refresh_public_retrieval_indexes() -> tuple[list[JsonObject], list[JsonObject]]:
    """Rebuild every public metadata retrieval index. Returns (refreshed, errors).

    Active Genome Index private metadata is excluded — that index is per-session
    and gets refreshed on demand inside the search path with explicit approval.
    """
    refreshed: list[JsonObject] = []
    errors: list[JsonObject] = []
    try:
        refreshed.append(prs_pgs_catalog.refresh_score_search_index())
    except prs_pgs_catalog.SourceUnavailable as exc:
        errors.append({
            "source": "pgs_scores",
            "status": "source_unavailable",
            "source_status": {"source": exc.source, "error": exc.message},
        })
    return refreshed, errors


def _genomi_install_scope() -> JsonObject:
    return {
        "updates": [
            "genomi_home_setup",
            "public_reference_libraries",
            "response_profile",
        ],
        "does_not_update": [
            "runtime_code_without_a_configured_runtime_update_provider",
        ],
        "force_behavior": "force=true reinstalls selected public reference libraries; runtime code updates are controlled by the configured runtime update provider.",
    }


def _runtime_update_step() -> JsonObject:
    configured = (os.environ.get(RUNTIME_UPDATE_ENV) or "").strip()
    external_prefix = "external:"

    if not configured:
        return {
            "status": "unconfigured",
            "provider": "none",
            "env": RUNTIME_UPDATE_ENV,
            "message": "No runtime update provider is configured; genomi install updated setup, response profile, and public reference libraries only.",
            "restart_required": False,
        }

    if configured.lower() == "external" or configured.lower().startswith(external_prefix):
        message = configured[len(external_prefix) :].strip() if configured.lower().startswith(external_prefix) else ""
        return {
            "status": "external",
            "provider": "external",
            "env": RUNTIME_UPDATE_ENV,
            "message": message or "Runtime code is managed by the host package/update mechanism.",
            "restart_required": True,
        }

    command = configured
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
    except OSError as exc:
        raise OperationError("runtime_update_failed", f"Genomi runtime update command could not start: {exc}") from exc

    result = {
        "status": "completed" if completed.returncode == 0 else "failed",
        "provider": "command",
        "env": RUNTIME_UPDATE_ENV,
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "restart_required": True,
        "restart_hint": "Restart the host agent and reload the Genomi MCP server if runtime code changed.",
    }
    if completed.returncode != 0:
        raise OperationError(
            "runtime_update_failed",
            f"Genomi runtime update command failed with exit code {completed.returncode}: {_tail(completed.stderr or completed.stdout)}",
        )
    return result


def _install_for_agents_script() -> Path:
    candidates = [
        PROJECT_ROOT / "scripts" / "install_for_agents.py",
        Path("/opt/genomi/scripts/install_for_agents.py"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise OperationError(
        "installer_unavailable",
        "The Genomi installer script is unavailable. Packaged runtimes must include /opt/genomi/scripts/install_for_agents.py.",
    )


def _redacted_install_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for token in command:
        if redact_next:
            redacted.append("[path]")
            redact_next = False
            continue
        redacted.append(token)
        if token in {"--msigdb-gmt", "--ancestry-panel-dir"}:
            redact_next = True
    return redacted


def _tail(text: str, *, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:]


def _genomi_clear_selection(params: JsonObject) -> JsonObject:
    return runtime_context.clear_active_genome_index(forget_active_genome_indexes=_bool(params, "forget_active_genome_indexes"))


def _genomi_invoke(params: JsonObject) -> JsonObject:
    """Dispatch a Genomi capability operation by qualified name.

    The agent reads the relevant capability's SKILL.md (via Anthropic Claude
    Code Skills' filesystem-based progressive disclosure) to learn parameter
    shapes and result semantics, then calls this dispatcher with the qualified
    tool name and params.
    """
    from .model import _operation_capability
    from .table import _OPERATION_BY_NAME, call_operation

    tool_name = params.get("tool")
    inner_params = params.get("params")
    if not isinstance(tool_name, str) or "." not in tool_name:
        raise OperationError(
            "invalid_params",
            "genomi.invoke requires a `tool` string in '<namespace>.<op>' form",
        )
    if inner_params is None:
        inner_params = {}
    if not isinstance(inner_params, dict):
        raise OperationError(
            "invalid_params",
            "genomi.invoke `params` must be an object",
        )

    target = _OPERATION_BY_NAME.get(tool_name)
    if target is None:
        raise OperationError(
            "unknown_tool",
            f"unknown operation: {tool_name!r}. Anthropic Skills should have loaded the relevant capability skill markdown (at ~/.claude/skills/genomi-<capability>/SKILL.md) before this invoke call; read it for valid tool names.",
        )

    target_capability = (
        TOOL_CATALOG_OPERATIONS.get(tool_name, {}).get("capability")
        or _operation_capability(target)
    )
    if target_capability in BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST:
        raise OperationError(
            "tool_not_dispatchable",
            f"{tool_name!r} is a base tool (capability={target_capability!r}); call it directly via MCP rather than through genomi.invoke",
        )

    result = call_operation(tool_name, inner_params)
    if isinstance(result, dict):
        result = {"dispatched_tool": tool_name, **result}
    return result


def _resources_list(_: JsonObject) -> JsonObject:
    return resources.list_resources()


def _resources_libraries(params: JsonObject) -> JsonObject:
    names = _list_str(params, "libraries")
    if names:
        return {
            "schema": "genomi-library-inventory-v1",
            "libraries": [library_status(name) for name in names],
        }
    return library_inventory()


def _genomi_search_indexes(params: JsonObject) -> JsonObject:
    semantic = retrieval_semantic.parse_semantic_context(params.get("semantic_context"))
    query = _optional_str(params, "query")
    if not query and not semantic.has_hints:
        raise OperationError(
            "invalid_params",
            "search_indexes requires a query string or semantic_context. Use genomi.list_resources to enumerate installed reference libraries.",
        )
    include_private = _bool(params, "include_private_metadata", False)
    source_filter = _optional_str(params, "source")
    limit = _int(params, "limit", 20)
    public_indexes = retrieval_index.list_index_files()
    if source_filter:
        public_indexes = [item for item in public_indexes if str(item.get("source") or "") == source_filter]

    searched: list[JsonObject] = []
    for item in public_indexes:
        path = item.get("index_path")
        if not path:
            continue
        result = retrieval_index.search_index(
            str(path),
            queries=_metadata_retrieval_queries(query=query, semantic=semantic),
            limit=limit,
        )
        searched.append(
            {
                "source": item.get("source"),
                "scope": item.get("scope"),
                "index_path": path,
                "retrieval": result["diagnostics"],
                "hits": [
                    {
                        "doc_id": hit.doc_id,
                        "score": hit.score,
                        "streams": list(hit.streams),
                        "metadata": hit.payload,
                    }
                    for hit in result["hits"]
                ],
            }
        )

    private_search_status: JsonObject = {"status": "not_requested"}
    if include_private:
        active = runtime_context.active_run()
        if active is None:
            private_search_status = {"status": "no_active_genome_index"}
        elif not runtime_context.agi_access_approved(active):
            private_search_status = {
                "status": "active_genome_index_approval_required",
                "message": "Explicit session approval is required before searching Active Genome Index metadata.",
            }
        else:
            private_record = _refresh_active_metadata_index(active)
            result = retrieval_index.search_index(
                str(private_record["index_path"]),
                queries=_metadata_retrieval_queries(query=query, semantic=semantic),
                limit=limit,
            )
            searched.append(
                {
                    "source": private_record.get("source"),
                    "scope": private_record.get("scope"),
                    "index_path": private_record.get("index_path"),
                    "retrieval": result["diagnostics"],
                    "hits": [
                        {
                            "doc_id": hit.doc_id,
                            "score": hit.score,
                            "streams": list(hit.streams),
                            "metadata": hit.payload,
                        }
                        for hit in result["hits"]
                    ],
                }
            )
            private_search_status = {"status": "included"}

    return {
        "schema": "genomi-retrieval-index-search",
        "status": "completed",
        "query": {
            "source": source_filter,
            "query": query,
            "include_private_metadata": include_private,
            "limit": limit,
        },
        "private_metadata": private_search_status,
        "search_results": searched,
        "semantic_context": retrieval_semantic.term_usage_payload(
            semantic,
            streams=retrieval_semantic.retrieval_streams(
                raw_query=semantic.raw_query or query,
                host_terms=retrieval_semantic.search_terms(semantic),
                private_metadata=include_private,
            ),
        ),
    }


def _metadata_retrieval_queries(*, query: str | None, semantic: retrieval_semantic.SemanticContext) -> list[retrieval_hybrid.RetrievalQuery]:
    queries: list[retrieval_hybrid.RetrievalQuery] = []
    if query:
        queries.append(retrieval_hybrid.RetrievalQuery(text=query, stream="query", weight=1.0))
    if semantic.raw_query and semantic.raw_query != query:
        queries.append(retrieval_hybrid.RetrievalQuery(text=semantic.raw_query, stream="semantic:raw_query", weight=1.0))
    for index, text in enumerate(retrieval_semantic.search_terms(semantic), start=1):
        queries.append(retrieval_hybrid.RetrievalQuery(text=text, stream=f"semantic:host_term:{index}", weight=0.7))
    return queries


def _refresh_active_metadata_index(active: JsonObject) -> JsonObject:
    evidence_dir = active.get("evidence_dir")
    if not evidence_dir:
        raise OperationError("missing_context", "Active Genome Index metadata is missing evidence_dir.")
    source = "active_genome_index_metadata"
    fields = {
        "identity": " ".join(str(active.get(key) or "") for key in ("agi_id", "sample_slug", "source_format", "source_kind")),
        "metadata": " ".join(
            str(active.get(key) or "")
            for key in (
                "status",
                "genome_build",
                "project_dir",
                "work_dir",
                "evidence_dir",
                "reference_dir",
            )
        ),
        "outputs": " ".join(str(key) for key in (active.get("outputs") or {}).keys()),
    }
    doc = retrieval_hybrid.RetrievalDocument(
        doc_id=str(active.get("agi_id") or "active_genome_index"),
        fields=fields,
        payload={
            key: active.get(key)
            for key in (
                "agi_id",
                "sample_slug",
                "status",
                "source_format",
                "source_kind",
                "genome_build",
                "project_dir",
                "work_dir",
                "evidence_dir",
                "reference_dir",
                "outputs",
                "created_at",
                "updated_at",
            )
            if active.get(key) is not None
        },
        facets={"scope": ["private_metadata"], "source": [source]},
    )
    result = retrieval_index.refresh_index(
        retrieval_index.private_index_path(evidence_dir, source),
        source=source,
        documents=[doc],
        field_weights={"identity": 4.0, "metadata": 1.5, "outputs": 1.0},
        scope="private_active_genome_index_metadata",
        provenance={
            "source_id": source,
            "active_agi_id": active.get("agi_id"),
            "privacy_boundary": "metadata_only_no_genotype_truth_claims",
        },
    )
    return retrieval_index.describe_index(result["index_path"], default_scope="private_active_genome_index_metadata")


def _runtime_check_background_job(params: JsonObject) -> JsonObject:
    from ...interfaces.presentation import present_result
    from ...runtime import background_jobs

    job_id = _optional_str(params, "job_id")
    job_path = _optional_str(params, "job_path")
    if not job_id and not job_path:
        raise OperationError("invalid_params", "genomi.check_background_job requires job_id or job_path")
    try:
        job = background_jobs.read_job(job_id=job_id, job_path=job_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OperationError("background_job_not_found", str(exc)) from exc

    payload = background_jobs.public_job_status(job)
    if isinstance(job.get("params"), dict):
        try:
            defaults = defaults_applied_for_call(str(job.get("operation") or ""), dict(job.get("params") or {}))
        except OperationError:
            defaults = []
        if defaults and "defaults_applied" not in payload:
            payload["defaults_applied"] = defaults
    if job.get("status") == "completed":
        operation = str(job.get("operation") or "")
        result = job.get("result") or {}
        if not isinstance(result, dict):
            raise OperationError("invalid_background_result", "background operation result must be an object")
        payload["operation_result"] = present_result(operation, result)
    return payload


def _genomi_parse_source(params: JsonObject) -> JsonObject:
    source_value = params.get("source")
    if source_value is None or source_value == "":
        raise OperationError("invalid_params", "source is required")
    source = Path(str(source_value))
    result = source_intake.parse_source(
        source,
        evidence_db=_optional_path(params, "db"),
        source_evidence_db=_optional_path(params, "source_evidence_db"),
        shared_evidence_db=_optional_path(params, "shared_db"),
        reference_fasta=_optional_path(params, "reference_fasta"),
        auto_reference_fasta=_bool(params, "auto_reference_fasta", True),
        reference_root=_optional_path(params, "reference_root"),
        genome_build=_str(params, "genome_build", "auto"),
        force=_bool(params, "force"),
        max_records=params.get("max_records"),
        parallel_workers=_optional_int(params, "parallel_workers"),
    )
    return _remember_source_result(
        source,
        result,
        status="parsed",
        user_nickname=params.get("user_nickname"),
        set_default_user=_bool(params, "set_default_user"),
    )
