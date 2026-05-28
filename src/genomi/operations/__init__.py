from __future__ import annotations

import sys
import types

from . import registry as _registry


class _OperationsModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        setattr(_registry, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _OperationsModule
__all__ = [name for name in dir(_registry) if not name.startswith("__")]
globals().update({name: getattr(_registry, name) for name in __all__})
