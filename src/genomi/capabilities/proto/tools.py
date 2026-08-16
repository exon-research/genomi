from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ...evidence import envelope as evidence_envelope
from ...runtime.external_credentials import resolve_external_credentials


PUBLIC_INPUT_SCOPE = "public_or_approved_research_artifact"
DEFAULT_DEVICE = "modal"
DEFAULT_ENVIRONMENT = "proto-env"


def search_tools(
    *, query: str, limit: int = 10, category: str | None = None
) -> dict[str, Any]:
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("proto.search_tools requires query")
    if not 1 <= limit <= 25:
        raise ValueError("limit must be between 1 and 25")
    native = _native_tools()
    _credentials, client = _modal_client()
    if native is None:
        return _unavailable("proto.search_tools", "client_missing")
    if client is None:
        return _unavailable("proto.search_tools", "credential_missing")
    try:
        result = native.search_tools(
            query=clean_query,
            deployed_only=True,
            limit=limit,
            device=DEFAULT_DEVICE,
            environment=DEFAULT_ENVIRONMENT,
            client=client,
        )
    except Exception:
        return _unavailable("proto.search_tools", "request_failed")
    tools = result.get("tools", []) if isinstance(result, dict) else []
    if category:
        tools = [item for item in tools if isinstance(item, dict) and item.get("category") == category]
    return {
        "status": "completed" if tools else "in_scope_empty",
        "provider": "proto",
        "query": clean_query,
        "tools": _sanitize(tools),
        "match_count": len(tools),
    }


def describe_tool_schema(*, tool_key: str) -> dict[str, Any]:
    native = _native_tools()
    if native is None:
        return _unavailable("proto.describe_tool_schema", "client_missing")
    try:
        result = native.get_tool_schema(tool_key.strip())
    except Exception:
        return _unavailable("proto.describe_tool_schema", "client_failed")
    return {"status": "completed", "provider": "proto", "tool": _sanitize(result)}


def run_tool(
    *,
    tool_key: str,
    inputs: dict[str, Any],
    input_scope: str,
    external_transfer_approved: bool,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if input_scope != PUBLIC_INPUT_SCOPE or external_transfer_approved is not True:
        return _out_of_scope(
            tool_key=tool_key,
            input_scope=input_scope,
            external_transfer_approved=external_transfer_approved,
        )
    native = _native_tools()
    _credentials, client = _modal_client()
    query_scope = {"tool_key": tool_key, "input_scope": input_scope, "device": DEFAULT_DEVICE}
    if native is None:
        return _unavailable("proto.run_tool", "client_missing", query_scope)
    if client is None:
        return _unavailable("proto.run_tool", "credential_missing", query_scope)
    try:
        result = native.run_tool(
            tool_key=tool_key.strip(),
            inputs=inputs,
            config=config or {},
            device=DEFAULT_DEVICE,
            environment=DEFAULT_ENVIRONMENT,
            client=client,
        )
    except Exception:
        return _unavailable("proto.run_tool", "request_failed", query_scope)
    sanitized = _sanitize(result)
    ok = isinstance(result, dict) and result.get("ok") is not False
    if not ok:
        return {
            "status": "source_unavailable",
            "provider": "proto",
            "tool_key": tool_key,
            "result": sanitized,
            "evidence_envelope": evidence_envelope.not_assessed(
                operation="proto.run_tool",
                reason="tool_failed",
                query_scope=query_scope,
                guidance=["not_assessed:inspect_tool_result_and_revise_research_call"],
            ),
        }
    return {
        "status": "completed",
        "provider": "proto",
        "tool_key": tool_key,
        "result": sanitized,
        "interpretation_scope": "nonclinical_computational_research_artifact",
        "classification_effect": "none",
        "evidence_envelope": evidence_envelope.evidence_present(
            operation="proto.run_tool",
            query_scope=query_scope,
            coverage={"consulted_sources": [f"proto:{tool_key}"], "source_status": "consulted"},
            observations={"observation_count": 1},
            answer_readiness=evidence_envelope.SCOPED_ANSWER_ONLY,
            guidance=["evidence_present:use_only_as_nonclinical_computational_research_artifact"],
        ),
    }


def _native_tools() -> Any | None:
    try:
        return importlib.import_module("proto_tools.mcp.tools")
    except (ImportError, ModuleNotFoundError):
        return None


def _modal_client() -> tuple[Any, Any | None]:
    credentials = resolve_external_credentials("proto")
    if not credentials.configured:
        return credentials, None
    try:
        modal = importlib.import_module("modal")
        client = modal.Client.from_credentials(
            credentials.values["token_id"], credentials.values["token_secret"]
        )
    except Exception:
        return credentials, None
    return credentials, client


def _sanitize(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(
        token in lowered
        for token in ("token", "secret", "credential", "api_key", "authorization", "password", "private_key")
    ):
        return None
    if isinstance(value, Path):
        return {"artifact_state": "materialized_not_presented"}
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for item_key, item_value in value.items():
            if item_key in {"_saved_to", "saved_files", "output_dir"}:
                clean["artifact_state"] = "materialized_not_presented"
                continue
            sanitized = _sanitize(item_value, key=str(item_key))
            if sanitized not in (None, "", [], {}):
                clean[str(item_key)] = sanitized
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key=key) for item in value]
    if isinstance(value, str):
        if value.startswith("/") or value.startswith("file://"):
            return {"artifact_state": "materialized_not_presented"}
        if len(value) > 20_000:
            return {"content_state": "omitted_from_presented_result", "character_count": len(value)}
    return value


def _unavailable(
    operation: str, reason_code: str, query_scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "provider": "proto",
        "reason_code": reason_code,
        "evidence_envelope": evidence_envelope.not_assessed(
            operation=operation,
            reason=reason_code,
            query_scope=query_scope,
            coverage={"consulted_sources": [], "source_status": "unavailable"},
            guidance=["not_assessed:configure_provider_or_retry_external_source"],
        ),
    }


def _out_of_scope(
    *,
    tool_key: str,
    input_scope: str,
    external_transfer_approved: bool,
) -> dict[str, Any]:
    query_scope = {
        "tool_key": tool_key,
        "input_scope": input_scope,
        "external_transfer_approved": external_transfer_approved,
        "device": DEFAULT_DEVICE,
    }
    coverage = {
        "consulted_sources": [],
        "source_status": "not_consulted",
        "coverage_state": evidence_envelope.OUT_OF_SCOPE_FOR_INPUT,
    }
    return {
        "status": evidence_envelope.OUT_OF_SCOPE_FOR_INPUT,
        "coverage_state": evidence_envelope.OUT_OF_SCOPE_FOR_INPUT,
        "provider": "proto",
        "reason_code": "input_scope_not_approved",
        "evidence_envelope": evidence_envelope.out_of_scope_for_input(
            operation="proto.run_tool",
            query_scope=query_scope,
            coverage=coverage,
            next_actions=[{"action": "use_approved_public_research_inputs"}],
        ),
    }
