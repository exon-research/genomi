"""Canonical typed-operation and corpus scope for GXL Paperclip."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .paperclip_adapter import PaperclipOperation
from .provider_policy import SourceFamily


PAPERCLIP_MAX_QUERY_TERMS = 5
PAPERCLIP_INTERNAL_FILTERS = frozenset({"evidence_domain"})
PAPERCLIP_SUPPORTED_OPERATIONS = (
    PaperclipOperation.SEARCH,
    PaperclipOperation.LOOKUP,
)
_LOOKUP_FIELDS = (
    "doi",
    "pmc",
    "pmid",
    "author",
    "title",
    "journal",
    "year",
    "keywords",
)
_SEARCH_FILTERS = (
    "exact",
    "since",
    "sort",
    "author",
    "journal",
    "year",
    "type",
    "category",
    "mode",
)


@dataclass(frozen=True)
class PaperclipOperationScope:
    """Public-input contract for one typed Paperclip operation."""

    operation: PaperclipOperation
    allowed_filter_fields: tuple[str, ...]
    required_filter_fields: tuple[str, ...] = ()
    filter_allowed_values: tuple[tuple[str, tuple[str, ...]], ...] = ()
    maximum_query_terms: int = PAPERCLIP_MAX_QUERY_TERMS
    query_terms_must_equal_query: bool = False

    def accepts(
        self,
        *,
        query: str,
        query_terms: Sequence[str],
        filters: Mapping[str, str],
        allow_internal_filters: bool = False,
    ) -> bool:
        allowed = set(self.allowed_filter_fields)
        if allow_internal_filters:
            allowed.update(PAPERCLIP_INTERNAL_FILTERS)
        if set(filters) - allowed:
            return False
        if not set(self.required_filter_fields).issubset(filters):
            return False
        if not 1 <= len(query_terms) <= self.maximum_query_terms:
            return False
        if self.query_terms_must_equal_query and tuple(query_terms) != (query,):
            return False
        allowed_values = dict(self.filter_allowed_values)
        return all(
            name not in filters or filters[name] in values
            for name, values in allowed_values.items()
        )

    def catalog_contract(self) -> dict[str, object]:
        allowed_values = dict(self.filter_allowed_values)
        return {
            "query_terms": {
                "type": "unique_public_biomedical_string_array",
                "minimum_items": 1,
                "maximum_items": self.maximum_query_terms,
                **(
                    {"items_must_equal_field": "query"}
                    if self.query_terms_must_equal_query
                    else {}
                ),
            },
            "filters": {
                "type": "public_string_map",
                "allowed_fields": list(self.allowed_filter_fields),
                "required_fields": list(self.required_filter_fields),
                "fields": {
                    name: {"allowed_values": list(values)}
                    for name, values in allowed_values.items()
                },
            },
        }


@dataclass(frozen=True)
class PaperclipRouteDefinition:
    """Typed operations and concrete provider corpora for one source family."""

    source_family: SourceFamily
    corpora: tuple[str, ...]
    operation_scopes: tuple[PaperclipOperationScope, ...]

    @property
    def operations(self) -> tuple[PaperclipOperation, ...]:
        return tuple(scope.operation for scope in self.operation_scopes)

    def operation_scope(
        self, operation: PaperclipOperation | str
    ) -> PaperclipOperationScope | None:
        normalized = PaperclipOperation(operation)
        return next(
            (scope for scope in self.operation_scopes if scope.operation == normalized),
            None,
        )


PAPERCLIP_SEARCH_SCOPE = PaperclipOperationScope(
    operation=PaperclipOperation.SEARCH,
    allowed_filter_fields=_SEARCH_FILTERS,
    filter_allowed_values=(("exact", ("true", "false")),),
)
PAPERCLIP_LOOKUP_SCOPE = PaperclipOperationScope(
    operation=PaperclipOperation.LOOKUP,
    allowed_filter_fields=("lookup_field",),
    required_filter_fields=("lookup_field",),
    filter_allowed_values=(("lookup_field", _LOOKUP_FIELDS),),
    maximum_query_terms=1,
    query_terms_must_equal_query=True,
)
PAPERCLIP_ROUTE_DEFINITIONS: dict[SourceFamily, PaperclipRouteDefinition] = {
    SourceFamily.LITERATURE: PaperclipRouteDefinition(
        source_family=SourceFamily.LITERATURE,
        corpora=("pmc", "biorxiv", "medrxiv", "arxiv"),
        operation_scopes=(PAPERCLIP_SEARCH_SCOPE, PAPERCLIP_LOOKUP_SCOPE),
    ),
    SourceFamily.REGULATORY: PaperclipRouteDefinition(
        source_family=SourceFamily.REGULATORY,
        corpora=("fda",),
        operation_scopes=(PAPERCLIP_SEARCH_SCOPE,),
    ),
    SourceFamily.TRIAL_REGISTRY: PaperclipRouteDefinition(
        source_family=SourceFamily.TRIAL_REGISTRY,
        corpora=("trials",),
        operation_scopes=(PAPERCLIP_SEARCH_SCOPE,),
    ),
}


def paperclip_route_definition(
    source_family: SourceFamily | str,
) -> PaperclipRouteDefinition | None:
    try:
        normalized = SourceFamily(source_family)
    except ValueError:
        return None
    return PAPERCLIP_ROUTE_DEFINITIONS.get(normalized)


def paperclip_operation_scope(
    source_family: SourceFamily | str,
    operation: PaperclipOperation | str,
) -> PaperclipOperationScope | None:
    route = paperclip_route_definition(source_family)
    if route is None:
        return None
    try:
        return route.operation_scope(operation)
    except ValueError:
        return None
