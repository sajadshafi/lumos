"""Azure DevOps adapter — a documented stub, not a live client.

This shows the shape a real tracker integration takes and keeps every
vendor-specific detail (the ``AB-`` run-id scheme, the area/iteration paths) out
of the engine. It deliberately does not import an HTTP client or make network
calls; wiring :meth:`fetch` to the Azure DevOps REST API (or the MCP
``wit_get_work_item`` tool, when driven by an agent) is left to the integrator.

Registering it::

    from ai_loom.adapters import register_adapter
    from ai_loom.adapters.azure_devops import AzureDevOpsTracker
    register_adapter("azure-devops", AzureDevOpsTracker)
"""

from __future__ import annotations

from ..models import WorkUnit
from .base import TrackerAdapter


class AzureDevOpsTracker(TrackerAdapter):
    """Maps Azure DevOps work items onto the neutral :class:`WorkUnit`."""

    name = "azure-devops"

    def normalise_id(self, work_id: str) -> str | None:
        """Collapse ``273`` / ``AB#273`` / ``AB-273`` onto a single ``AB-273``."""
        token = str(work_id).strip().upper()
        for prefix in ("AB#", "AB-", "#"):
            if token.startswith(prefix):
                token = token[len(prefix) :]
                break
        token = "".join(ch if ch.isalnum() else "-" for ch in token).strip("-")
        return f"AB-{token}" if token else None

    def fetch(self, work_id: str) -> WorkUnit:
        """Fetch a work item and map its ADO-specific fields into ``metadata``.

        A live implementation would call the REST API here. This stub only shows
        the mapping: ``area_path`` and ``iteration_path`` are not core fields, so
        they live in ``metadata`` where skills can still read them.
        """
        raw = self._get_work_item(work_id)  # integrator supplies this
        return WorkUnit(
            id=self.normalise_id(work_id) or work_id,
            title=raw.get("System.Title", ""),
            type=raw.get("System.WorkItemType", ""),
            state=raw.get("System.State", ""),
            description=raw.get("System.Description", ""),
            url=raw.get("url", ""),
            acceptance_criteria=raw.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""),
            metadata={
                key: raw[field]
                for key, field in (
                    ("area_path", "System.AreaPath"),
                    ("iteration_path", "System.IterationPath"),
                )
                if raw.get(field)
            },
        )

    def _get_work_item(self, work_id: str) -> dict[str, str]:
        raise NotImplementedError(
            "AzureDevOpsTracker is a stub: wire this to the Azure DevOps REST API "
            "or the wit_get_work_item MCP tool to fetch real work items."
        )
