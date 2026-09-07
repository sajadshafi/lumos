"""Shared behavior for remote tracker adapters."""

from __future__ import annotations

import hashlib
from typing import Any

from .base import TrackerAdapter, TrackerCapabilities


class RemoteTracker(TrackerAdapter):
    capabilities = TrackerCapabilities(fetch=True, comment=True, link_pull_request=True, transition=True)

    def _fetch_raw(self, work_id: str) -> dict[str, Any]:
        payload = self._call("fetch", work_id=work_id)
        if not isinstance(payload, dict):
            raise TypeError(f"{self.name} fetch returned {type(payload).__name__}, expected a mapping")
        # MCP connectors commonly wrap the provider object while REST returns it
        # directly. Accept both without leaking connector response shapes into
        # the engine or WorkUnit model.
        for key in ("issue", "work_item"):
            if isinstance(payload.get(key), dict):
                payload = payload[key]
                break
        return payload

    def comment(self, work_id: str, body: str) -> None:
        self._call("comment", work_id=work_id, body=body, idempotency_key=_key(work_id, "comment", body))

    def link_pull_request(self, work_id: str, pr_url: str) -> None:
        self._call(
            "link_pull_request",
            work_id=work_id,
            pr_url=pr_url,
            idempotency_key=_key(work_id, "link_pull_request", pr_url),
        )

    def transition(self, work_id: str, state: str) -> None:
        self._call("transition", work_id=work_id, state=state, idempotency_key=_key(work_id, "transition", state))


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(str(part) for part in parts).encode()).hexdigest()[:24]
