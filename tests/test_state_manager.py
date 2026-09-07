"""State persistence, identity normalisation, and interrupted-run recovery."""

from __future__ import annotations

import json
import unittest

from ai_loom.config import load_workflow
from ai_loom.errors import StateError
from ai_loom.models import StageStatus, WorkflowStatus, WorkItem
from ai_loom.state_manager import StateManager
from support import OrchestratorTestCase, report  # noqa: E402


class RunIdTests(unittest.TestCase):
    def test_equivalent_references_normalise_to_one_run(self):
        # Case, surrounding whitespace and separator style all collapse, so the
        # same reference typed differently resumes the same run.
        ids = {StateManager.run_id_for(v) for v in ("TASK-42", "task-42", "task#42", " TASK-42 ")}
        self.assertEqual(ids, {"TASK-42"})

    def test_run_id_is_tracker_neutral(self):
        # No synthetic prefix is imposed: a bare id is preserved, not rewritten
        # into a tracker-specific shape.
        self.assertEqual(StateManager.run_id_for("42"), "42")
        self.assertEqual(StateManager.run_id_for("#42"), "42")
        self.assertEqual(StateManager.run_id_for("feature/login"), "FEATURE-LOGIN")

    def test_unsafe_characters_are_stripped(self):
        # Path separators and dots collapse to hyphens, so a work item reference
        # can never escape the state directory.
        run_id = StateManager.run_id_for("AB#273/../etc")
        self.assertEqual(run_id, "AB-273----ETC")
        self.assertNotIn("/", run_id)
        self.assertNotIn("..", run_id)

    def test_empty_reference_is_rejected(self):
        with self.assertRaises(StateError):
            StateManager.run_id_for("###")


class PersistenceTests(OrchestratorTestCase):
    def test_create_seeds_every_stage_as_pending(self):
        engine = self.make_engine()
        self.assertEqual(len(engine.state.stages), 5)
        self.assertTrue(all(s.status == StageStatus.PENDING.value for s in engine.state.stages.values()))
        self.assertEqual(engine.state.pending_queue, engine.state.order)

    def test_state_round_trips_through_disk(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", report(deliverables="- the plan"))

        reloaded = self.manager.load(engine.state.run_id)
        stage = reloaded.require_stage("feature-planner")
        self.assertEqual(stage.status, StageStatus.COMPLETED.value)
        self.assertEqual(stage.deliverables, ["the plan"])
        self.assertEqual(reloaded.pending_queue, engine.state.pending_queue)
        self.assertEqual(reloaded.work_item.id, "AB#273")

    def test_interrupted_run_resumes_at_the_same_stage(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", report())
        self.run_stage(engine, "coding", report())

        # Simulate process death: nothing survives but the state file.
        definition = load_workflow(self.paths, "default")
        resumed, was_resumed = self.manager.load_or_create(
            WorkItem(id="AB#273"), definition, branch="feat/273-test"
        )
        self.assertTrue(was_resumed)
        self.assertEqual(resumed.pending_queue[0], "testing")
        self.assertEqual(resumed.require_stage("coding").status, StageStatus.COMPLETED.value)

    def test_resume_preserves_work_item_details(self):
        self.make_engine()  # seeds the run's state on disk
        definition = load_workflow(self.paths, "default")
        resumed, _ = self.manager.load_or_create(WorkItem(id="AB#273"), definition)
        self.assertEqual(resumed.work_item.title, "Test feature")

    def test_missing_state_is_an_actionable_error(self):
        with self.assertRaises(StateError) as ctx:
            self.manager.load("AB-999")
        self.assertIn("lumos start", str(ctx.exception))

    def test_corrupt_state_is_reported_not_swallowed(self):
        engine = self.make_engine()
        self.paths.state_file(engine.state.run_id).write_text("{not json", encoding="utf-8")
        with self.assertRaises(StateError) as ctx:
            self.manager.load(engine.state.run_id)
        self.assertIn("corrupt", str(ctx.exception))

    def test_future_schema_is_refused(self):
        engine = self.make_engine()
        path = self.paths.state_file(engine.state.run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(StateError) as ctx:
            self.manager.load(engine.state.run_id)
        self.assertIn("schema v99", str(ctx.exception))

    def test_save_leaves_no_temporary_files(self):
        engine = self.make_engine()
        self.manager.save(engine.state)
        self.assertEqual(list(self.paths.state_dir.glob("*.tmp")), [])

    def test_list_runs(self):
        self.make_engine(work_item_id="AB#273")
        self.make_engine(work_item_id="AB#274")
        self.assertEqual(self.manager.list_runs(), ["AB-273", "AB-274"])

    def test_attempt_records_duration(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", report())
        attempt = engine.state.require_stage("feature-planner").attempts[0]
        self.assertIsNotNone(attempt.duration_seconds)
        self.assertGreaterEqual(attempt.duration_seconds, 0)

    def test_completing_without_begin_still_records(self):
        # A resumed session may have lost the in-memory attempt while the work
        # actually happened; losing that record would be worse than tolerating it.
        engine = self.make_engine()
        self.manager.complete_attempt(
            engine.state, "coding", verdict="success", status=StageStatus.COMPLETED, summary="ok"
        )
        self.assertEqual(engine.state.require_stage("coding").attempt_count, 1)


class StatusTests(OrchestratorTestCase):
    def test_new_run_is_running(self):
        engine = self.make_engine()
        self.assertEqual(engine.state.status, WorkflowStatus.RUNNING.value)

    def test_terminal_statuses_report_themselves(self):
        self.assertTrue(WorkflowStatus.COMPLETED.is_terminal)
        self.assertTrue(WorkflowStatus.ESCALATED.is_terminal)
        self.assertFalse(WorkflowStatus.RUNNING.is_terminal)
        self.assertFalse(WorkflowStatus.AWAITING_APPROVAL.is_terminal)


if __name__ == "__main__":
    unittest.main()
