"""The default, dependency-free tracker.

There is no external system. The work unit is whatever the caller passed on the
command line, and "posting a comment" just returns the text for the caller to do
with as it likes. This is what makes the orchestrator usable with no integration
at all — a plain local run driven entirely by CLI flags.
"""

from __future__ import annotations

from ..models import WorkUnit
from .base import TrackerAdapter


class LocalTracker(TrackerAdapter):
    """A tracker that stores nothing and calls out to nothing."""

    name = "local"

    def fetch(self, work_id: str) -> WorkUnit:
        return WorkUnit(id=work_id)
