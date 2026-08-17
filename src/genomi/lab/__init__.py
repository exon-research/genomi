"""GenomiLab's local patient research workspace.

Imports stay lazy so the operation catalog can read this package's tool
fragment while the operation registry itself is still initializing.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "GenomiLabService":
        from .service import GenomiLabService

        return GenomiLabService
    if name == "GenomiLabStore":
        from .store import GenomiLabStore

        return GenomiLabStore
    raise AttributeError(name)


__all__ = ["GenomiLabService", "GenomiLabStore"]
