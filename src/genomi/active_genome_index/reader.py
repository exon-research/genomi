"""The single sanctioned way to *read* Active Genome Index data.

Every capability that needs per-sample genome rows goes through an ``ActiveGenomeIndexReader``
instead of opening the SQLite index itself. The reader is bound to one resolved
index path, wraps the ``_agi_query`` helpers and ``connect_existing_readonly``,
and exposes the *parse state* so a caller can tell what is still building (a
two-phase gVCF parse is ``variants_ready`` — every variant is queryable — while
its reference-block tail is still being appended in the background).

This module is pure data layer: it performs the *readiness* gate but knows
nothing about session authorization. The authorization gate lives one layer up
in ``genomi.runtime.context.agi_access``, which resolves + authorizes a run and
then hands back an ``ActiveGenomeIndexReader`` built here. Keeping auth out of this module
preserves the ``active_genome_index`` package's independence from the runtime
and operations layers (no circular imports).
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from ._agi_query import coverage_query, query_region, query_rsid_filtered, query_variant
from ._agi_readiness import (
    REFERENCE_PENDING_NOTE,
    active_genome_index_readiness,
    ensure_active_genome_index_complete,
)
from ._agi_schema import connect_existing_readonly

JsonObject = dict[str, Any]


class ActiveGenomeIndexNeed(Enum):
    """The class of AGI data a caller needs — governs the readiness gate and
    whether a result is stamped ``reference_pending``.

    - ``NONE``: the caller reads no AGI rows (it may only need the resolved
      paths / approval). No readiness gate.
    - ``VARIANT``: the variant interpretation surface (rsID, gene, region,
      exact-allele, ClinVar, PRS markers). Final at ``variants_ready`` — never
      stamped ``reference_pending``.
    - ``REFERENCE``: a reference-dependent read (coverage, callability,
      genotype-support, callset-QC, reference-block stats). Usable at
      ``completed`` and *degraded* at ``variants_ready`` — a negative/empty
      answer there is provisional, so the caller's result is stamped
      ``reference_pending`` until the reference-block tail lands.
    """

    NONE = "none"
    VARIANT = "variant"
    REFERENCE = "reference"


@dataclass(frozen=True)
class ActiveGenomeIndexReader:
    """A readiness-gated, parse-state-aware view of one Active Genome Index.

    The only place capability code opens the AGI SQLite. Construct via
    :func:`open_reader` (or the authorizing ``agi_access.open_agi`` wrapper) —
    never instantiate against an ungated path.
    """

    active_genome_index_path: Path
    need: ActiveGenomeIndexNeed
    readiness: JsonObject = field(default_factory=dict)
    vcf_path: Path | None = None
    genome_build: str | None = None

    # --- parse-state identification -------------------------------------
    @property
    def complete(self) -> bool:
        """The whole index is built (every variant *and* the reference tail)."""
        return bool(self.readiness.get("complete"))

    @property
    def variants_ready(self) -> bool:
        """Every variant is queryable. The reference-block tail may still be
        appending (a two-phase gVCF parse), in which case ``complete`` is
        False and ``reference_pending`` is True."""
        return bool(self.readiness.get("variants_ready")) or self.complete

    @property
    def reference_pending(self) -> bool:
        """``variants_ready`` but the reference-block tail is still being
        appended (Phase B). Reference-dependent answers are provisional."""
        return bool(self.readiness.get("variants_ready")) and not self.complete

    def parse_state(self) -> JsonObject:
        """A compact summary of what is built vs. still parsing — surfaced so a
        host can tell a final negative from a provisional one."""
        state: JsonObject = {
            "status": self.readiness.get("status"),
            "complete": self.complete,
            "variants_ready": self.variants_ready,
            "reference_pending": self.reference_pending,
        }
        if self.reference_pending:
            state["note"] = REFERENCE_PENDING_NOTE
        return state

    # --- data access (the ONLY AGI read path) --------------------------
    def query_rsid(self, rsid: str, *, limit: int = 50, pass_only: bool = False) -> list[dict[str, Any]]:
        return query_rsid_filtered(
            self._source_hint, rsid, self.active_genome_index_path, limit=limit, pass_only=pass_only
        )

    def query_variant(
        self, chrom: str, pos: int, ref: str, alt: str, *, limit: int = 50, pass_only: bool = False
    ) -> list[dict[str, Any]]:
        return query_variant(
            self._source_hint, chrom, pos, ref, alt, self.active_genome_index_path, limit=limit, pass_only=pass_only
        )

    def query_region(
        self,
        chrom: str,
        start: int,
        end: int,
        *,
        variants_only: bool = False,
        pass_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return query_region(
            self._source_hint,
            chrom,
            start,
            end,
            self.active_genome_index_path,
            variants_only=variants_only,
            pass_only=pass_only,
            limit=limit,
        )

    def coverage(self, chrom: str, start: int, end: int, *, limit: int = 200) -> dict[str, Any]:
        return coverage_query(self._source_hint, chrom, start, end, self.active_genome_index_path, limit=limit)

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A read-only connection for bespoke SQL (PRS dosage, ancestry overlap,
        reference-block stats).

        The readiness gate is enforced *here*, lazily, at the moment data is
        actually read — not eagerly when the reader is built. That lets a
        capability run its cheap public prerequisite checks first (panel
        installed? score imported?) and only pay the readiness gate when it
        truly needs the index. For ``VARIANT``/``REFERENCE`` this raises the
        lifecycle / ``ActiveGenomeIndexIncomplete`` exceptions that
        ``call_operation`` maps to structured envelopes; ``NONE`` skips the gate
        (build-on-demand callers manage their own index lifecycle)."""
        if self.need is not ActiveGenomeIndexNeed.NONE:
            ensure_active_genome_index_complete(self.active_genome_index_path)
        connection = connect_existing_readonly(self.active_genome_index_path)
        try:
            yield connection
        finally:
            connection.close()

    @property
    def _source_hint(self) -> Path:
        # The query helpers take a vcf_path positionally but only use it to
        # derive a default index path when none is passed — and we always pass
        # the resolved index path, so the hint is never consulted.
        return self.vcf_path or self.active_genome_index_path


def open_reader(
    active_genome_index_path: str | Path,
    *,
    need: ActiveGenomeIndexNeed,
    vcf_path: str | Path | None = None,
    genome_build: str | None = None,
) -> ActiveGenomeIndexReader:
    """Build an :class:`ActiveGenomeIndexReader` bound to one index path.

    The readiness gate is NOT enforced here — it is deferred to the moment data
    is read (:meth:`ActiveGenomeIndexReader.connect` and the ``query_*`` helpers). Building a
    reader is therefore cheap and side-effect-free, so a caller can inspect
    :attr:`ActiveGenomeIndexReader.readiness` / parse-state and run its own cheap *public*
    prerequisite checks (panel installed? score imported?) before paying — or
    triggering — the gate. ``need`` is carried on the reader and decides what
    the lazy gate raises and what gets stamped ``reference_pending`` downstream.
    """
    path = Path(active_genome_index_path)
    return ActiveGenomeIndexReader(
        active_genome_index_path=path,
        need=need,
        readiness=active_genome_index_readiness(path),
        vcf_path=Path(vcf_path) if vcf_path is not None else None,
        genome_build=genome_build,
    )


# Re-export so reader callers have one import for the provisional-answer
# guidance string they stamp on degraded reference reads.
__all__ = ["ActiveGenomeIndexNeed", "ActiveGenomeIndexReader", "open_reader", "REFERENCE_PENDING_NOTE"]
