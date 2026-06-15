from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ...active_genome_index import source_intake
from ...runtime import context as runtime_context
from ...runtime import host_response, host_skills, resources
from ...runtime.libraries import manager as library_manager
from ...runtime.libraries.manager import inventory as library_inventory
from ...runtime.libraries.manager import status as library_status
from ...runtime.paths import expand_user_path, genomi_data_root
from ...retrieval import hybrid as retrieval_hybrid
from ...retrieval import index as retrieval_index
from ...retrieval import semantic as retrieval_semantic
from ...capabilities.prs import pgs_catalog as prs_pgs_catalog
from .catalog_meta import (
    BASE_CAPABILITIES_IN_DEFAULT_TOOLS_LIST,
    TOOL_CATALOG_OPERATIONS,
)
from .handlers_admin_next_actions import (
    assign_profile_next_action,
    read_agi_skill_next_action,
    reference_pass_next_action,
    with_next_action,
)
from .coerce import (
    _bool,
    _int,
    _list_str,
    _optional_int,
    _optional_path,
    _optional_str,
    _path,
    _remember_source_result,
    _str,
    defaults_applied_for_call,
)
from .errors import JsonObject, OperationError

# Gate for the runtime git pull. The pull is the default on `genomi install`;
# distributions that are not git-bound set this to suppress it.
SKIP_GIT_PULL_ENV = "GENOMI_SKIP_RUNTIME_GIT_PULL"


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
    # `genomi install` always updates everything that can be
    # updated: runtime code, host-agent skill links, reference libraries,
    # retrieval indexes, and a background reparse of every stale genome. There
    # are deliberately no per-step skip flags — exposing them only invited a
    # host agent to rationalize a do-nothing "setup-only" call as a valid
    # update. The single real gate is the env var GENOMI_SKIP_RUNTIME_GIT_PULL,
    # for distributions that update the runtime outside git.
    # `libraries` selects WHICH reference libraries to materialize. It defaults
    # to "everything" — a bare install installs them all — and otherwise
    # names a targeted subset (e.g. clinvar-grch38) for the on-demand
    # "install this missing library" prompts surfaced across the capabilities.
    # It is not a skip lever: install always runs, reindex always follows, and
    # the runtime/reparse steps are unconditional.
    libraries = _str(params, "libraries", "everything").strip()
    if not libraries:
        raise OperationError("invalid_params", "libraries is required. Use everything (the default) or a specific library selection such as common-questions or clinvar-grch38.")

    runtime_update = _runtime_update_step()

    # Reconcile host-agent skill symlinks against the (possibly just-pulled)
    # checkout, so links a prior bootstrap left stale or dangling are repaired
    # and links for newly-added capabilities are created on every update.
    host_skill_links = _reconcile_host_skill_links_step(force=_bool(params, "force"))

    response_profile = _optional_str(params, "response_profile") or _optional_str(params, "profile")
    active_profile: JsonObject | None = None
    if response_profile:
        try:
            registry = runtime_context.set_response_profile_id(response_profile)
        except ValueError as exc:
            raise OperationError("invalid_response_profile", str(exc)) from exc
        active_profile = host_response.resolve_active_response_profile(runtime_context.get_response_profile_id(registry))

    install_result = _install_libraries_step(libraries, params)

    # Newly-installed libraries can change what is searchable in the public
    # retrieval indexes; rebuild them so list_resources / search_indexes return
    # a coherent view immediately after install.
    reindex_result: JsonObject | None = None
    if install_result.get("status") in {"completed", "partial"}:
        refreshed, errors = _refresh_public_retrieval_indexes()
        reindex_result = {
            "status": "completed" if refreshed and not errors else ("partial" if refreshed else "not_refreshed"),
            "refreshed_indexes": refreshed,
            "errors": errors,
        }

    # After the runtime may have changed (git pull), reparse genomes whose stored
    # index schema is older than the on-disk schema. Each reparse runs as a
    # background job (fresh subprocess at the new schema), so install returns
    # immediately with job ids to poll rather than blocking on full rebuilds.
    reparse_result = _reparse_stale_genomes()
    registry_result = runtime_context.reconcile_current_agi_registry()

    return {
        "status": "partial" if install_result.get("status") == "partial" else "completed",
        "genomi_home": str(genomi_data_root()),
        "libraries_requested": libraries,
        "install_scope": _genomi_install_scope(),
        "runtime_update": runtime_update,
        "host_skill_links": host_skill_links,
        "install": install_result,
        "reindex": reindex_result,
        "reparse": reparse_result,
        "registry": registry_result,
        "active_response_profile": active_profile,
        "library_inventory": library_inventory(),
    }


def _install_libraries_step(libraries: str, params: JsonObject) -> JsonObject:
    """Materialize the selected reference libraries through the central manager,
    in-process. Each selected library is checked against its source and only the
    changed bytes are downloaded (missing libraries download in full; present
    ones are conditionally refreshed). Idempotent: present + unchanged is a
    no-op. ``force`` re-downloads. Invalid selections raise OperationError;
    per-library materialization failures are collected so one unavailable
    source does not prevent later selected libraries from being attempted.
    """
    try:
        selected = library_manager.resolve_selection(libraries)
    except ValueError as exc:
        raise OperationError("invalid_params", str(exc)) from exc

    force = _bool(params, "force")
    overrides: dict[str, str] = {}
    for param_name in ("msigdb_gmt", "msigdb_gmt_url", "pharmcat_version", "ancestry_panel_url", "ancestry_panel_dir"):
        value = _optional_str(params, param_name)
        if value:
            overrides[param_name] = value

    results: list[JsonObject] = []
    errors: list[JsonObject] = []
    for library_id in selected:
        try:
            results.append(library_manager.refresh(library_id, force=force, **overrides))
        except Exception as exc:  # noqa: BLE001 — surface any materialization failure as an operation error
            errors.append({
                "library": library_id,
                "status": "install_failed",
                "error": str(exc),
            })

    has_partial_result = any(_library_refresh_result_is_partial(result) for result in results)
    status = "partial" if errors or has_partial_result else "completed"
    payload: JsonObject = {
        "status": status,
        "libraries": selected,
        "results": results,
    }
    if errors:
        payload["errors"] = errors
    return payload


def _library_refresh_result_is_partial(result: JsonObject) -> bool:
    status = str(result.get("status") or "")
    return status == "manual_source_required" or bool(result.get("source_status"))


def _refresh_public_retrieval_indexes() -> tuple[list[JsonObject], list[JsonObject]]:
    """Rebuild every public metadata retrieval index. Returns (refreshed, errors).

    Active Genome Index private metadata is excluded — that index is per-session
    and gets refreshed on demand inside the search path with explicit approval.
    """
    refreshed: list[JsonObject] = []
    errors: list[JsonObject] = []
    try:
        refreshed.append(prs_pgs_catalog.refresh_score_search_index())
    except prs_pgs_catalog.ScoreMetadataUnavailable as exc:
        errors.append({
            "source": "pgs_scores",
            "status": str(exc.payload.get("status") or "requires_library_install"),
            "missing_library": exc.payload.get("missing_library"),
            "ask_user": exc.payload.get("ask_user"),
        })
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
            "runtime_code",
            "host_skill_links",
            "public_reference_libraries",
            "retrieval_indexes",
            "stale_genome_reparse",
            "response_profile",
        ],
        "does_not_update": [
            "runtime_code_when_GENOMI_SKIP_RUNTIME_GIT_PULL_is_set",
            "runtime_code_when_not_a_git_checkout",
            "host_skill_links_when_not_a_git_checkout",
        ],
        "force_behavior": "Library install is idempotent — already-present libraries are skipped; force=true re-downloads them and replaces non-symlink host-skill link conflicts. Runtime code updates via git pull unless GENOMI_SKIP_RUNTIME_GIT_PULL is set or the runtime is not a git checkout. A manifest-changing pull also reconciles dependencies.",
    }


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _git_pull_suppressed_by() -> str | None:
    """The env disabling the runtime git pull, or None to allow it."""
    if _env_truthy(SKIP_GIT_PULL_ENV):
        return SKIP_GIT_PULL_ENV
    return None


def _runtime_update_step() -> JsonObject:
    """Update the runtime code via git pull, unless gated off.

    The git pull is the runtime update mechanism: `genomi install` pulls the
    checkout the runtime lives in. GENOMI_SKIP_RUNTIME_GIT_PULL suppresses it
    for distributions that are not git-bound; the pull is also a no-op when the
    runtime is not a git checkout.
    """
    base: JsonObject = {"provider": "git", "gate_env": SKIP_GIT_PULL_ENV}
    suppressed_by = _git_pull_suppressed_by()
    if suppressed_by is not None:
        return {
            **base,
            "status": "skipped",
            "restart_required": False,
            "message": f"Runtime git pull disabled by {suppressed_by}; this runtime is updated outside genomi.",
        }
    return _git_pull_runtime_step()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _runtime_git_repo() -> Path | None:
    """The git work-tree root the runtime is installed from, or None.

    None means the runtime is not a git checkout (packaged install) or git is
    unavailable — either way there is nothing to `git pull`."""
    import genomi

    start = Path(genomi.__file__).resolve().parent
    try:
        completed = _git(start, "rev-parse", "--show-toplevel")
    except OSError:
        return None
    top = completed.stdout.strip()
    return Path(top) if completed.returncode == 0 and top else None


def _reconcile_host_skill_links_step(*, force: bool = False) -> JsonObject:
    """Repair/create host-agent skill symlinks against the runtime checkout.

    Skills live in the source tree (``<checkout>/SKILL.md`` and
    ``<checkout>/skills/<name>``), so linking only applies to a git-checkout
    install. A packaged install has no such tree and is reported as skipped.
    """
    repo = _runtime_git_repo()
    if repo is None:
        return {
            "status": "skipped",
            "reason": "runtime_not_a_git_checkout",
            "message": "Runtime is not a git checkout; host skills are linked only from a source checkout.",
        }
    return host_skills.reconcile_host_skill_links(repo, force=force)


def _git_pull_runtime_step() -> JsonObject:
    base = {"provider": "git", "gate_env": SKIP_GIT_PULL_ENV}
    repo = _runtime_git_repo()
    if repo is None:
        return {
            **base,
            "status": "unmanaged",
            "restart_required": False,
            "message": "Runtime is not a git checkout (package-managed install); update it with your package manager.",
        }
    if _git(repo, "status", "--porcelain").stdout.strip():
        return {
            **base,
            "status": "skipped",
            "restart_required": False,
            "repo": str(repo),
            "message": f"Runtime git checkout at {repo} has uncommitted changes; skipped git pull. Commit or stash, then re-run.",
        }
    before = _git(repo, "rev-parse", "HEAD").stdout.strip() or None
    completed = _git(repo, "pull", "--ff-only")
    after = _git(repo, "rev-parse", "HEAD").stdout.strip() or None
    if completed.returncode != 0:
        raise OperationError(
            "runtime_update_failed",
            f"git pull --ff-only failed in {repo}: {_tail(completed.stderr or completed.stdout)}",
        )
    changed = bool(before and after and before != after)
    result: JsonObject = {
        **base,
        "status": "completed",
        "repo": str(repo),
        "from": before,
        "to": after,
        "changed": changed,
        "restart_required": changed,
        "stdout_tail": _tail(completed.stdout),
    }
    if changed:
        # A git pull updates the source in place (an editable install reads it
        # directly), but it does NOT install new or bumped dependencies from a
        # changed manifest — pulled code can then import a package that isn't
        # present. Reconcile the environment, but only if a dependency manifest
        # actually changed in the pulled range.
        result["dependency_sync"] = _sync_runtime_dependencies(repo, before=before, after=after)
        result["restart_hint"] = "Restart the host agent and reload the Genomi MCP server to load the pulled code."
    return result


# Files that declare the runtime's dependencies. A pull that touches none of
# these can't have changed deps, so no reinstall is attempted.
_DEPENDENCY_MANIFESTS = (
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
)


def _dependency_manifests_changed(repo: Path, before: str | None, after: str | None) -> list[str] | None:
    """Manifest files that changed between two SHAs, or None if it can't be told.

    None means "couldn't determine" (missing SHAs or a failed/garbled diff) — the
    caller treats that as "attempt a sync to be safe" rather than silently skip.
    """
    if not (before and after):
        return None
    completed = _git(repo, "diff", "--name-only", f"{before}..{after}", "--", *_DEPENDENCY_MANIFESTS)
    if completed.returncode != 0:
        return None
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _sync_runtime_dependencies(repo: Path, *, before: str | None, after: str | None) -> JsonObject:
    """Reconcile the runtime's installed dependencies after a code-changing pull.

    Deliberately makes no assumption about how the host installed Python. It
    only runs when a dependency manifest changed, then tries the mechanisms that
    can target *this* interpreter (``sys.executable`` — the same one the
    ``genomi`` shim launches), in order, stopping at the first that works:

    1. ``python -m pip`` bound to the running interpreter (venv-with-pip,
       system, conda, …).
    2. ``uv pip --python <interpreter>`` when ``uv`` is on PATH (uv venvs ship
       no pip, so this is the common fallback there).

    If a manifest changed but none of those are usable (PEP 668 base interpreter
    with no pip and no uv, an exotic package manager, …) it reports
    ``action_required`` with the changed manifests and a tool-neutral hint —
    it never guesses a command for an environment it can't drive, and never
    aborts the wider install (the pulled code is already in place).
    """
    interpreter = sys.executable
    base: JsonObject = {"interpreter": interpreter}

    changed = _dependency_manifests_changed(repo, before, after)
    if changed == []:
        return {**base, "status": "skipped", "reason": "no dependency manifest changed in the pulled range"}
    base["changed_manifests"] = changed if changed is not None else "undetermined"

    candidates: list[tuple[str, list[str]]] = [
        ("pip", [interpreter, "-m", "pip", "install", "-e", str(repo)]),
    ]
    uv = shutil.which("uv")
    if uv:
        candidates.append(("uv", [uv, "pip", "install", "-e", str(repo), "--python", interpreter]))

    attempts: list[JsonObject] = []
    for tool, command in candidates:
        try:
            completed = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            attempts.append({"tool": tool, "status": "unavailable", "error": str(exc)})
            continue
        if completed.returncode == 0:
            return {**base, "status": "completed", "tool": tool, "stdout_tail": _tail(completed.stdout)}
        attempts.append({"tool": tool, "status": "failed", "returncode": completed.returncode, "stderr_tail": _tail(completed.stderr)})

    return {
        **base,
        "status": "action_required",
        "attempts": attempts,
        "hint": (
            "A dependency manifest changed but no installer could be driven for this "
            "interpreter. Reinstall the package into the environment that runs Genomi "
            f"using whatever manages it — e.g. `pip install -e .`, `uv pip install -e . "
            f"--python {interpreter}`, conda, or your distro's package manager."
        ),
    }


def _effective_runtime_schema() -> int:
    """The Active Genome Index SCHEMA_VERSION of the *on-disk* runtime code.

    Probed in a fresh subprocess so a git pull performed earlier in this same
    call is reflected, even though the running process still holds the old
    constant. The reparse jobs are themselves fresh subprocesses, so they build
    at this schema. Falls back to the in-process constant if the probe fails."""
    from ...active_genome_index._agi_schema import SCHEMA_VERSION

    try:
        completed = subprocess.run(
            [sys.executable, "-c", "import genomi.active_genome_index._agi_schema as s; print(s.SCHEMA_VERSION)"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
        )
        if completed.returncode == 0:
            return int(completed.stdout.strip())
    except (OSError, ValueError):
        pass
    return SCHEMA_VERSION


def _stored_agi_schema(agi_path: str) -> int | None:
    from ...active_genome_index.active_genome_index import stored_schema_version

    return stored_schema_version(agi_path)


def _reparse_stale_genomes() -> JsonObject:
    """Launch a background reparse for every registered genome whose stored
    index schema is older than the on-disk runtime schema.

    Reparse jobs run via the standard background machinery (a fresh job-worker
    subprocess that builds at the current on-disk schema). start_operation_job
    dedups on source, so re-running install attaches to an in-flight reparse
    rather than starting a second one. A genome whose source is gone cannot be
    rebuilt — it is reported, not launched."""
    from ...runtime import background_jobs

    effective_schema = _effective_runtime_schema()
    registry = runtime_context.load_registry()
    agis = registry.get("agis", {})
    checked = 0
    launched: list[JsonObject] = []
    skipped: list[JsonObject] = []
    for agi_id, record in agis.items():
        if not isinstance(record, dict):
            continue
        agi_path = record.get("agi_path")
        resolved_agi_path = expand_user_path(str(agi_path)) if agi_path else None
        if not resolved_agi_path or not resolved_agi_path.exists():
            continue
        checked += 1
        stored = _stored_agi_schema(str(resolved_agi_path))
        if stored is None or stored >= effective_schema:
            continue
        agi_intake_source_path = record.get("agi_intake_source_path")
        resolved_agi_intake_source_path = (
            expand_user_path(str(agi_intake_source_path))
            if agi_intake_source_path
            else None
        )
        agi_intake_source_available = bool(
            resolved_agi_intake_source_path and resolved_agi_intake_source_path.exists()
        )
        entry: JsonObject = {
            "agi_id": agi_id,
            "stored_agi_schema_version": stored,
            "agi_intake_source_available": agi_intake_source_available,
        }
        if not agi_intake_source_available:
            skipped.append({**entry, "reason": "agi_intake_source_unavailable"})
            continue
        try:
            job = background_jobs.start_operation_job(
                "genomi.parse_source", {"source": str(resolved_agi_intake_source_path), "force": True}
            )
            launched.append({**entry, "job_id": job.get("job_id")})
        except Exception as exc:  # pragma: no cover - best effort per genome
            skipped.append({**entry, "reason": f"launch_failed: {exc}"})
    return {
        "effective_agi_schema_version": effective_schema,
        "checked": checked,
        "stale": len(launched) + len(skipped),
        "launched": launched,
        "skipped": skipped,
    }


def _tail(text: str, *, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:]


def _genomi_invoke(params: JsonObject) -> JsonObject:
    """Dispatch a Genomi capability operation by qualified name.

    The agent reads the relevant capability's SKILL.md (via Anthropic Claude
    Code Skills' filesystem-based progressive disclosure) to learn parameter
    shapes and result contracts, then calls this dispatcher with the qualified
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
        active = runtime_context.active_agi_record()
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
        "identity": " ".join(str(active.get(key) or "") for key in ("agi_id", "sample_slug", "agi_source_format", "agi_source_kind")),
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
                "agi_source_format",
                "agi_source_kind",
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
    source = _path(params, "source")
    result = source_intake.parse_source(
        source,
        evidence_db=_optional_path(params, "db"),
        source_evidence_db=_optional_path(params, "source_evidence_db"),
        shared_evidence_db=_optional_path(params, "shared_db"),
        reference_fasta=_optional_path(params, "reference_fasta"),
        auto_reference_fasta=_bool(params, "auto_reference_fasta", True),
        genome_build=_str(params, "genome_build", "auto"),
        force=_bool(params, "force"),
        max_records=params.get("max_records"),
        parallel_workers=_optional_int(params, "parallel_workers"),
    )
    result_status = str(result.get("status") or "")
    parse_completed = result_status == "completed"
    parsed = _remember_source_result(
        source,
        result,
        status="parsed" if parse_completed else (result_status or "blocked"),
        user_nickname=params.get("user_nickname"),
        set_default_user=_bool(params, "set_default_user"),
    )
    build_status = ""
    steps = result.get("steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        step_result = steps[0].get("result")
        if isinstance(step_result, dict):
            build_status = str(step_result.get("status") or "")
    outputs_value = result.get("outputs")
    outputs: JsonObject = outputs_value if isinstance(outputs_value, dict) else {}
    reference_job_id = outputs.get("reference_pass_job_id")
    reference_pending = build_status == "variants_ready" or bool(reference_job_id)

    if parse_completed:
        parsed = with_next_action(
            parsed,
            read_agi_skill_next_action(
                "Every variant is now queryable in the Active Genome Index. Interpreting "
                "it and assigning it to a user profile use invoke-only active_genome_index.* tools."
            ),
        )
    # The user did not pre-supply a profile name, so prompt for one (and whether
    # to make it the default) exactly like INSTALL_FOR_AGENTS.md Step 8.
    if parse_completed and not params.get("user_nickname"):
        parsed = with_next_action(parsed, assign_profile_next_action())
    if reference_pending:
        parsed = with_next_action(parsed, reference_pass_next_action(reference_job_id, outputs.get("reference_pass_job_path")))
    return parsed
