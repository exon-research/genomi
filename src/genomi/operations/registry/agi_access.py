"""The single sanctioned way a handler obtains a readable Active Genome Index.

``open_agi`` composes the two gates that used to be stamped by hand in every
handler:

- **Authorization** — resolve the target run (explicit ``agi_id`` > a genome
  source supplied in this chat > the session's active run) and confirm it is
  approved for this session. A supplied source grants approval, mirroring the
  old ``_approve_supplied_dna_source``.
- **Readiness** — hand back an :class:`ActiveGenomeIndexReader` (the data-access door from
  ``active_genome_index.reader``) only after the readiness gate for the
  requested data class has passed. ``variants_ready`` is admitted; the lifecycle
  exceptions (needs-reparse / schema-too-new) propagate to
  ``call_operation`` which maps them to structured envelopes.

Lives in the operations layer (not ``runtime/context``) so it can raise
``OperationError`` directly without a ``runtime -> operations`` import cycle —
handlers, which already raise ``OperationError``, are the only callers. The pure
data door stays in ``active_genome_index`` so that package keeps no runtime
dependency.

``reference_pending`` is **not** stamped here. The dispatch chokepoint
(``call_operation``) stamps it once, driven by the operation's ``agi_need``
metadata, so no handler has to remember to.
"""

from __future__ import annotations

from pathlib import Path

from ...active_genome_index.active_genome_index import (
    ActiveGenomeIndexNeed,
    ActiveGenomeIndexReader,
    default_active_genome_index_path,
    open_reader,
)
from ...active_genome_index._agi_readiness import reference_pending as _reference_pending
from ...runtime import context as runtime_context
from .errors import JsonObject, OperationError

_SOURCE_KEYS = ("source", "vcf")


def _supplied_source(params: JsonObject) -> str | None:
    for key in _SOURCE_KEYS:
        value = params.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _approval_error(action: str) -> OperationError:
    return OperationError(
        "active_genome_index_approval_required",
        (
            f"Explicit user approval is required before {action}. After the user approves "
            "Active Genome Index access for this chat, call active_genome_index.approve_access."
        ),
    )


def _clean_build(value: object) -> str | None:
    build = str(value or "").strip()
    return build if build and build != "auto" else None


def _index_path_for_run(run: JsonObject, params: JsonObject) -> Path | None:
    explicit = params.get("active_genome_index_path")
    if explicit not in (None, ""):
        return Path(str(explicit))
    stored = run.get("active_genome_index_path")
    if stored:
        return Path(str(stored))
    source = run.get("vcf") or run.get("source")
    if source:
        return default_active_genome_index_path(str(source))
    return None


def open_agi(
    *,
    need: ActiveGenomeIndexNeed,
    action: str,
    params: JsonObject | None = None,
    agi_id: str | None = None,
    optional: bool = False,
) -> ActiveGenomeIndexReader | None:
    """Resolve, authorize, and readiness-gate the target AGI, returning an
    :class:`ActiveGenomeIndexReader` bound to it.

    ``need`` selects the readiness gate and (downstream, via ``agi_need``)
    whether the result is stamped ``reference_pending``. ``action`` is the human
    phrase used in the approval error. ``agi_id`` targets a specific named run.
    ``optional=True`` returns ``None`` instead of raising when no approved AGI is
    available — for operations whose AGI use is optional (public-only fallback).
    """
    params = params or {}
    named = agi_id or params.get("agi_id")

    # A genome source supplied in this chat is approval to read it this session.
    source = _supplied_source(params)
    if source is not None and not named:
        runtime_context.approve_agi_access(
            source=source, reason="User supplied a genome source path in this session."
        )

    if named:
        run = runtime_context.find_agi(str(named))
        if not isinstance(run, dict) or not runtime_context.agi_access_approved(run):
            if optional:
                return None
            raise _approval_error(action)
    else:
        run = runtime_context.active_accessible_run()
        if not isinstance(run, dict):
            if optional:
                return None
            if runtime_context.active_run() is not None:
                # An AGI is selected but not approved for this session.
                raise _approval_error(action)
            raise OperationError(
                "missing_context",
                (
                    f"No Active Genome Index is selected for this session. Provide a genome "
                    f"source path or select one with genomi.parse_source before {action}."
                ),
            )

    path = _index_path_for_run(run, params)
    if path is None:
        if optional:
            return None
        raise OperationError(
            "missing_context",
            f"The selected Active Genome Index has no index path; re-run genomi.parse_source before {action}.",
        )

    return open_reader(
        path,
        need=need,
        vcf_path=run.get("vcf") or run.get("source"),
        genome_build=_clean_build(run.get("genome_build")),
    )


def require_session_access(action: str) -> None:
    """Session-level personal-access gate (no specific run).

    For operations that read a personal *artifact* not tied to one resolved AGI
    — e.g. a ClinVar ``matches`` file — where ``open_agi`` (which resolves and
    authorizes a specific run) does not fit. Raises approval_required unless the
    session has approved Active Genome Index access."""
    if runtime_context.agi_access_approved():
        return
    raise _approval_error(action)


def _resolved_index_path(params: JsonObject | None, *, agi_id: str | None = None) -> Path | None:
    """Resolve the AGI index path the same way :func:`open_agi` would, without
    authorizing or granting — used by read-only callers (the chokepoint). By the
    time this runs the handler has already authorized, so an unapproved active
    run cannot reach here."""
    params = params or {}
    explicit = params.get("active_genome_index_path")
    if explicit not in (None, ""):
        return Path(str(explicit))
    named = agi_id or params.get("agi_id")
    if named:
        run = runtime_context.find_agi(str(named))
    else:
        run = runtime_context.active_run()
    if isinstance(run, dict):
        path = _index_path_for_run(run, params)
        if path is not None:
            return path
    source = _supplied_source(params)
    if source is not None:
        return default_active_genome_index_path(source)
    return None


def reference_pending_for_call(params: JsonObject | None, *, agi_id: str | None = None) -> bool:
    """Whether this call's AGI is ``variants_ready`` with its reference-block
    tail still appending. The dispatch chokepoint uses this to stamp a
    reference-dependent result ``reference_pending`` once, in one place."""
    try:
        path = _resolved_index_path(params, agi_id=agi_id)
        if path is None:
            return False
        return _reference_pending(path)
    except Exception:
        return False
