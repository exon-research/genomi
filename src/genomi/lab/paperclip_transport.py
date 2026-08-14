"""Concrete, structured transport for the narrow GXL Paperclip surface."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

from .evidence_types import EvidenceStatus, ProviderTransportError
from .paperclip_adapter import PaperclipOperation
from .paperclip_contract import (
    PAPERCLIP_INTERNAL_FILTERS,
    PAPERCLIP_ROUTE_DEFINITIONS,
    PAPERCLIP_SEARCH_SCOPE,
    PAPERCLIP_SUPPORTED_OPERATIONS,
    paperclip_route_definition,
)
from .provider_policy import (
    PAPERCLIP_CONNECTION_PROBE_QUERY,
    EvidenceRequest,
    SourceFamily,
)


PAPERCLIP_SEARCH_LIMIT = 20
PAPERCLIP_REQUEST_TIMEOUT_SECONDS = 120.0
PAPERCLIP_PROBE_TIMEOUT_SECONDS = 15.0
PAPERCLIP_PROBE_SOURCE = "pmc"
PAPERCLIP_BASE_URL = "https://paperclip.gxl.ai"
PAPERCLIP_SDK_VERSION = "0.4.2"
PAPERCLIP_SDK_REPOSITORY = "https://github.com/GXL-ai/paperclip"
PAPERCLIP_SDK_COMMIT = "b5571365f0b36847dce42c5d66d2b158a0f871f9"


def _retrieved_at() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


_LITERATURE_SOURCES = frozenset(
    {
        "pmc",
        "biorxiv",
        "medrxiv",
        "arxiv",
        "abstracts",
        "pubmed",
    }
)
_REGULATORY_SOURCES = frozenset({"fda", "regulatory"})
_TRIAL_SOURCES = frozenset({"trials", "clinicaltrials", "clinicaltrials.gov"})


PaperclipClientFactory = Callable[[str], object]


def _official_client(secret: str) -> object:
    """Build the official client with an explicit key and no ambient fallback."""

    try:
        from gxl_paperclip import APIKeyAuth, PaperclipClient
    except ImportError as exc:
        raise ProviderTransportError(EvidenceStatus.SOURCE_UNAVAILABLE) from exc
    return PaperclipClient(auth=APIKeyAuth(secret), base_url=PAPERCLIP_BASE_URL)


def _transport_error(exc: Exception) -> ProviderTransportError:
    status = {
        "AuthError": EvidenceStatus.AUTHENTICATION_FAILED,
        "RateLimitError": EvidenceStatus.RATE_LIMITED,
        "RequestTimeoutError": EvidenceStatus.TIMEOUT,
        "NetworkError": EvidenceStatus.NETWORK_ERROR,
        "NotFoundError": EvidenceStatus.NOT_FOUND,
        "ServerError": EvidenceStatus.SERVER_ERROR,
    }.get(type(exc).__name__, EvidenceStatus.SERVER_ERROR)
    return ProviderTransportError(status)


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        raw = asdict(value)
        if isinstance(raw, Mapping):
            return raw
    raw = getattr(value, "__dict__", None)
    return raw if isinstance(raw, Mapping) else {}


def _structured_papers(result: object) -> Sequence[object]:
    exit_code = getattr(result, "exit_code", None)
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code != 0:
        raise ProviderTransportError(EvidenceStatus.SERVER_ERROR)
    result_data = getattr(result, "result_data", None)
    if not isinstance(result_data, Mapping):
        raise ProviderTransportError(EvidenceStatus.SERVER_ERROR)
    papers = result_data.get("papers")
    if papers is None:
        papers = result_data.get("results")
    if not isinstance(papers, Sequence) or isinstance(papers, (str, bytes, bytearray)):
        raise ProviderTransportError(EvidenceStatus.SERVER_ERROR)
    return papers


def _search_filter_kwargs(filters: Mapping[str, str]) -> dict[str, object] | None:
    allowed_filters = PAPERCLIP_SEARCH_SCOPE.allowed_filter_fields
    if set(filters) - set(allowed_filters) - PAPERCLIP_INTERNAL_FILTERS:
        return None
    kwargs: dict[str, object] = {}
    for name in allowed_filters:
        value = filters.get(name)
        if value is None:
            continue
        if name == "exact":
            normalized = value.lower()
            if normalized not in {"true", "false"}:
                return None
            kwargs[name] = normalized == "true"
        else:
            kwargs[name] = value
    return kwargs


def _text(raw: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _http_uri(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _document_state(request: EvidenceRequest, source: str | None) -> str:
    if request.source_family is SourceFamily.TRIAL_REGISTRY:
        return "trial_registration"
    if request.source_family is SourceFamily.REGULATORY:
        return "regulatory_document"
    if request.source_family in {
        SourceFamily.UNIPROT,
        SourceFamily.PDB,
        SourceFamily.CHEMBL,
    }:
        return "structured_database"
    lowered = (source or "").lower()
    return "preprint" if lowered in {"biorxiv", "medrxiv", "arxiv"} else "abstract_only"


def _record_source_family(
    raw: Mapping[str, object], source_id: str
) -> SourceFamily | None:
    source = (_text(raw, "source", "source_name") or "").lower()
    if source in _LITERATURE_SOURCES:
        return SourceFamily.LITERATURE
    if source in _REGULATORY_SOURCES:
        return SourceFamily.REGULATORY
    if source in _TRIAL_SOURCES:
        return SourceFamily.TRIAL_REGISTRY
    normalized_id = source_id.lower()
    if normalized_id.startswith(("pmc", "pmid", "bio_", "med_", "arx_")):
        return SourceFamily.LITERATURE
    if normalized_id.startswith(("nct", "isrctn")):
        return SourceFamily.TRIAL_REGISTRY
    if normalized_id.startswith(("fda", "nda", "bla")):
        return SourceFamily.REGULATORY
    return None


def _record(request: EvidenceRequest, paper: object) -> dict[str, object] | None:
    raw = _mapping(paper)
    source_id = _text(raw, "document_id")
    title = _text(raw, "title")
    if source_id is None or title is None:
        return None
    if _record_source_family(raw, source_id) is not request.source_family:
        return None
    source = _text(raw, "source", "source_name")
    record: dict[str, object] = {
        "source_id": source_id,
        "title": title,
        "source_document_state": _document_state(request, source),
        "source_license": {"status": "not_provided"},
    }
    source_uri = _http_uri(_text(raw, "source_uri", "url", "uri"))
    if source_uri is not None:
        record["source_uri"] = source_uri
    for name, aliases in {
        "doi": ("doi",),
        "pmid": ("pmid",),
        "pmcid": ("pmcid", "pmc"),
        "publication_date": ("publication_date", "published_at", "pub_date", "date"),
    }.items():
        value = _text(raw, *aliases)
        if value is not None:
            record[name] = value
    return record


class GxlPaperclipTransport:
    """Use only typed SDK calls and structured paper rows."""

    supported_operations = PAPERCLIP_SUPPORTED_OPERATIONS
    supported_source_families = tuple(PAPERCLIP_ROUTE_DEFINITIONS)
    supported_routes = {
        family: route.operations
        for family, route in PAPERCLIP_ROUTE_DEFINITIONS.items()
    }

    def __init__(
        self, *, client_factory: PaperclipClientFactory = _official_client
    ) -> None:
        self._client_factory = client_factory

    def probe(self, secret: str) -> None:
        client = self._client(secret)
        try:
            result = client.search(
                PAPERCLIP_CONNECTION_PROBE_QUERY,
                source=PAPERCLIP_PROBE_SOURCE,
                limit=1,
                timeout=PAPERCLIP_PROBE_TIMEOUT_SECONDS,
            )
        except ProviderTransportError:
            raise
        except Exception as exc:
            raise _transport_error(exc) from exc
        _structured_papers(result)

    def __call__(
        self,
        operation: PaperclipOperation,
        request: EvidenceRequest,
        secret: str,
    ) -> Mapping[str, object]:
        operation = PaperclipOperation(operation)
        if operation not in self.supported_operations:
            raise ValueError("Paperclip operation is not allowlisted by this transport")
        route = paperclip_route_definition(request.source_family)
        if route is None:
            return self._empty(request, "out_of_scope_for_input")
        filters = dict(request.filters)
        operation_scope = route.operation_scope(operation)
        if operation_scope is None or not operation_scope.accepts(
            query=request.query,
            query_terms=request.query_terms,
            filters=filters,
            allow_internal_filters=True,
        ):
            return self._empty(request, "out_of_scope_for_input")
        if operation is PaperclipOperation.LOOKUP:
            field = filters.get("lookup_field", "").lower()
            search_filter_kwargs = None
        else:
            search_filter_kwargs = _search_filter_kwargs(filters)
            assert search_filter_kwargs is not None
        client = self._client(secret)
        records: list[dict[str, object]] = []
        misses: list[str] = []
        result_ids: list[str] = []
        try:
            if operation is PaperclipOperation.SEARCH:
                for term in request.query_terms:
                    kwargs: dict[str, object] = {
                        "limit": PAPERCLIP_SEARCH_LIMIT,
                        "timeout": PAPERCLIP_REQUEST_TIMEOUT_SECONDS,
                        "source": ",".join(route.corpora),
                        **(search_filter_kwargs or {}),
                    }
                    result = client.search(term, **kwargs)
                    papers = _structured_papers(result)
                    result_id = self._result_id(result)
                    term_records = [
                        item for paper in papers if (item := _record(request, paper))
                    ]
                    if papers and not term_records:
                        raise ProviderTransportError(EvidenceStatus.SERVER_ERROR)
                    if not term_records:
                        misses.append(term)
                    if result_id is not None:
                        for record in term_records:
                            record["provider_result_id"] = result_id
                    records.extend(term_records)
                    if result_id is not None:
                        result_ids.append(result_id)
            else:
                result = client.lookup(
                    field,
                    request.query,
                    limit=PAPERCLIP_SEARCH_LIMIT,
                    timeout=PAPERCLIP_REQUEST_TIMEOUT_SECONDS,
                )
                papers = _structured_papers(result)
                result_id = self._result_id(result)
                records = [
                    item for paper in papers if (item := _record(request, paper))
                ]
                if papers and not records:
                    raise ProviderTransportError(EvidenceStatus.SERVER_ERROR)
                if not records:
                    misses.append(request.query)
                if result_id is not None:
                    for record in records:
                        record["provider_result_id"] = result_id
                    result_ids.append(result_id)
        except ProviderTransportError:
            raise
        except Exception as exc:
            raise _transport_error(exc) from exc
        records = list({record["source_id"]: record for record in records}.values())
        raw: dict[str, object] = {
            "status": "data_returned" if records else "in_scope_empty",
            "source_family": request.source_family.value,
            "records": records,
            "coverage": {
                "consulted": list(route.corpora),
                "misses": misses,
            },
            "process_provenance": {
                "provider_result_ids": list(dict.fromkeys(result_ids)),
                "provider_version": PAPERCLIP_SDK_VERSION,
                "provider_repository": PAPERCLIP_SDK_REPOSITORY,
                "provider_commit": PAPERCLIP_SDK_COMMIT,
                "retrieved_at": _retrieved_at(),
            },
        }
        return raw

    @staticmethod
    def _result_id(result: object) -> str | None:
        result_id = getattr(result, "result_id", None)
        return (
            result_id.strip()
            if isinstance(result_id, str) and result_id.strip()
            else None
        )

    def _client(self, secret: str) -> object:
        if not isinstance(secret, str) or not secret.strip():
            raise ProviderTransportError(EvidenceStatus.AUTHENTICATION_FAILED)
        try:
            return self._client_factory(secret)
        except ProviderTransportError:
            raise
        except Exception as exc:
            raise _transport_error(exc) from exc

    @staticmethod
    def _empty(request: EvidenceRequest, status: str) -> Mapping[str, object]:
        return {
            "status": status,
            "source_family": request.source_family.value,
            "records": [],
            "coverage": {"consulted": []},
        }
