"""Azure DevOps Boards tracker adapter."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..errors import ConfigError
from ..models import WorkUnit
from .content import html_to_text
from .remote import RemoteTracker


class AzureDevOpsTracker(RemoteTracker):
    name = "azure-devops"

    def normalise_id(self, work_id: str) -> str | None:
        token = str(work_id).strip()
        if token.startswith(("http://", "https://")):
            token = urlparse(token).path.rstrip("/").split("/")[-1]
        prefix = str(self.options.get("prefix", "AB")).upper().removesuffix("#")
        token = re.sub(rf"^(?:{re.escape(prefix)}[#-]|AB[#-]|#)", "", token, flags=re.I)
        if not token.isdigit():
            raise ConfigError(f"invalid Azure DevOps work-item reference {work_id!r}")
        return f"{prefix}#{token}"

    def fetch(self, work_id: str) -> WorkUnit:
        normalized = self.normalise_id(work_id) or work_id
        number = normalized.partition("#")[2]
        raw = self._fetch_raw(number)
        fields = raw.get("fields", {}) or {}
        relations = raw.get("relations", []) or []
        assigned = fields.get("System.AssignedTo") or {}
        return WorkUnit(
            id=f"{normalized.partition('#')[0]}#{raw.get('id', number)}",
            title=str(fields.get("System.Title") or ""),
            type=str(fields.get("System.WorkItemType") or ""),
            state=str(fields.get("System.State") or ""),
            description=html_to_text(fields.get("System.Description")),
            url=str(raw.get("_links", {}).get("html", {}).get("href") or raw.get("url") or ""),
            acceptance_criteria=html_to_text(fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")),
            metadata={
                "provider": "azure-devops",
                "area_path": str(fields.get("System.AreaPath") or ""),
                "iteration_path": str(fields.get("System.IterationPath") or ""),
                "tags": str(fields.get("System.Tags") or ""),
                "assigned_to": str(assigned.get("displayName", "")) if isinstance(assigned, dict) else str(assigned),
                "revision": str(raw.get("rev") or ""),
                "relations": ", ".join(str(item.get("url", "")) for item in relations if isinstance(item, dict)),
            },
        )
