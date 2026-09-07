"""GitHub Issues tracker adapter."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..errors import ConfigError
from ..models import WorkUnit
from .content import task_list
from .remote import RemoteTracker


class GitHubTracker(RemoteTracker):
    name = "github"

    def _reference(self, value: str) -> tuple[str, str | None]:
        token = str(value).strip()
        if token.startswith(("http://", "https://")):
            parts = urlparse(token).path.strip("/").split("/")
            if len(parts) >= 4 and parts[2] == "issues" and parts[3].isdigit():
                return parts[3], f"{parts[0]}/{parts[1]}"
        match = re.fullmatch(r"(?:(?P<repo>[\w.-]+/[\w.-]+))?(?:GH)?[#-]?(?P<number>\d+)", token, re.I)
        if not match:
            raise ConfigError(f"invalid GitHub issue reference {value!r}")
        return match.group("number"), match.group("repo")

    def normalise_id(self, work_id: str) -> str | None:
        number, repository = self._reference(work_id)
        if repository:
            self.options["repository"] = repository
        return f"GH#{number}"

    def fetch(self, work_id: str) -> WorkUnit:
        number, repository = self._reference(work_id)
        if repository:
            self.options["repository"] = repository
        raw = self._fetch_raw(number)
        body = str(raw.get("body") or "")
        labels = [
            item.get("name", "") if isinstance(item, dict) else str(item) for item in raw.get("labels", []) or []
        ]
        assignees = [item.get("login", "") for item in raw.get("assignees", []) or [] if isinstance(item, dict)]
        milestone = raw.get("milestone") or {}
        issue_number = raw.get("number") or raw.get("issue_number") or number
        return WorkUnit(
            id=f"GH#{issue_number}", title=str(raw.get("title") or ""), type="issue",
            state=str(raw.get("state") or ""), description=body,
            url=str(raw.get("html_url") or raw.get("display_url") or raw.get("url") or ""),
            acceptance_criteria=task_list(body),
            metadata={
                "provider": "github", "repository": str(self.options.get("repository", "")),
                "labels": ", ".join(filter(None, labels)), "assignees": ", ".join(filter(None, assignees)),
                "milestone": str(milestone.get("title", "")) if isinstance(milestone, dict) else "",
            },
        )
