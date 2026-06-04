"""The unified data-source model for Genomi's central library registry.

Every external data source Genomi uses — a downloadable reference library, a
live public API, a locally-derived panel, a user-supplied file — is ONE
``LibrarySpec`` in the registry (see ``registry.py``). The spec is the single
source of truth: id, description, where the bytes come from, where they land,
how to transform them, what proves it is installed, and how to tell whether it
is current. The install/update path and on-demand runtime materialization both
go through the manager (see ``manager.py``) reading these specs — no per-module
download code with its own lifetime, no duplicated catalogs.

Paths here are RELATIVE to ``GENOMI_HOME``; the manager resolves them against
the live data root so tests can relocate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Kind(str, Enum):
    """What sort of source this is; decides install, status, and freshness behavior."""

    OFFLINE = "offline"  # downloaded + cached under GENOMI_HOME
    ONLINE = "online"  # live public API; never cached offline
    DERIVED = "derived"  # built locally from other libraries (no direct download)
    MANUAL = "manual"  # user must supply the file (no public URL)
    PARAMETERIZED = "parameterized"  # per-key cache, e.g. PRS scoring files by pgs_id


class Transform(str, Enum):
    """Post-download processing applied before a source counts as installed."""

    NONE = "none"  # store the bytes as-is
    GUNZIP_FAIDX = "gunzip_faidx"  # decompress a .fa.gz, then build the .fai index
    XLSX_TO_TSV = "xlsx_to_tsv"  # normalize an XLSX export to a Genomi marker TSV
    TAR_EXTRACT = "tar_extract"  # extract a tarball (flattening a leading dir)


class Freshness(str, Enum):
    """How the manager decides whether an installed source is current."""

    HTTP_VALIDATORS = "http_validators"  # conditional GET via stored ETag/Last-Modified
    GITHUB_RELEASE_TAG = "github_release_tag"  # compare installed tag to releases/latest
    PINNED_SHA = "pinned_sha"  # version+sha256 pinned in the registry; bumps with the registry
    MANUAL = "manual"  # user-supplied; nothing upstream to check
    LIVE = "live"  # online API; always current — only reachability is checked
    DERIVED = "derived"  # rebuild when its input libraries change


@dataclass(frozen=True)
class Source:
    """Where a source's bytes (or endpoint) come from. Fields used depend on Kind.

    - OFFLINE: ``urls`` (one per target), optional ``user_agent``.
    - GITHUB_RELEASE_TAG freshness: ``github_release_api`` (+ optional ``version`` pin).
    - PINNED_SHA: ``urls`` + ``sha256`` (+ ``version``), Linux-x64 binaries / tarballs.
    - ONLINE: ``api_base`` (used for the reachability probe; per-call URLs live in the
      capability, which asks the manager only "is this source available?").
    - DERIVED: ``derived_from`` — the library ids this one is built from.
    - MANUAL: nothing here; the user passes a path/url at install time.
    """

    urls: tuple[str, ...] = ()
    github_release_api: str | None = None
    api_base: str | None = None
    sha256: str | None = None
    version: str | None = None
    derived_from: tuple[str, ...] = ()
    user_agent: str | None = None


@dataclass(frozen=True)
class LibrarySpec:
    """One entry in the central registry — the single source of truth for a source."""

    id: str
    title: str
    helps: str
    kind: Kind
    size_class: str = ""  # human size, e.g. "~180 MB"; "online" for live APIs
    purposes: tuple[str, ...] = ()  # install purposes this belongs to (everything, common-questions, …)
    source: Source = field(default_factory=Source)
    transform: Transform = Transform.NONE
    freshness: Freshness = Freshness.HTTP_VALIDATORS
    # Paths RELATIVE to GENOMI_HOME, resolved by the manager.
    targets: tuple[Path, ...] = ()  # where downloaded bytes land (one per source url)
    required_paths: tuple[Path, ...] = ()  # existence proves "installed" (offline/derived/manual)
    manual_source_required: bool = False
    platform_linux_x64_only: bool = False  # binaries skipped on macOS/ARM

    @property
    def is_offline(self) -> bool:
        return self.kind in (Kind.OFFLINE, Kind.DERIVED, Kind.MANUAL, Kind.PARAMETERIZED)

    @property
    def is_online(self) -> bool:
        return self.kind is Kind.ONLINE
