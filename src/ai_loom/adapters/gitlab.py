"""GitLab Issues tracker adapter."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..errors import ConfigError
from ..models import WorkUnit
from .content import task_list
from .remote import RemoteTracker


class GitLabTracker(RemoteTracker):
    name = "gitlab"

    def _reference(self, value: str) -> tuple[str, str | None]:
        token = str(value).strip()
        if token.startswith(("http://", "https://")):
            parsed = urlparse(token)
            before, marker, after = parsed.path.strip("/").partition("/-/issues/")
            if marker and after.isdigit():
                self.options.setdefault("host", f"{parsed.scheme}://{parsed.netloc}")
                return after, before
        match = re.fullmatch(r"(?:(?P<project>.+)#)?(?:GL[#-]?)?(?P<number>\d+)", token, re.I)
        if not match:
            raise ConfigError(f"invalid GitLab issue reference {value!r}")
        return match.group("number"), match.group("project")

    def normalise_id(self, work_id: str) -> str | None:
        number, project = self._reference(work_id)
        if project:
            self.options["project"] = project
        return f"GL#{number}"

    def fetch(self, work_id: str) -> WorkUnit:
        iid, project = self._reference(work_id)
        if project:
            self.options["project"] = project
        raw = self._fetch_raw(iid)
        description = str(raw.get("description") or "")
        assignees = [str(x.get("username", "")) for x in raw.get("assignees", []) or []]
        milestone = raw.get("milestone") or {}
        return WorkUnit(
            id=f"GL#{raw.get('iid', iid)}", title=str(raw.get("title") or ""), type="issue",
            state=str(raw.get("state") or ""), description=description,
            url=str(raw.get("web_url") or ""), acceptance_criteria=task_list(description),
            metadata={
                "provider": "gitlab", "project": str(self.options.get("project", "")),
                "labels": ", ".join(map(str, raw.get("labels", []) or [])), "assignees": ", ".join(assignees),
                "milestone": str(milestone.get("title", "")), "weight": str(raw.get("weight") or ""),
                "confidential": str(bool(raw.get("confidential", False))).lower(),
            },
        )
