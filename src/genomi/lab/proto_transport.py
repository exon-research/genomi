"""Fail-closed placeholder for the future managed Proto expert runtime."""

from __future__ import annotations

from .evidence_types import EvidenceStatus, ProviderTransportError


class ModalProtoTransport:
    """Refuse credential-bearing Proto checks until its transport is pinned.

    Modal's public Python credential constructor resolves its service endpoint
    from ambient configuration. GenomiLab therefore does not pass saved Modal
    credentials to it. A future Proto lane must provide a Genomi-managed,
    versioned runtime and a fixed reviewed transport before enabling this probe.
    """

    verification_available = False

    def probe(self, token_id: str, token_secret: str, environment: str) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (token_id, token_secret, environment)
        ):
            raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
