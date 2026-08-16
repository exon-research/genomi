"""Resolve external-provider credentials without presenting secret values."""

from __future__ import annotations

import contextlib
import contextvars
import os
from dataclasses import dataclass
from typing import Iterator, Mapping


_SESSION_CREDENTIALS: contextvars.ContextVar[Mapping[str, str]] = contextvars.ContextVar(
    "genomi_external_credentials", default={}
)

_ENV_KEYS = {
    "paperclip": (("api_key", "PAPERCLIP_API_KEY"),),
    "biohub": (("api_key", "BIOHUB_API_KEY"), ("api_key", "ESM_API_KEY")),
    "proto": (
        ("token_id", "MODAL_TOKEN_ID"),
        ("token_secret", "MODAL_TOKEN_SECRET"),
    ),
}


@dataclass(frozen=True)
class ExternalCredentials:
    provider: str
    values: Mapping[str, str]
    source: str

    @property
    def configured(self) -> bool:
        return _complete(self.provider, self.values)


@contextlib.contextmanager
def external_credential_session(values: Mapping[str, str]) -> Iterator[None]:
    """Bind credentials to one in-process session boundary."""

    token = _SESSION_CREDENTIALS.set(dict(values))
    try:
        yield
    finally:
        _SESSION_CREDENTIALS.reset(token)


def resolve_external_credentials(provider: str) -> ExternalCredentials:
    """Resolve from the bound session first, then the process environment."""

    normalized = provider.strip().lower()
    if normalized not in _ENV_KEYS:
        raise ValueError(f"unsupported external credential provider: {provider}")

    session = _values_from_mapping(normalized, _SESSION_CREDENTIALS.get())
    if _complete(normalized, session):
        return ExternalCredentials(normalized, session, "session")

    environment = _values_from_mapping(normalized, os.environ)
    if _complete(normalized, environment):
        return ExternalCredentials(normalized, environment, "environment")
    return ExternalCredentials(normalized, {}, "missing")


def credential_state(provider: str) -> dict[str, str | bool]:
    credentials = resolve_external_credentials(provider)
    return {"configured": credentials.configured, "source": credentials.source}


def _values_from_mapping(provider: str, values: Mapping[str, str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for field, environment_key in _ENV_KEYS[provider]:
        value = str(values.get(environment_key) or "").strip()
        if value and field not in found:
            found[field] = value
    return found


def _complete(provider: str, values: Mapping[str, str]) -> bool:
    required = {field for field, _ in _ENV_KEYS[provider]}
    return required <= set(values)


__all__ = [
    "ExternalCredentials",
    "credential_state",
    "external_credential_session",
    "resolve_external_credentials",
]
