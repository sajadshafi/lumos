"""Workflow engine behaviour: progression, loops, retries, and terminal states.

These are the tests that matter most. The engine is where a mistake costs real
tokens and real time, so each branch of the state machine is exercised against
persisted state rather than a mock.
"""

from __future__ import annotations

import unittest

from ai_loom.models import Action, StageStatus, WorkflowStatus
from support import OrchestratorTestCase, report  # noqa: E402


class LinearProgressionTests(OrchestratorTestCase):
    def test_first_directive_is_the_first_stage(self):
        engine = self.make_engine()
        directive = engine.next_directive()
        self.assertEqual(directive.action, Action.INVOKE_SKILL.value)
        self.assertEqual(directive.skill, "feature-planner")
        self.assertEqual(directive.attempt, 1)

    def test_stages_advance_in_definition_order(self):
        engine = self.make_engine()
        expected = ["coding", "testing", "reviewer", "post-feature-implementation"]
        for stage_key, following in zip(
            ["feature-planner", "coding", "testing", "reviewer"], expected
        ):
            directive = self.run_stage(engine, stage_key, report(next_skill=following))
            self.assertEqual(directive.skill, following, f"after {stage_key}")

    def test_full_run_completes(self):
        engine = self.make_engine()
        for key in ["feature-planner", "coding", "testing", "reviewer", "post-feature-implementation"]:
            directive = self.run_stage(engine, key, report(next_skill="None — done"))
        self.assertEqual(directive.action, Action.COMPLETE.value)
        self.assertEqual(engine.state.status, WorkflowStatus.COMPLETED.value)
        self.assertTrue(
            all(s.status == StageStatus.COMPLETED.value for s in engine.state.stages.values())
        )

    def test_skill_recommendation_does_not_override_the_workflow(self):
        # §3 of the contract: Next Skill is advisory. The definition dispatches.
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", report(next_skill="None"))
        directive = engine.next_directive()
        self.assertEqual(directive.skill, "coding")


class RemediationLoopTests(OrchestratorTestCase):
    def test_reviewer_findings_queue_the_fixer_then_return_to_reviewer(self):
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())

        directive = self.run_stage(engine, "reviewer", report(next_skill="fixer — 2 findings"))
        self.assertEqual(directive.skill, "fixer")
        self.assertEqual(directive.stage_key, "fixer@reviewer")
        self.assertEqual(engine.state.pending_queue[:2], ["fixer@reviewer", "reviewer"])

        directive = self.run_stage(engine, "fixer@reviewer", report(next_skill="reviewer"))
        self.assertEqual(directive.skill, "reviewer")
        self.assertEqual(engine.state.require_stage("reviewer").status, StageStatus.PENDING.value)

    def test_loop_converges_and_the_run_finishes(self):
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())

        self.run_stage(engine, "reviewer", report(next_skill="fixer — 1 finding"))
        self.run_stage(engine, "fixer@reviewer", report(next_skill="reviewer"))
        directive = self.run_stage(engine, "reviewer", report(next_skill="None — approved"))

        self.assertEqual(directive.skill, "post-feature-implementation")
        self.assertEqual(engine.state.require_stage("reviewer").remediation_cycles, 1)

    def test_non_converging_loop_escalates_at_the_configured_ceiling(self):
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())

        # max_cycles is 3; the fourth request to fix is the escalation.
        for _ in range(3):
            self.run_stage(engine, "reviewer", report(next_skill="fixer — still broken"))
            self.run_stage(engine, "fixer@reviewer", report(next_skill="reviewer"))

        directive = self.run_stage(engine, "reviewer", report(next_skill="fixer — still broken"))

        self.assertEqual(directive.action, Action.ABORT.value)
        self.assertEqual(engine.state.status, WorkflowStatus.ESCALATED.value)
        self.assertEqual(engine.state.require_stage("reviewer").status, StageStatus.ESCALATED.value)
        self.assertTrue(any("without convergence" in e["message"] for e in engine.state.errors))

    def test_remediation_stage_carries_its_origin(self):
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())
        self.run_stage(engine, "reviewer", report(next_skill="fixer"))
        self.assertEqual(engine.state.require_stage("fixer@reviewer").returns_to, "reviewer")

    def test_remediation_stage_is_ordered_next_to_its_origin(self):
        # `order` drives every rendered view; appending would report the fixer as
        # having run after the PR stage.
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())
        self.run_stage(engine, "reviewer", report(next_skill="fixer"))
        self.assertEqual(
            engine.state.order,
            ["feature-planner", "coding", "testing", "reviewer", "fixer@reviewer",
             "post-feature-implementation"],
        )

    def test_unmodelled_routing_continues_linearly_and_records_it(self):
        engine = self.make_engine()
        # `testing` has no remediation configured, so routing to fixer is noted,
        # not obeyed — the engine does not invent workflow edges.
        self.run_stage(engine, "feature-planner", report())
        self.run_stage(engine, "coding", report())
        directive = self.run_stage(engine, "testing", report(next_skill="fixer — coverage gap"))
        self.assertEqual(directive.skill, "reviewer")
        self.assertTrue(any("no remediation" in e["message"] for e in engine.state.errors))
        self.assertTrue(all(e["recoverable"] for e in engine.state.errors))


class RetryTests(OrchestratorTestCase):
    def test_malformed_report_retries_the_same_stage(self):
        engine = self.make_engine()
        directive = self.run_stage(engine, "feature-planner", "this is not a report")
        self.assertEqual(directive.skill, "feature-planner")
        self.assertEqual(directive.attempt, 2)
        self.assertEqual(engine.state.require_stage("feature-planner").attempt_count, 1)

    def test_exhausting_attempts_fails_the_run(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", "garbage")
        directive = self.run_stage(engine, "feature-planner", "garbage again")

        self.assertEqual(directive.action, Action.ABORT.value)
        self.assertEqual(engine.state.status, WorkflowStatus.FAILED.value)
        self.assertEqual(engine.state.require_stage("feature-planner").status, StageStatus.FAILED.value)
        self.assertTrue(any("exhausted 2 of 2 attempts" in e["message"] for e in engine.state.errors))

    def test_retry_then_success_continues_the_run(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", "garbage")
        directive = self.run_stage(engine, "feature-planner", report(next_skill="coding"))
        self.assertEqual(directive.skill, "coding")
        self.assertEqual(engine.state.require_stage("feature-planner").attempt_count, 2)

    def test_retry_context_quotes_the_previous_failure(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", "garbage")
        stage = engine.state.require_stage("feature-planner")
        request = self.runner.build_request(
            engine.state, engine.definition_for("feature-planner"), stage, "constraints"
        )
        self.assertIn("previous attempt", request.context.lower())
        self.assertIn("does not conform", request.context)

    def test_attempt_history_is_preserved_across_retries(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", "garbage")
        self.run_stage(engine, "feature-planner", report())
        attempts = engine.state.require_stage("feature-planner").attempts
        self.assertEqual([a.number for a in attempts], [1, 2])
        self.assertEqual(attempts[0].verdict, "failed")
        self.assertEqual(attempts[1].verdict, "success")


class TerminalStateTests(OrchestratorTestCase):
    def test_blocked_report_halts_the_chain(self):
        engine = self.make_engine()
        directive = self.run_stage(
            engine, "feature-planner", report(next_skill="None — blocked, need the fee schedule")
        )
        self.assertEqual(directive.action, Action.ABORT.value)
        self.assertEqual(engine.state.status, WorkflowStatus.BLOCKED.value)
        self.assertEqual(engine.state.pending_queue, [])

    def test_escalation_halts_the_chain(self):
        engine = self.make_engine()
        directive = self.run_stage(engine, "feature-planner", report(next_skill="None — escalate to a human"))
        self.assertEqual(engine.state.status, WorkflowStatus.ESCALATED.value)
        self.assertEqual(directive.action, Action.ABORT.value)

    def test_cancel_is_terminal(self):
        engine = self.make_engine()
        directive = engine.cancel("requirements changed")
        self.assertEqual(directive.action, Action.ABORT.value)
        self.assertEqual(engine.state.status, WorkflowStatus.CANCELLED.value)

    def test_directive_on_a_finished_run_does_not_restart_it(self):
        engine = self.make_engine()
        engine.cancel("done")
        self.assertEqual(engine.next_directive().action, Action.ABORT.value)

    def test_runaway_guard_aborts(self):
        engine = self.make_engine()
        engine.definition = engine.definition.__class__(
            name=engine.definition.name,
            stages=engine.definition.stages,
            max_total_stages=len(engine.definition.stages),
        )
        for _ in range(len(engine.definition.stages)):
            self.manager.begin_attempt(engine.state, "feature-planner")
        directive = engine.next_directive()
        self.assertEqual(directive.action, Action.ABORT.value)
        self.assertIn("runaway guard", directive.reason)


class ControlTests(OrchestratorTestCase):
    workflow_text = """
version: 1
name: default
stages:
  - skill: coding
    retry:
      max_attempts: 2
  - skill: reviewer
    requires_approval: true
    retry:
      max_attempts: 2
"""

    def test_approval_gate_pauses_the_run(self):
        engine = self.make_engine()
        self.run_stage(engine, "coding", report())
        directive = engine.next_directive()
        self.assertEqual(directive.action, Action.AWAIT_APPROVAL.value)
        self.assertEqual(directive.stage_key, "reviewer")

    def test_approval_releases_the_gate(self):
        engine = self.make_engine()
        self.run_stage(engine, "coding", report())
        directive = engine.approve("reviewer")
        self.assertEqual(directive.action, Action.INVOKE_SKILL.value)
        self.assertEqual(directive.skill, "reviewer")

    def test_skip_advances_past_a_stage(self):
        engine = self.make_engine()
        directive = engine.skip("coding", "already implemented by hand")
        self.assertEqual(engine.state.require_stage("coding").status, StageStatus.SKIPPED.value)
        self.assertEqual(directive.stage_key, "reviewer")


if __name__ == "__main__":
    unittest.main()
