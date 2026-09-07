"""Workflow Engine — decides what happens next. It never does it.

The engine is a pure state machine over (workflow definition, workflow state).
Given a run, `next_directive` answers one question: *what should the orchestrator
do now?* Given a completed invocation, `record` folds the outcome into state and
re-derives the queue.

Determinism is the point. The same state and the same definition always yield the
same directive, which is what makes runs resumable after an interruption and
reproducible when something goes wrong. No clocks, no randomness, no I/O beyond
what the state manager and logger perform on its behalf.

## The queue

`state.pending_queue` holds stage keys still to run, seeded from the workflow
order. Linear progress pops the head. A remediation loop splices work in:

    queue: [reviewer, post-feature-implementation]
    reviewer reports changes requested
    queue: [fixer@reviewer, reviewer, post-feature-implementation]

The remediation stage carries `returns_to="reviewer"`, so the skill that raised
the findings verifies its own objection rather than trusting the fixer's word.
Remediation stages are keyed `fixer@reviewer` so a later `fixer@security` run
cannot collide with it in state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Paths, StageDefinition, WorkflowDefinition
from .logging_ import RunLogger
from .models import (
    Action,
    Directive,
    Stage,
    StageStatus,
    Verdict,
    WorkflowState,
    WorkflowStatus,
)
from .skill_runner import InvocationResult, SkillRunner
from .state_manager import StateManager

REMEDIATION_SEPARATOR = "@"


@dataclass
class Engine:
    """Coordinates definition, state, runner and log into a decision."""

    definition: WorkflowDefinition
    state: WorkflowState
    paths: Paths
    state_manager: StateManager
    runner: SkillRunner
    logger: RunLogger

    # ------------------------------------------------------------------ #
    # Definition lookup
    # ------------------------------------------------------------------ #

    def definition_for(self, stage_key: str) -> StageDefinition:
        """Resolve the definition governing a stage key.

        A remediation stage `fixer@reviewer` has no entry of its own; it inherits
        the retry budget of the origin stage that spawned it, because the fixer's
        budget is really part of that review cycle's budget.
        """
        base, _, origin = stage_key.partition(REMEDIATION_SEPARATOR)
        if origin:
            origin_def = self.definition.stage(origin)
            remediation = origin_def.remediation if origin_def else None
            skill = remediation.skill if remediation else base
            kind = remediation.kind if remediation else "skill"
            retry = origin_def.retry if origin_def else StageDefinition(skill=skill).retry
            return StageDefinition(skill=skill, kind=kind, retry=retry)
        found = self.definition.stage(stage_key)
        if found is None:
            # A stage present in state but absent from the definition — the
            # workflow was edited mid-run. Run it with defaults and let the
            # summary record the drift.
            return StageDefinition(skill=base)
        return found

    # ------------------------------------------------------------------ #
    # Decision
    # ------------------------------------------------------------------ #

    def next_directive(self) -> Directive:
        """Compute the next action without mutating state."""
        state = self.state

        if WorkflowStatus(state.status).is_terminal:
            return Directive(
                action=Action.COMPLETE.value if state.status == WorkflowStatus.COMPLETED.value else Action.ABORT.value,
                run_id=state.run_id,
                reason=f"run already finished with status '{state.status}'",
                workflow_status=state.status,
            )

        executions = sum(len(stage.attempts) for stage in state.stages.values())
        if executions >= self.definition.max_total_stages:
            return Directive(
                action=Action.ABORT.value,
                run_id=state.run_id,
                reason=(
                    f"runaway guard: {executions} stage executions reached the "
                    f"max_total_stages limit of {self.definition.max_total_stages}"
                ),
                workflow_status=WorkflowStatus.FAILED.value,
            )

        if not state.pending_queue:
            return Directive(
                action=Action.COMPLETE.value,
                run_id=state.run_id,
                reason="all stages completed",
                workflow_status=WorkflowStatus.COMPLETED.value,
            )

        stage_key = state.pending_queue[0]
        stage = state.stages.get(stage_key)
        if stage is None:
            stage = self.state_manager.add_stage(state, stage_key, stage_key.split(REMEDIATION_SEPARATOR)[0])

        stage_def = self.definition_for(stage_key)

        if stage_def.requires_approval and stage.status == StageStatus.PENDING.value:
            return Directive(
                action=Action.AWAIT_APPROVAL.value,
                run_id=state.run_id,
                stage_key=stage_key,
                skill=stage_def.skill,
                attempt=stage.attempt_count + 1,
                max_attempts=stage_def.retry.max_attempts,
                reason=(
                    f"stage '{stage_key}' is a manual approval point. "
                    f"Approve with: lumos approve {state.run_id} --stage {stage_key}"
                ),
                workflow_status=WorkflowStatus.AWAITING_APPROVAL.value,
            )

        action = Action.INVOKE_AGENT if stage_def.kind == "agent" else Action.INVOKE_SKILL
        return Directive(
            action=action.value,
            run_id=state.run_id,
            stage_key=stage_key,
            skill=stage_def.skill,
            worker=stage_def.worker,
            worker_type=stage_def.kind,
            attempt=stage.attempt_count + 1,
            max_attempts=stage_def.retry.max_attempts,
            reason=stage_def.description or f"next stage in workflow '{self.definition.name}'",
            workflow_status=WorkflowStatus.RUNNING.value,
        )

    # ------------------------------------------------------------------ #
    # Transition
    # ------------------------------------------------------------------ #

    def record(self, result: InvocationResult) -> Directive:
        """Fold an invocation outcome into state and return the next directive."""
        state = self.state
        stage = state.require_stage(result.stage_key)
        stage_def = self.definition_for(result.stage_key)

        self.runner.apply(stage, result)

        handler = {
            Verdict.SUCCESS: self._on_success,
            Verdict.CHANGES_REQUESTED: self._on_changes_requested,
            Verdict.FAILED: self._on_failure,
            Verdict.BLOCKED: self._on_blocked,
            Verdict.ESCALATE: self._on_escalate,
        }[result.verdict]
        handler(stage, stage_def, result)

        state.current_step = result.stage_key
        state.next_step = state.pending_queue[0] if state.pending_queue else None
        self.state_manager.save(state)

        directive = self.next_directive()
        if directive.action in (Action.COMPLETE.value, Action.ABORT.value):
            self.state_manager.set_status(state, WorkflowStatus(directive.workflow_status))
            self.logger.emit(
                "workflow_finished",
                status=directive.workflow_status,
                detail={"reason": directive.reason},
            )
        return directive

    # ------------------------------------------------------------------ #
    # Verdict handlers
    # ------------------------------------------------------------------ #

    def _pop(self, stage_key: str) -> None:
        queue = self.state.pending_queue
        if queue and queue[0] == stage_key:
            queue.pop(0)

    def _record_routing_divergence(self, stage: Stage) -> None:
        """Note when a skill's recommendation differs from what the workflow dispatches.

        `Next Skill` is advisory (§3) — the definition decides. But a persistent
        gap between the two means the workflow is modelling the wrong pipeline,
        and that is invisible unless it is written down. Recorded as recoverable:
        it is information for the human reading the summary, not a failure.
        """
        recommended = stage.next_skill
        if not recommended:
            return
        upcoming = [k for k in self.state.pending_queue if k != stage.key]
        dispatching = self.state.stages[upcoming[0]].skill if upcoming and upcoming[0] in self.state.stages else None
        if recommended == dispatching:
            return
        origin_def = self.definition.stage(stage.key)
        if origin_def and origin_def.remediation and origin_def.remediation.skill == recommended:
            return  # handled by the remediation path
        self.state.record_error(
            stage.key,
            f"recommended '{recommended}' but workflow '{self.definition.name}' "
            f"dispatches '{dispatching or 'nothing further'}'"
            + (
                f"; no remediation to '{recommended}' is defined for this stage"
                if not (origin_def and origin_def.remediation)
                else ""
            ),
            recoverable=True,
        )

    def _on_success(self, stage: Stage, stage_def: StageDefinition, result: InvocationResult) -> None:
        stage.status = StageStatus.COMPLETED.value
        self._pop(stage.key)
        self._record_routing_divergence(stage)
        self.logger.emit(
            "stage_completed",
            stage=stage.key,
            skill=stage.skill,
            status=StageStatus.COMPLETED.value,
            attempt=result.attempt,
            duration_seconds=stage.current_attempt.duration_seconds if stage.current_attempt else None,
        )
        # A remediation stage hands control back to the skill that objected.
        if stage.returns_to:
            self.state_manager.reset_stage(self.state, stage.returns_to)
            if stage.returns_to not in self.state.pending_queue:
                self.state.pending_queue.insert(0, stage.returns_to)
            self.logger.emit(
                "remediation_returned",
                stage=stage.key,
                skill=stage.skill,
                detail={"returns_to": stage.returns_to},
            )

    def _on_changes_requested(self, stage: Stage, stage_def: StageDefinition, result: InvocationResult) -> None:
        origin_def = self.definition.stage(stage.key)
        remediation = origin_def.remediation if origin_def else None

        if remediation is None:
            # Defensive: reachable only if a caller derives CHANGES_REQUESTED for a
            # stage with no remediation configured. Continue linearly rather than
            # inventing a workflow edge; `_on_success` records the divergence.
            self._on_success(stage, stage_def, result)
            return

        stage.remediation_cycles += 1

        if stage.remediation_cycles > remediation.max_cycles:
            stage.status = StageStatus.ESCALATED.value
            self._pop(stage.key)
            self.state.record_error(
                stage.key,
                f"{stage.remediation_cycles - 1} remediation cycles without convergence "
                f"(limit {remediation.max_cycles}); escalating to a human",
                recoverable=False,
            )
            self.state_manager.set_status(self.state, WorkflowStatus.ESCALATED, save=False)
            self.state.pending_queue.clear()
            self.logger.emit(
                "escalated",
                stage=stage.key,
                skill=stage.skill,
                status=StageStatus.ESCALATED.value,
                detail={"cycles": stage.remediation_cycles - 1, "limit": remediation.max_cycles},
            )
            return

        stage.status = StageStatus.COMPLETED.value
        self._pop(stage.key)

        remediation_key = f"{remediation.skill}{REMEDIATION_SEPARATOR}{stage.key}"
        self.state_manager.add_stage(
            self.state,
            remediation_key,
            remediation.skill,
            worker_type=remediation.kind,
            returns_to=stage.key,
        )
        # Queue both halves of the loop now — fixer, then the origin stage to
        # re-verify. Deferring the re-review until the fixer succeeds would leave
        # `status` showing a queue that omits work the run is committed to.
        self.state_manager.reset_stage(self.state, stage.key)
        self.state.pending_queue.insert(0, stage.key)
        self.state.pending_queue.insert(0, remediation_key)
        self.logger.emit(
            "remediation_queued",
            stage=stage.key,
            skill=stage.skill,
            status=Verdict.CHANGES_REQUESTED.value,
            detail={
                "remediation_stage": remediation_key,
                "cycle": stage.remediation_cycles,
                "max_cycles": remediation.max_cycles,
            },
        )

    def _on_failure(self, stage: Stage, stage_def: StageDefinition, result: InvocationResult) -> None:
        recoverable = not result.violations or stage_def.retry.retry_on_contract_violation
        if stage_def.retry.should_retry(Verdict.FAILED, stage.attempt_count, recoverable):
            stage.status = StageStatus.PENDING.value  # stays at the head of the queue
            self.state.record_error(stage.key, result.error or "stage failed", recoverable=True)
            self.logger.emit(
                "stage_retry",
                stage=stage.key,
                skill=stage.skill,
                status=StageStatus.FAILED.value,
                attempt=result.attempt,
                error=result.error,
                detail={"remaining": stage_def.retry.attempts_remaining(stage.attempt_count)},
            )
            return

        stage.status = StageStatus.FAILED.value
        self._pop(stage.key)
        self.state.record_error(
            stage.key,
            f"exhausted {stage.attempt_count} of {stage_def.retry.max_attempts} attempts: "
            f"{result.error or 'stage failed'}",
            recoverable=False,
        )

        if stage_def.optional:
            self.logger.emit(
                "optional_stage_skipped",
                stage=stage.key,
                skill=stage.skill,
                status=StageStatus.FAILED.value,
                error=result.error,
            )
            return

        self.state_manager.set_status(self.state, WorkflowStatus.FAILED, save=False)
        self.state.pending_queue.clear()
        self.logger.emit(
            "stage_failed",
            stage=stage.key,
            skill=stage.skill,
            status=StageStatus.FAILED.value,
            attempt=result.attempt,
            error=result.error,
        )

    def _on_blocked(self, stage: Stage, stage_def: StageDefinition, result: InvocationResult) -> None:
        stage.status = StageStatus.BLOCKED.value
        self._pop(stage.key)
        self.state.record_error(stage.key, result.summary or "skill reported a blocker", recoverable=False)
        self.state_manager.set_status(self.state, WorkflowStatus.BLOCKED, save=False)
        self.state.pending_queue.clear()
        self.logger.emit(
            "stage_blocked",
            stage=stage.key,
            skill=stage.skill,
            status=StageStatus.BLOCKED.value,
            attempt=result.attempt,
            detail={"summary": result.summary[:400]},
        )

    def _on_escalate(self, stage: Stage, stage_def: StageDefinition, result: InvocationResult) -> None:
        stage.status = StageStatus.ESCALATED.value
        self._pop(stage.key)
        self.state.record_error(stage.key, result.summary or "skill requested escalation", recoverable=False)
        self.state_manager.set_status(self.state, WorkflowStatus.ESCALATED, save=False)
        self.state.pending_queue.clear()
        self.logger.emit(
            "escalated",
            stage=stage.key,
            skill=stage.skill,
            status=StageStatus.ESCALATED.value,
            attempt=result.attempt,
            detail={"summary": result.summary[:400]},
        )

    # ------------------------------------------------------------------ #
    # Control operations
    # ------------------------------------------------------------------ #

    def approve(self, stage_key: str) -> Directive:
        """Clear a manual approval gate."""
        stage_def = self.definition_for(stage_key)
        if not stage_def.requires_approval:
            return self.next_directive()
        # Approval is recorded by promoting the stage out of PENDING; the gate is
        # only checked in that state, so the stage now dispatches normally.
        stage = self.state.require_stage(stage_key)
        stage.status = StageStatus.RUNNING.value
        self.state_manager.set_status(self.state, WorkflowStatus.RUNNING, save=False)
        self.state_manager.save(self.state)
        self.logger.emit("approval_granted", stage=stage_key, skill=stage_def.skill)
        return self.next_directive()

    def cancel(self, reason: str) -> Directive:
        self.state.pending_queue.clear()
        self.state.record_error("<workflow>", f"cancelled: {reason}", recoverable=False)
        self.state_manager.set_status(self.state, WorkflowStatus.CANCELLED)
        self.logger.emit("workflow_cancelled", status=WorkflowStatus.CANCELLED.value, detail={"reason": reason})
        return Directive(
            action=Action.ABORT.value,
            run_id=self.state.run_id,
            reason=f"cancelled: {reason}",
            workflow_status=WorkflowStatus.CANCELLED.value,
        )

    def skip(self, stage_key: str, reason: str) -> Directive:
        stage = self.state.require_stage(stage_key)
        stage.status = StageStatus.SKIPPED.value
        stage.summary = f"Skipped: {reason}"
        self._pop(stage_key)
        self.state_manager.save(self.state)
        self.logger.emit(
            "stage_skipped",
            stage=stage_key,
            skill=stage.skill,
            status=StageStatus.SKIPPED.value,
            detail={"reason": reason},
        )
        return self.next_directive()
