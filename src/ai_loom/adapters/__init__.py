"""Tracker adapters: the seam between the runtime-neutral engine and a specific
issue tracker (Azure DevOps, GitHub, Jira, or none at all).

The core engine never talks to a tracker. It receives a :class:`WorkUnit` and
emits markdown; *how* that work unit is fetched and where the final summary is
posted is an adapter's concern. This keeps Azure DevOps — or any other vendor —
out of the engine entirely.

The default is :class:`~ai_loom.adapters.local.LocalTracker`, which needs no
external system: the work unit is supplied directly on the command line. Real
integrations subclass :class:`~ai_loom.adapters.base.TrackerAdapter`.
"""

from __future__ import annotations

from .base import TrackerAdapter
from .local import LocalTracker

__all__ = ["TrackerAdapter", "LocalTracker", "get_adapter", "register_adapter"]

# A tiny name -> factory registry so a runtime can select an adapter by string
# (e.g. from a config file or a --tracker flag) without importing it directly.
_REGISTRY: dict[str, type[TrackerAdapter]] = {}


def register_adapter(name: str, adapter_cls: type[TrackerAdapter]) -> None:
    """Register an adapter class under a short name."""
    _REGISTRY[name] = adapter_cls


def get_adapter(name: str) -> type[TrackerAdapter]:
    """Look up a registered adapter class by name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"unknown tracker adapter {name!r}; registered: {available}") from None


register_adapter("local", LocalTracker)
