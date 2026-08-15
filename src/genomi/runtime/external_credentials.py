"""Resolve external-provider credentials without presenting secret values."""

from __future__ import annotations

import contextlib
import contextvars
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
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


def resolve_external_credentials(
    provider: str, *, api_path: str | Path | None = None
) -> ExternalCredentials:
    normalized = provider.strip().lower()
    if normalized not in _ENV_KEYS:
        raise ValueError(f"unsupported external credential provider: {provider}")

    session = _values_from_mapping(normalized, _SESSION_CREDENTIALS.get())
    if _complete(normalized, session):
        return ExternalCredentials(normalized, session, "session")

    environment = _values_from_mapping(normalized, os.environ)
    if _complete(normalized, environment):
        return ExternalCredentials(normalized, environment, "environment")

    # Only the explicit path or this checkout's owner-managed api.md is read.
    candidate = Path(api_path) if api_path else Path(__file__).resolve().parents[3] / "api.md"
    local = _read_api_md(normalized, candidate.expanduser())
    if _complete(normalized, local):
        return ExternalCredentials(normalized, local, "local_api_file")
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


def _read_api_md(provider: str, path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return {}
    parsed = _parse_api_lines(lines)
    return parsed.get(provider, {})


def _parse_api_lines(lines: list[str]) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    for line in lines:
        label, separator, raw_value = line.partition(":")
        if not separator:
            continue
        provider = label.strip().lower()
        value = raw_value.strip()
        if provider == "paperclip" and value:
            parsed[provider] = {"api_key": value}
        elif provider == "biohub" and value:
            parsed[provider] = {"api_key": value}
        elif provider == "modal" and value:
            modal = _parse_modal_tokens(value)
            if modal:
                parsed["proto"] = modal
    return parsed


def _parse_modal_tokens(value: str) -> dict[str, str]:
    try:
        tokens = shlex.split(value)
    except ValueError:
        return {}
    result: dict[str, str] = {}
    for index, token in enumerate(tokens):
        if token == "--token-id" and index + 1 < len(tokens):
            result["token_id"] = tokens[index + 1]
        elif token.startswith("--token-id="):
            result["token_id"] = token.partition("=")[2]
        elif token == "--token-secret" and index + 1 < len(tokens):
            result["token_secret"] = tokens[index + 1]
        elif token.startswith("--token-secret="):
            result["token_secret"] = token.partition("=")[2]
    return {key: value for key, value in result.items() if value}


__all__ = [
    "ExternalCredentials",
    "credential_state",
    "external_credential_session",
    "resolve_external_credentials",
]
