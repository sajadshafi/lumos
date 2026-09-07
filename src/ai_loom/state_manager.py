"""Workflow state persistence.

Sole owner of reading and writing run state. Nothing else in the package touches
the state file — that is what makes "recover an interrupted workflow" a property
of the system rather than a hopeful comment.

Two decisions worth stating:

*Why JSON and not YAML.* The design sketch shows state as YAML, and `status`
renders it that way for humans. But the durable record is JSON: it round-trips
exactly through the standard library, needs no third-party dependency, and cannot
be silently corrupted by the YAML subset the fallback parser supports. Human
readability is a presentation concern, and it is served by a renderer.

*Why atomic writes.* A run can be interrupted at any moment — Ctrl-C, a crashed
session, a killed terminal. Writing in place risks a truncated state file, which
loses the entire run. Write-temp-then-rename is atomic on POSIX, so the file on
disk is always either the previous state or the next one, never a fragment.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import Paths, WorkflowDefinition
from .errors import StateError
from .models import (
    Attempt,
    Stage,
    StageStatus,
    WorkflowState,
    WorkflowStatus,
    WorkItem,
)

SUPPORTED_SCHEMA_VERSION = 1


class StateManager:
    """Create, load, mutate and persist `WorkflowState`."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #

    @staticmethod
    def run_id_for(work_item_id: str) -> str:
        """Normalise any work-unit reference into a filesystem-safe run id.

        Tracker-neutral: `TASK-42`, `task-42`, `#42` and `feature/42` all collapse
        to a stable, case-insensitive id, so resuming a run does not depend on the
        user retyping the reference the same way. A tracker that needs a bespoke
        scheme (e.g. an Azure DevOps `AB-` prefix) normalises the reference in its
        adapter before it reaches the engine.
        """
        token = str(work_item_id).strip().upper()
        token = "".join(ch if ch.isalnum() else "-" for ch in token).strip("-")
        if not token:
            raise StateError(f"cannot derive a run id from {work_item_id!r}")
        return token

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def exists(self, run_id: str) -> bool:
        return self._paths.state_file(run_id).is_file()

    def create(
        self,
        work_item: WorkItem,
        workflow: WorkflowDefinition,
        branch: str = "",
        repository: str = "",
    ) -> WorkflowState:
        """Initialise state for a new run, seeding one pending stage per definition."""
        run_id = self.run_id_for(work_item.id)
        state = WorkflowState(
            run_id=run_id,
            work_item=work_item,
            workflow_name=workflow.name,
            branch=branch,
            repository=repository,
            status=WorkflowStatus.RUNNING.value,
        )
        for definition in workflow.stages:
            state.stages[definition.key] = Stage(
                key=definition.key, skill=definition.worker, worker_type=definition.kind
            )
            state.order.append(definition.key)
        state.pending_queue = list(state.order)
        state.next_step = state.pending_queue[0] if state.pending_queue else None
        self.save(state)
        return state

    def load(self, run_id: str) -> WorkflowState:
        path = self._paths.state_file(run_id)
        if not path.is_file():
            raise StateError(f"no state for run {run_id!r} at {path}. Start it with: lumos start {run_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"state file {path} is corrupt: {exc}") from exc

        schema = data.get("schema_version", 1)
        if schema > SUPPORTED_SCHEMA_VERSION:
            raise StateError(
                f"state file {path} uses schema v{schema}, but this orchestrator supports "
                f"v{SUPPORTED_SCHEMA_VERSION}. Upgrade the orchestrator or start a fresh run."
            )
        return WorkflowState.from_dict(data)

    def load_or_create(
        self,
        work_item: WorkItem,
        workflow: WorkflowDefinition,
        branch: str = "",
        repository: str = "",
    ) -> tuple[WorkflowState, bool]:
        """Resume if a run exists, otherwise start one. Returns (state, resumed)."""
        run_id = self.run_id_for(work_item.id)
        if self.exists(run_id):
            state = self.load(run_id)
            # Refresh volatile context that may legitimately change between sessions.
            if branch:
                state.branch = branch
            if work_item.title and not state.work_item.title:
                state.work_item = work_item
            return state, True
        return self.create(work_item, workflow, branch=branch, repository=repository), False

    def save(self, state: WorkflowState) -> Path:
        """Persist atomically: temp file in the same directory, then rename."""
        state.updated_at = time.time()
        path = self._paths.state_file(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)

        temp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return path

    def delete(self, run_id: str) -> bool:
        path = self._paths.state_file(run_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list_runs(self) -> list[str]:
        if not self._paths.state_dir.is_dir():
            return []
        return sorted(p.name[: -len(".state.json")] for p in self._paths.state_dir.glob("*.state.json"))

    # ------------------------------------------------------------------ #
    # Mutation — the only sanctioned way to change a stage
    # ------------------------------------------------------------------ #

    def begin_attempt(self, state: WorkflowState, stage_key: str) -> Attempt:
        stage = state.require_stage(stage_key)
        attempt = Attempt(number=stage.attempt_count + 1, started_at=time.time())
        stage.attempts.append(attempt)
        stage.status = StageStatus.RUNNING.value
        state.current_step = stage_key
        state.status = WorkflowStatus.RUNNING.value
        self.save(state)
        return attempt

    def complete_attempt(
        self,
        state: WorkflowState,
        stage_key: str,
        verdict: str,
        status: StageStatus,
        summary: str = "",
        report_path: str | None = None,
        error: str | None = None,
    ) -> Attempt:
        stage = state.require_stage(stage_key)
        attempt = stage.current_attempt
        if attempt is None:
            # Tolerate a record without a matching begin — a resumed session may
            # have lost the in-memory attempt while the work actually happened.
            attempt = Attempt(number=stage.attempt_count + 1, started_at=time.time())
            stage.attempts.append(attempt)
        attempt.ended_at = time.time()
        attempt.verdict = verdict
        attempt.report_path = report_path
        attempt.error = error
        attempt.summary = summary
        stage.status = status.value
        if summary:
            stage.summary = summary
        self.save(state)
        return attempt

    def add_stage(
        self,
        state: WorkflowState,
        key: str,
        skill: str,
        worker_type: str = "skill",
        returns_to: str | None = None,
    ) -> Stage:
        """Register a dynamically created stage, such as a remediation run."""
        stage = state.stages.get(key)
        if stage is None:
            stage = Stage(key=key, skill=skill, worker_type=worker_type, returns_to=returns_to)
            state.stages[key] = stage
            # `order` drives every rendered view, so a remediation stage belongs
            # immediately after the stage that spawned it. Appending would show
            # the fixer running after the PR stage, which is not what happened.
            if returns_to and returns_to in state.order:
                state.order.insert(state.order.index(returns_to) + 1, key)
            else:
                state.order.append(key)
        else:
            # A repeat remediation cycle reuses the stage and gets a fresh budget.
            stage.status = StageStatus.PENDING.value
            stage.worker_type = worker_type
            stage.returns_to = returns_to
        return stage

    def reset_stage(self, state: WorkflowState, key: str) -> Stage:
        """Return a completed stage to pending so it can run again.

        Used when a remediation loop sends control back to the reviewer that
        raised the findings. Attempt history is preserved deliberately.
        """
        stage = state.require_stage(key)
        stage.status = StageStatus.PENDING.value
        return stage

    def set_status(self, state: WorkflowState, status: WorkflowStatus, save: bool = True) -> None:
        state.status = status.value
        if save:
            self.save(state)
