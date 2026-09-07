"""Jira Cloud tracker adapter."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..errors import ConfigError
from ..models import WorkUnit
from .content import adf_to_text
from .remote import RemoteTracker


class JiraTracker(RemoteTracker):
    name = "jira"

    def normalise_id(self, work_id: str) -> str | None:
        token = str(work_id).strip()
        if token.startswith(("http://", "https://")):
            parts = urlparse(token).path.rstrip("/").split("/")
            token = parts[-1]
        token = token.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", token):
            raise ConfigError(f"invalid Jira issue reference {work_id!r}")
        return token

    def fetch(self, work_id: str) -> WorkUnit:
        key = self.normalise_id(work_id) or work_id
        raw = self._fetch_raw(key)
        fields = raw.get("fields", {}) or {}
        field_name = self.options.get("acceptance_criteria_field", "")
        acceptance = adf_to_text(fields.get(field_name)) if field_name else ""
        site = str(self.options.get("site", "")).rstrip("/")

        def named(name: str) -> str:
            value = fields.get(name) or {}
            return str(value.get("name", "")) if isinstance(value, dict) else str(value or "")

        return WorkUnit(
            id=str(raw.get("key") or key),
            title=str(fields.get("summary") or ""),
            type=named("issuetype"),
            state=named("status"),
            description=adf_to_text(fields.get("description")).strip(),
            url=f"{site}/browse/{raw.get('key', key)}" if site else str(raw.get("self") or ""),
            acceptance_criteria=acceptance.strip(),
            metadata={
                "provider": "jira",
                "labels": ", ".join(map(str, fields.get("labels", []) or [])),
                "components": ", ".join(str(x.get("name", "")) for x in fields.get("components", []) or []),
                "parent": str((fields.get("parent") or {}).get("key", "")),
            },
        )
