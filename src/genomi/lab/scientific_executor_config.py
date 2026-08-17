"""Resolve explicitly selected, installed GenomiLab scientific executors."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Mapping, Protocol

from .research_scientific_operations import (
    ESMScientificExecutor,
    ProtoScientificExecutor,
)


SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP = "genomi.scientific_executors"
ESM_SCIENTIFIC_EXECUTOR_ENV = "GENOMILAB_ESM_SCIENTIFIC_EXECUTOR"
PROTO_SCIENTIFIC_EXECUTOR_ENV = "GENOMILAB_PROTO_SCIENTIFIC_EXECUTOR"
_ENTRY_POINT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class _ScientificExecutorEntryPoint(Protocol):
    name: str

    def load(self) -> object: ...


class ScientificExecutorConfigurationError(RuntimeError):
    """A configured scientific executor cannot be selected safely."""

    def __init__(
        self,
        code: str,
        *,
        system: str,
        selector: str | None,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.system = system
        self.selector = selector


@dataclass(frozen=True, slots=True)
class ScientificExecutorConfiguration:
    esm_executor: ESMScientificExecutor | None
    proto_executor: ProtoScientificExecutor | None


def load_scientific_executor_configuration(
    environ: Mapping[str, str] | None = None,
) -> ScientificExecutorConfiguration:
    """Load configured executor callables from one fixed entry-point group.

    Environment values are non-secret selectors, never import paths. An unset
    selector leaves that scientific operation unavailable.
    """

    values = os.environ if environ is None else environ
    esm_selector = _selector(values, ESM_SCIENTIFIC_EXECUTOR_ENV, "ESM")
    proto_selector = _selector(values, PROTO_SCIENTIFIC_EXECUTOR_ENV, "Proto")
    if esm_selector is None and proto_selector is None:
        return ScientificExecutorConfiguration(None, None)

    try:
        entry_points = tuple(
            importlib_metadata.entry_points(
                group=SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP
            )
        )
    except Exception as exc:
        raise ScientificExecutorConfigurationError(
            "scientific_executor_catalog_unavailable",
            system="configured",
            selector=None,
            message=(
                "Configured GenomiLab scientific executors could not be "
                "resolved from installed Python entry points."
            ),
        ) from exc

    return ScientificExecutorConfiguration(
        esm_executor=_load_selected_executor(
            selector=esm_selector,
            system="ESM",
            entry_points=entry_points,
        ),
        proto_executor=_load_selected_executor(
            selector=proto_selector,
            system="Proto",
            entry_points=entry_points,
        ),
    )


def _selector(
    environ: Mapping[str, str], env_name: str, system: str
) -> str | None:
    raw = environ.get(env_name)
    if raw is None:
        return None
    if raw != raw.strip() or _ENTRY_POINT_NAME_RE.fullmatch(raw) is None:
        raise ScientificExecutorConfigurationError(
            "invalid_scientific_executor_selector",
            system=system.lower(),
            selector=raw,
            message=(
                f"{env_name} must name one installed entry point in "
                f"{SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP!r}."
            ),
        )
    return raw


def _load_selected_executor(
    *,
    selector: str | None,
    system: str,
    entry_points: tuple[_ScientificExecutorEntryPoint, ...],
) -> ESMScientificExecutor | ProtoScientificExecutor | None:
    if selector is None:
        return None
    matches = [
        entry_point
        for entry_point in entry_points
        if getattr(entry_point, "name", None) == selector
    ]
    if not matches:
        raise ScientificExecutorConfigurationError(
            "scientific_executor_not_installed",
            system=system.lower(),
            selector=selector,
            message=(
                f"Configured {system} scientific executor {selector!r} was not "
                f"found in installed entry-point group "
                f"{SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP!r}."
            ),
        )
    if len(matches) != 1:
        raise ScientificExecutorConfigurationError(
            "ambiguous_scientific_executor_entry_point",
            system=system.lower(),
            selector=selector,
            message=(
                f"Configured {system} scientific executor {selector!r} is "
                "ambiguous across installed distributions."
            ),
        )
    try:
        executor = matches[0].load()
    except Exception as exc:
        raise ScientificExecutorConfigurationError(
            "scientific_executor_load_failed",
            system=system.lower(),
            selector=selector,
            message=(
                f"Configured {system} scientific executor {selector!r} could "
                "not be loaded from its installed entry point."
            ),
        ) from exc
    if not callable(executor):
        raise ScientificExecutorConfigurationError(
            "scientific_executor_not_callable",
            system=system.lower(),
            selector=selector,
            message=(
                f"Configured {system} scientific executor {selector!r} did "
                "not load a callable."
            ),
        )
    return executor


__all__ = [
    "ESM_SCIENTIFIC_EXECUTOR_ENV",
    "PROTO_SCIENTIFIC_EXECUTOR_ENV",
    "SCIENTIFIC_EXECUTOR_ENTRY_POINT_GROUP",
    "ScientificExecutorConfiguration",
    "ScientificExecutorConfigurationError",
    "load_scientific_executor_configuration",
]
