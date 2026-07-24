"""The tracker adapter contract.

An adapter connects the engine to whatever system tracks work — or to nothing at
all. Every method has a safe no-op default, so a minimal adapter only overrides
what it actually supports. The engine calls these; it never assumes any of them
does more than the local default.
"""

from __future__ import annotations

from ..models import WorkUnit


class TrackerAdapter:
    """Base class for issue-tracker integrations.

    Subclasses typically override :meth:`fetch` (to pull a work unit from an API)
    and, optionally, :meth:`comment` / :meth:`link_pull_request` (to write the run
    summary back). :meth:`normalise_id` lets a tracker impose its own run-id
    scheme; by default the engine's generic normalisation is used.
    """

    #: Short name used in the adapter registry and any ``--tracker`` selection.
    name: str = "base"

    def fetch(self, work_id: str) -> WorkUnit:
        """Return the work unit for ``work_id``.

        The default treats ``work_id`` as the entire work unit — no external
        lookup. Real adapters call their API and populate title/description/etc.
        """
        return WorkUnit(id=work_id)

    def normalise_id(self, work_id: str) -> str | None:
        """Optionally rewrite a raw reference before the engine derives a run id.

        Return ``None`` to accept the engine's generic normalisation. An Azure
        DevOps adapter might return ``f"AB-{n}"`` here so ``273`` and ``AB#273``
        share one run.
        """
        return None

    def comment(self, work_id: str, body: str) -> None:  # noqa: D401 - simple hook
        """Post ``body`` to the tracker. No-op by default."""

    def link_pull_request(self, work_id: str, pr_url: str) -> None:
        """Associate a pull request with the work item. No-op by default."""
