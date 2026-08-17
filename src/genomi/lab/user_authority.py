"""Serialize GenomiLab requests against the exact current Genomi user."""

from __future__ import annotations

import functools
import threading
from contextlib import nullcontext
from typing import Any, Callable

from ..runtime.context.storage import context_authority_lock
from .service_errors import LabError


_UNGUARDED_PUBLIC_METHODS = frozenset(
    {
        # Lifecycle/configuration methods do not read or mutate patient domain
        # state.  ``close`` performs revocation and must remain usable after the
        # selected user or underlying Genomi session disappears.
        "close",
        "configure_evidence_gateway",
        "evidence_capability_manifest",
        "agent_session_manifest",
    }
)


class CurrentUserAuthorityMixin:
    """Guard every public application operation with one user authority epoch.

    The HTTP server is threaded, and tests and host integrations also call the
    service directly.  Intercepting public methods here gives both paths the
    same boundary.  Nested public calls share the outer guard.
    """

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        if (
            name.startswith("_")
            or name in _UNGUARDED_PUBLIC_METHODS
            or not callable(value)
        ):
            return value
        guard = super().__getattribute__("_run_current_user_operation")

        @functools.wraps(value)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            return guard(value, *args, **kwargs)

        return guarded

    def _initialize_current_user_authority(self) -> None:
        self._current_user_authority_local = threading.local()
        self._current_user_authority_epoch = 0

    def _run_current_user_operation(
        self, bound_method: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        local = getattr(self, "_current_user_authority_local", None)
        if local is None:
            raise RuntimeError("current-user authority is not initialized")
        if int(getattr(local, "depth", 0)) > 0:
            return bound_method(*args, **kwargs)

        mismatch = False
        with self._operation_lock:
            local.depth = 1
            try:
                # This lock is re-entrant in-process and advisory across
                # processes.  Genomi context writers use the same boundary, so
                # a user-selection write cannot linearize midway through a
                # patient request.
                lock_boundary = (
                    context_authority_lock()
                    if self._uses_runtime_context_authority_lock
                    else nullcontext()
                )
                with lock_boundary:
                    context = self._read_current_user_authority_context()
                    expected_user_id = self._context_user_id(context)
                    self._synchronize_bound_user(expected_user_id)
                    expected_epoch = int(self._current_user_authority_epoch)
                    local.expected_user_id = expected_user_id
                    local.expected_epoch = expected_epoch

                    store_boundary = self.store.current_user_authority_guard(
                        lambda: self._require_current_user_authority(
                            expected_user_id, expected_epoch
                        )
                    )
                    try:
                        with store_boundary:
                            result = bound_method(*args, **kwargs)
                            self._require_current_user_authority(
                                expected_user_id, expected_epoch
                            )
                        return result
                    except LabError as exc:
                        mismatch = exc.code == "genomi_user_changed"
                        raise
            finally:
                local.depth = 0
                local.expected_user_id = None
                local.expected_epoch = None
                if mismatch:
                    # Cleanup is deliberately outside the failed store guard;
                    # it revokes the old user's session grants/disclosures and
                    # synchronizes the service to the newly observed identity.
                    self._synchronize_to_current_user_best_effort()

    def _read_current_user_authority_context(self) -> dict[str, Any]:
        return self._safe_call("genomi.describe_context", {})

    @staticmethod
    def _context_user_id(context: dict[str, Any]) -> str | None:
        user_id = str(context.get("active_user_id") or "").strip()
        return user_id or None

    def _synchronize_bound_user(self, user_id: str | None) -> None:
        before = getattr(self, "_bound_user_id", None)
        if user_id is None:
            self._unbind_current_user()
        else:
            self._bind_current_user(user_id)
        after = getattr(self, "_bound_user_id", None)
        if before != after:
            self._current_user_authority_epoch += 1

    def _require_current_user_authority(
        self, expected_user_id: str | None, expected_epoch: int
    ) -> None:
        context = self._read_current_user_authority_context()
        current_user_id = self._context_user_id(context)
        if (
            current_user_id != expected_user_id
            or int(self._current_user_authority_epoch) != int(expected_epoch)
        ):
            raise LabError(
                "genomi_user_changed",
                (
                    "The current Genomi user changed while this request was in "
                    "progress. No in-flight result was returned or committed."
                ),
                http_status=409,
            )

    def _synchronize_to_current_user_best_effort(self) -> None:
        try:
            current = self._read_current_user_authority_context()
            self._synchronize_bound_user(self._context_user_id(current))
        except Exception:
            # The original typed authority failure remains the caller-visible
            # result.  Runtime AGI handles were already invalidated by the
            # authority mismatch or will be revoked on close.
            self._revoke_runtime_access()


__all__ = ["CurrentUserAuthorityMixin"]
