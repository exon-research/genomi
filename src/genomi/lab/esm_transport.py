"""Response-safe Biohub ESM connection verification."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Final

from .evidence_types import EvidenceStatus, ProviderTransportError


BIOHUB_ESM_API_URL: Final = "https://biohub.ai/api/v1/encode"
BIOHUB_ESM_MODEL: Final = "esmc-600m-2024-12"
BIOHUB_ESM_REPOSITORY: Final = "https://github.com/Biohub/esm"
BIOHUB_ESM_COMMIT: Final = "26b0bc2b771e3e419ea74f445a5f35cc094a1509"
BIOHUB_ESM_TIMEOUT_SECONDS: Final = 15.0
BIOHUB_ESM_MAX_RESPONSE_BYTES: Final = 1_000_000

# Fixed synthetic alphabet covering every canonical amino acid exactly once.
# Connection checks never accept a patient or externally supplied sequence.
BIOHUB_ESM_PROBE_SEQUENCE: Final = "ACDEFGHIKLMNPQRSTVWY"
BIOHUB_ESM_PROBE_TOKENS: Final = (
    0,
    5,
    23,
    13,
    9,
    18,
    6,
    21,
    12,
    15,
    4,
    20,
    17,
    14,
    16,
    10,
    8,
    11,
    7,
    22,
    19,
    2,
)

OpenRequest = Callable[..., object]


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _open_request_without_redirects(
    request: urllib.request.Request, *, timeout: float
) -> object:
    return urllib.request.build_opener(_RejectRedirects()).open(
        request, timeout=timeout
    )


class BiohubESMTransport:
    """Verify an API token with one fixed, JSON-only synthetic request."""

    verification_available = True

    def __init__(
        self,
        *,
        open_request: OpenRequest = _open_request_without_redirects,
        timeout_seconds: float = BIOHUB_ESM_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._open_request = open_request
        self._timeout_seconds = timeout_seconds

    def probe(self, token: str) -> None:
        credential = _credential(token)
        request = urllib.request.Request(
            BIOHUB_ESM_API_URL,
            data=json.dumps(
                {
                    "inputs": {"sequence": BIOHUB_ESM_PROBE_SEQUENCE},
                    "model": BIOHUB_ESM_MODEL,
                    "potential_sequence_of_concern": False,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
                "User-Agent": "genomi/0.1",
            },
            method="POST",
        )
        try:
            response = self._open_request(request, timeout=self._timeout_seconds)
            with response:  # type: ignore[attr-defined]
                payload = _read_json_response(response)
        except urllib.error.HTTPError as exc:
            raise ProviderTransportError(_http_status(exc.code)) from None
        except (TimeoutError, socket.timeout):
            raise ProviderTransportError(EvidenceStatus.TIMEOUT) from None
        except urllib.error.URLError as exc:
            status = (
                EvidenceStatus.TIMEOUT
                if isinstance(exc.reason, (TimeoutError, socket.timeout))
                else EvidenceStatus.NETWORK_ERROR
            )
            raise ProviderTransportError(status) from None
        except (ConnectionError, OSError):
            raise ProviderTransportError(EvidenceStatus.NETWORK_ERROR) from None
        except ProviderTransportError:
            raise
        except Exception:
            raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE) from None
        _validate_encode_response(payload)


def _credential(token: object) -> str:
    if not isinstance(token, str) or not token.strip():
        raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
    return token.strip()


def _read_json_response(response: object) -> Mapping[str, object]:
    headers = getattr(response, "headers", None)
    content_type = (
        str(headers.get("Content-Type", "")) if hasattr(headers, "get") else ""
    )
    content_encoding = (
        str(headers.get("Content-Encoding", "")) if hasattr(headers, "get") else ""
    )
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
    if content_encoding.strip().lower() not in {"", "identity"}:
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
    data = response.read(BIOHUB_ESM_MAX_RESPONSE_BYTES + 1)  # type: ignore[attr-defined]
    if not isinstance(data, bytes) or len(data) > BIOHUB_ESM_MAX_RESPONSE_BYTES:
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE) from None
    if not isinstance(payload, Mapping):
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
    return payload


def _validate_encode_response(payload: Mapping[str, object]) -> None:
    resolved = _encode_payload(payload)
    outputs = resolved.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
    sequence = outputs.get("sequence")
    if (
        not isinstance(sequence, list)
        or any(
            isinstance(token, bool) or not isinstance(token, int) for token in sequence
        )
        or tuple(sequence) != BIOHUB_ESM_PROBE_TOKENS
        or resolved.get("potential_sequence_of_concern") is not False
    ):
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)


def _encode_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    if "outputs" in payload:
        return payload
    data = payload.get("data")
    if set(payload) == {"data"} and isinstance(data, Mapping):
        return data
    raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)


def _http_status(status_code: int) -> EvidenceStatus:
    if status_code in {401, 403}:
        return EvidenceStatus.AUTHENTICATION_FAILED
    if status_code == 429:
        return EvidenceStatus.RATE_LIMITED
    if status_code == 402:
        return EvidenceStatus.QUOTA_EXCEEDED
    if status_code in {408, 504}:
        return EvidenceStatus.TIMEOUT
    if 500 <= status_code <= 599:
        return EvidenceStatus.SERVER_ERROR
    return EvidenceStatus.SOURCE_UNAVAILABLE
