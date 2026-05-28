from __future__ import annotations

import sys
import types

from . import store as _store


class _EvidenceModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        setattr(_store, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _EvidenceModule
__all__ = [name for name in dir(_store) if not name.startswith("__")]
globals().update({name: getattr(_store, name) for name in __all__})
