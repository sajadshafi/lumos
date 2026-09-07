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

from importlib.metadata import entry_points

from ..errors import ConfigError
from .azure_devops import AzureDevOpsTracker
from .base import TrackerAdapter, TrackerCapabilities, TrackerTransport
from .github import GitHubTracker
from .gitlab import GitLabTracker
from .jira import JiraTracker
from .local import LocalTracker
from .transports import create_transport

__all__ = [
    "AzureDevOpsTracker", "GitHubTracker", "GitLabTracker", "JiraTracker", "LocalTracker",
    "TrackerAdapter", "TrackerCapabilities", "TrackerTransport", "create_adapter",
    "get_adapter", "list_adapters", "register_adapter",
]

# A tiny name -> factory registry so a runtime can select an adapter by string
# (e.g. from a config file or a --tracker flag) without importing it directly.
_REGISTRY: dict[str, type[TrackerAdapter]] = {}
_ENTRY_POINTS_LOADED = False


def register_adapter(name: str, adapter_cls: type[TrackerAdapter]) -> None:
    """Register an adapter class under a short name."""
    _REGISTRY[name] = adapter_cls


def get_adapter(name: str) -> type[TrackerAdapter]:
    """Look up a registered adapter class by name."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    _load_entry_point_adapters()
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"unknown tracker adapter {name!r}; registered: {available}") from None


def _load_entry_point_adapters() -> None:
    """Discover third-party adapters from the ``lumos.trackers`` group once."""
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    _ENTRY_POINTS_LOADED = True
    discovered = entry_points()
    candidates = (
        discovered.select(group="lumos.trackers")
        if hasattr(discovered, "select")
        else discovered.get("lumos.trackers", [])
    )
    for entry_point in candidates:
        try:
            adapter_cls = entry_point.load()
        except Exception as exc:
            raise ConfigError(f"could not load tracker entry point {entry_point.name!r}: {exc}") from exc
        if not isinstance(adapter_cls, type) or not issubclass(adapter_cls, TrackerAdapter):
            raise ConfigError(f"tracker entry point {entry_point.name!r} must load a TrackerAdapter subclass")
        register_adapter(entry_point.name, adapter_cls)


def list_adapters() -> dict[str, type[TrackerAdapter]]:
    """Return a copy of the registry for diagnostics and extension discovery."""
    _load_entry_point_adapters()
    return dict(_REGISTRY)


def create_adapter(
    name: str,
    *,
    transport: str = "mcp",
    options: dict[str, str] | None = None,
    transport_instance: TrackerTransport | None = None,
) -> TrackerAdapter:
    """Construct a configured adapter while preserving the local zero-config path."""
    try:
        adapter_cls = get_adapter(name)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc
    if name == "local":
        return adapter_cls(options=options)
    return adapter_cls(options=options, transport=transport_instance or create_transport(transport))


register_adapter("local", LocalTracker)
register_adapter("github", GitHubTracker)
register_adapter("jira", JiraTracker)
register_adapter("gitlab", GitLabTracker)
register_adapter("azure-devops", AzureDevOpsTracker)
