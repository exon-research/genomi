"""Load owner-controlled Paperclip policy records from a strict JSON file."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, TypeVar

from .paperclip_contract import PAPERCLIP_SUPPORTED_OPERATIONS
from .provider_policy import (
    PAPERCLIP_PROVIDER,
    AuthorizationBasis,
    DeploymentAuthorization,
    EvidenceDataClass,
    PatientDataContract,
    SourceFamily,
    required_text,
)


_MAX_CONFIG_BYTES = 64 * 1024
_ALLOWED_OPERATIONS = frozenset(
    operation.value for operation in PAPERCLIP_SUPPORTED_OPERATIONS
)
_DEPLOYMENT_FIELDS = frozenset(
    {
        "provider",
        "authorization_id",
        "basis",
        "permitted_source_families",
        "permitted_operations",
        "permitted_purposes",
        "permitted_data_classes",
        "effective_at",
        "expires_at",
        "revoked_at",
        "policy_version_id",
        "aup_version_id",
        "terms_version_id",
        "privacy_version_id",
        "live_use_authorized",
    }
)
_PATIENT_CONTRACT_FIELDS = frozenset(
    {
        "provider",
        "contract_id",
        "permitted_source_families",
        "permitted_operations",
        "permitted_purposes",
        "permitted_data_classes",
        "effective_at",
        "expires_at",
        "revoked_at",
        "policy_version_id",
        "aup_version_id",
        "terms_version_id",
        "privacy_version_id",
        "patient_influenced_data_authorized",
    }
)


class PaperclipAuthorizationConfigError(ValueError):
    """The deployment-owner policy file is absent, malformed, or out of scope."""


@dataclass(frozen=True)
class PaperclipAuthorizationConfig:
    deployment_authorization: DeploymentAuthorization
    patient_data_contract: PatientDataContract | None = None


def load_paperclip_authorization_config(
    path: str | Path,
) -> PaperclipAuthorizationConfig:
    """Read exact policy records; credentials never belong in this file."""

    payload = _load_json_object(path)
    _require_exact_fields(
        payload,
        field="paperclip_authorization",
        required=frozenset({"deployment_authorization"}),
        optional=frozenset({"patient_data_contract"}),
    )
    deployment = _deployment_authorization(payload["deployment_authorization"])
    contract = (
        _patient_data_contract(payload["patient_data_contract"])
        if "patient_data_contract" in payload
        else None
    )
    return PaperclipAuthorizationConfig(
        deployment_authorization=deployment,
        patient_data_contract=contract,
    )


def _load_json_object(path: str | Path) -> dict[str, object]:
    candidate = Path(path)
    encoded = _read_authorization_file(candidate)
    try:
        text = encoded.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_number,
        )
    except PaperclipAuthorizationConfigError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration must be valid UTF-8 JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration must be a JSON object."
        )
    return payload


def _read_authorization_file(candidate: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    elif candidate.is_symlink():
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration must be a regular file, not a symlink."
        )
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration could not be read."
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PaperclipAuthorizationConfigError(
                "Paperclip authorization configuration must be a regular file."
            )
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise PaperclipAuthorizationConfigError(
                "Paperclip authorization configuration must not be group- or world-writable."
            )
        if hasattr(os, "getuid") and metadata.st_uid not in {0, os.getuid()}:
            raise PaperclipAuthorizationConfigError(
                "Paperclip authorization configuration must be owned by the current user or root."
            )
        if metadata.st_size > _MAX_CONFIG_BYTES:
            raise PaperclipAuthorizationConfigError(
                "Paperclip authorization configuration is too large."
            )
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            encoded = handle.read(_MAX_CONFIG_BYTES + 1)
    except PaperclipAuthorizationConfigError:
        raise
    except OSError as exc:
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration could not be read."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(encoded) > _MAX_CONFIG_BYTES:
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization configuration is too large."
        )
    return encoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field, value in pairs:
        if field in result:
            raise PaperclipAuthorizationConfigError(
                "Paperclip authorization configuration contains a duplicate field."
            )
        result[field] = value
    return result


def _reject_non_finite_number(_value: str) -> object:
    raise PaperclipAuthorizationConfigError(
        "Paperclip authorization configuration contains a non-finite number."
    )


def _deployment_authorization(value: object) -> DeploymentAuthorization:
    payload = _policy_object(value, "deployment_authorization", _DEPLOYMENT_FIELDS)
    try:
        return DeploymentAuthorization(
            **_shared_policy_fields(payload),
            authorization_id=_text(payload["authorization_id"], "authorization_id"),
            basis=_enum(payload["basis"], "basis", AuthorizationBasis),
            live_use_authorized=_boolean(
                payload["live_use_authorized"], "live_use_authorized"
            ),
        )
    except PaperclipAuthorizationConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise PaperclipAuthorizationConfigError(
            "deployment_authorization is internally inconsistent."
        ) from exc


def _patient_data_contract(value: object) -> PatientDataContract:
    payload = _policy_object(value, "patient_data_contract", _PATIENT_CONTRACT_FIELDS)
    try:
        return PatientDataContract(
            **_shared_policy_fields(payload),
            contract_id=_text(payload["contract_id"], "contract_id"),
            patient_influenced_data_authorized=_boolean(
                payload["patient_influenced_data_authorized"],
                "patient_influenced_data_authorized",
            ),
        )
    except PaperclipAuthorizationConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise PaperclipAuthorizationConfigError(
            "patient_data_contract is internally inconsistent."
        ) from exc


def _shared_policy_fields(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "provider": _paperclip_provider(payload["provider"]),
        "permitted_source_families": _enum_set(
            payload["permitted_source_families"],
            "permitted_source_families",
            SourceFamily,
        ),
        "permitted_operations": _operation_set(payload["permitted_operations"]),
        "permitted_purposes": _text_set(
            payload["permitted_purposes"], "permitted_purposes", maximum=500
        ),
        "permitted_data_classes": _enum_set(
            payload["permitted_data_classes"],
            "permitted_data_classes",
            EvidenceDataClass,
        ),
        "effective_at": _timestamp(payload["effective_at"], "effective_at"),
        "expires_at": _timestamp(payload["expires_at"], "expires_at"),
        "revoked_at": _optional_timestamp(payload["revoked_at"], "revoked_at"),
        "policy_version_id": _text(payload["policy_version_id"], "policy_version_id"),
        "aup_version_id": _text(payload["aup_version_id"], "aup_version_id"),
        "terms_version_id": _text(payload["terms_version_id"], "terms_version_id"),
        "privacy_version_id": _text(
            payload["privacy_version_id"], "privacy_version_id"
        ),
    }


def _policy_object(
    value: object, field: str, expected: frozenset[str]
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PaperclipAuthorizationConfigError(f"{field} must be a JSON object.")
    _require_exact_fields(value, field=field, required=expected)
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    *,
    field: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    missing = sorted(required - set(payload))
    if missing:
        raise PaperclipAuthorizationConfigError(
            f"{field} is missing required field {missing[0]}."
        )
    unknown = sorted(set(payload) - required - optional)
    if unknown:
        raise PaperclipAuthorizationConfigError(
            f"{field} contains an unsupported field."
        )


def _paperclip_provider(value: object) -> str:
    provider = _text(value, "provider", maximum=100)
    if provider != PAPERCLIP_PROVIDER:
        raise PaperclipAuthorizationConfigError(
            "Paperclip authorization provider must be paperclip."
        )
    return provider


def _text(value: object, field: str, maximum: int = 200) -> str:
    try:
        normalized = required_text(value, field, maximum)
    except ValueError as exc:
        raise PaperclipAuthorizationConfigError(str(exc)) from exc
    if value != normalized:
        raise PaperclipAuthorizationConfigError(
            f"{field} must not contain surrounding whitespace."
        )
    return normalized


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise PaperclipAuthorizationConfigError(f"{field} must be a boolean.")
    return value


def _text_set(value: object, field: str, *, maximum: int) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise PaperclipAuthorizationConfigError(
            f"{field} must be a non-empty JSON array."
        )
    items = tuple(_text(item, field, maximum) for item in value)
    if len(items) != len(set(items)):
        raise PaperclipAuthorizationConfigError(f"{field} contains a duplicate value.")
    return frozenset(items)


def _operation_set(value: object) -> frozenset[str]:
    operations = _text_set(value, "permitted_operations", maximum=100)
    if not operations.issubset(_ALLOWED_OPERATIONS):
        raise PaperclipAuthorizationConfigError(
            "permitted_operations contains an operation unavailable in the pinned Paperclip transport."
        )
    return operations


EnumValue = TypeVar("EnumValue")


def _enum_set(
    value: object,
    field: str,
    enum_type: Callable[[object], EnumValue],
) -> frozenset[EnumValue]:
    values = _text_set(value, field, maximum=100)
    try:
        return frozenset(enum_type(item) for item in values)
    except ValueError as exc:
        raise PaperclipAuthorizationConfigError(
            f"{field} contains an unsupported value."
        ) from exc


def _enum(
    value: object,
    field: str,
    enum_type: Callable[[object], EnumValue],
) -> EnumValue:
    text = _text(value, field, maximum=100)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise PaperclipAuthorizationConfigError(
            f"{field} contains an unsupported value."
        ) from exc


def _timestamp(value: object, field: str) -> datetime:
    text = _text(value, field, maximum=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperclipAuthorizationConfigError(
            f"{field} must be an ISO-8601 timestamp with a UTC offset."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperclipAuthorizationConfigError(
            f"{field} must be an ISO-8601 timestamp with a UTC offset."
        )
    return parsed


def _optional_timestamp(value: object, field: str) -> datetime | None:
    return None if value is None else _timestamp(value, field)


__all__ = [
    "PaperclipAuthorizationConfig",
    "PaperclipAuthorizationConfigError",
    "load_paperclip_authorization_config",
]
