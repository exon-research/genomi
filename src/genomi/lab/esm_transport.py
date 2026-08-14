"""Fail-closed placeholder for the future managed Biohub ESM runtime."""

from __future__ import annotations

from .evidence_types import EvidenceStatus, ProviderTransportError


class BiohubESMTransport:
    """Expose only an unavailable, token-validating connection probe."""

    verification_available = False

    def probe(self, token: str) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE)
