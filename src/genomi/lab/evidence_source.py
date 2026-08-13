"""Configured direct-primary-source route for GenomiLab evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_gateway import ProviderGateway
from .evidence_types import EvidenceResult
from .models import JsonObject
from .paperclip_adapter import (
    DirectSourceJobTransport,
    DirectSourceTransport,
    PaperclipOperation,
)
from .provider_policy import EvidenceRequest, SourceFamily, provider_name, required_text


@dataclass(frozen=True)
class DirectEvidenceSource:
    """One host-configured direct source and its optional resumable job route."""

    source_family: SourceFamily
    provider: str
    destination: str
    transport: DirectSourceTransport
    background_job_transport: DirectSourceJobTransport | None = None
    background_job_resume_operation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_family, SourceFamily):
            object.__setattr__(self, "source_family", SourceFamily(self.source_family))
        object.__setattr__(self, "provider", provider_name(self.provider))
        object.__setattr__(
            self,
            "destination",
            required_text(self.destination, "destination", 300),
        )
        if not callable(self.transport):
            raise ValueError("transport must be callable")
        if self.background_job_transport is None:
            if self.background_job_resume_operation is not None:
                raise ValueError(
                    "a direct-source resume operation requires a job transport"
                )
        else:
            if not callable(self.background_job_transport):
                raise ValueError("background_job_transport must be callable")
            object.__setattr__(
                self,
                "background_job_resume_operation",
                required_text(
                    self.background_job_resume_operation,
                    "background_job_resume_operation",
                    200,
                ),
            )

    def manifest(self) -> JsonObject:
        return {
            "source_family": self.source_family.value,
            "provider": self.provider,
            "destination": self.destination,
            "route": "direct_primary_source",
            "credentials_exposed": False,
            "background_job_check_available": self.background_job_transport is not None,
            **(
                {
                    "background_job_resume_operation": self.background_job_resume_operation
                }
                if self.background_job_resume_operation
                else {}
            ),
        }

    def resume_job(
        self,
        *,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        job_id: str,
        resume_operation: str,
        approved: bool,
    ) -> EvidenceResult:
        if (
            self.background_job_transport is None
            or resume_operation != self.background_job_resume_operation
        ):
            raise ValueError("direct-source job resume operation is unavailable")
        return ProviderGateway().retrieve_direct(
            provider=self.provider,
            request=request,
            transport=lambda approved_request: self.background_job_transport(
                PaperclipOperation(operation), approved_request, job_id
            ),
            exact_egress_approved=approved,
        )


__all__ = ["DirectEvidenceSource"]
