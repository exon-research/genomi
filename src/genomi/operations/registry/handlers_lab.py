"""Focused Lab operation adapters.

The registry owns public operation names and dispatch only. Durable state,
authorization, and receipt validation remain owned by ``genomi.lab``.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

from .errors import JsonObject, OperationError


def _dispatch_lab(handler_name: str, params: JsonObject) -> JsonObject:
    try:
        operations = importlib.import_module("genomi.lab.operations")
    except ModuleNotFoundError as exc:
        if exc.name != "genomi.lab.operations":
            raise
        raise OperationError(
            "lab_runtime_unavailable",
            "The Lab operation runtime is not available in this installation.",
        ) from exc
    handler = getattr(operations, handler_name, None)
    if not isinstance(handler, Callable):
        raise OperationError(
            "lab_operation_unavailable",
            f"The Lab runtime does not implement {handler_name!r}.",
        )
    result = handler(params)
    if not isinstance(result, dict):
        raise OperationError(
            "invalid_lab_operation_result",
            f"The Lab runtime returned a non-object result for {handler_name!r}.",
        )
    return result


def _lab_create_investigation(params: JsonObject) -> JsonObject:
    return _dispatch_lab("create_investigation", params)


def _lab_update_health_profile(params: JsonObject) -> JsonObject:
    return _dispatch_lab("update_health_profile", params)


def _lab_read_investigation(params: JsonObject) -> JsonObject:
    return _dispatch_lab("read_investigation", params)


def _lab_create_cycle(params: JsonObject) -> JsonObject:
    return _dispatch_lab("create_cycle", params)


def _lab_create_hypothesis(params: JsonObject) -> JsonObject:
    return _dispatch_lab("create_hypothesis", params)


def _lab_revise_hypothesis(params: JsonObject) -> JsonObject:
    return _dispatch_lab("revise_hypothesis", params)


def _lab_prepare_specialist_brief(params: JsonObject) -> JsonObject:
    return _dispatch_lab("prepare_specialist_brief", params)


def _lab_create_specialist_assignment(params: JsonObject) -> JsonObject:
    return _dispatch_lab("create_specialist_assignment", params)


def _lab_transition_specialist_assignment(params: JsonObject) -> JsonObject:
    return _dispatch_lab("transition_specialist_assignment", params)


def _lab_capture_evidence_result(params: JsonObject) -> JsonObject:
    return _dispatch_lab("capture_evidence_result", params)


def _lab_capture_provider_result(params: JsonObject) -> JsonObject:
    return _dispatch_lab("capture_provider_result", params)


def _lab_publish_brief(params: JsonObject) -> JsonObject:
    return _dispatch_lab("publish_brief", params)


__all__ = [
    "_lab_capture_evidence_result",
    "_lab_capture_provider_result",
    "_lab_create_cycle",
    "_lab_create_hypothesis",
    "_lab_create_investigation",
    "_lab_create_specialist_assignment",
    "_lab_prepare_specialist_brief",
    "_lab_publish_brief",
    "_lab_read_investigation",
    "_lab_revise_hypothesis",
    "_lab_transition_specialist_assignment",
    "_lab_update_health_profile",
]
