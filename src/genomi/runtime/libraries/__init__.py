"""Genomi's central data-source library registry and manager.

Every external data source — downloadable reference library, live API, derived
panel, user-supplied file — is one ``LibrarySpec`` in ``registry`` and is
managed only through ``manager`` (``ensure`` for runtime, ``install``/``refresh``
for the installer). Consumers import from this package, not from the individual
modules.
"""

from . import manager, registry
from .manager import (
    ensure,
    install,
    install_command,
    inventory,
    missing_request,
    refresh,
    status,
)
from .registry import (
    all_ids,
    all_specs,
    get,
    has,
    purposes,
    resolve_selection,
)
from .spec import Freshness, Kind, LibrarySpec, Source, Transform

__all__ = [
    "manager",
    "registry",
    "ensure",
    "install",
    "install_command",
    "inventory",
    "missing_request",
    "refresh",
    "status",
    "all_ids",
    "all_specs",
    "get",
    "has",
    "purposes",
    "resolve_selection",
    "Freshness",
    "Kind",
    "LibrarySpec",
    "Source",
    "Transform",
]
