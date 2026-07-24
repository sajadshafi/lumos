"""Workflow definition loading, YAML fallback parsing, skill discovery, retry policy."""

from __future__ import annotations

import unittest

from ai_loom import yamlcompat
from ai_loom.config import WorkflowDefinition, load_workflow
from ai_loom.errors import ConfigError, SkillNotFoundError
from ai_loom.models import Verdict
from ai_loom.retry import RetryPolicy
from support import OrchestratorTestCase, report  # noqa: E402


class YamlTests(unittest.TestCase):
    def test_parses_the_workflow_shape(self):
        data = yamlcompat.load(
            """
version: 1
name: default
stages:
  - skill: coding
    retry:
      max_attempts: 3
  - skill: reviewer
    remediation:
      skill: fixer
      max_cycles: 2
"""
        )
        self.assertEqual(data["name"], "default")
        self.assertEqual(data["stages"][0]["retry"]["max_attempts"], 3)
        self.assertEqual(data["stages"][1]["remediation"]["skill"], "fixer")

    def test_scalar_types(self):
        data = yamlcompat.load("a: 1\nb: 2.5\nc: true\nd: false\ne: null\nf: text\ng: \"quoted: yes\"\n")
        self.assertEqual(data, {"a": 1, "b": 2.5, "c": True, "d": False, "e": None,
                                "f": "text", "g": "quoted: yes"})

    def test_comments_are_ignored(self):
        data = yamlcompat.load("# leading\nname: x  # trailing\n")
        self.assertEqual(data, {"name": "x"})

    def test_hash_inside_a_value_is_not_a_comment(self):
        self.assertEqual(yamlcompat.load("id: AB#273\n"), {"id": "AB#273"})

    def test_scalar_sequence(self):
        self.assertEqual(yamlcompat.load("workflow:\n  - a\n  - b\n"), {"workflow": ["a", "b"]})

    def test_flow_collections_are_refused_with_a_clear_message(self):
        # Silently returning the raw string would surface as an opaque
        # AttributeError deep in config parsing.
        if yamlcompat.USING_PYYAML:
            self.skipTest("PyYAML is installed and supports flow style")
        with self.assertRaises(yamlcompat.YamlError) as ctx:
            yamlcompat.load("retry: { max_attempts: 2 }\n")
        self.assertIn("flow collections are not supported", str(ctx.exception))

    def test_empty_flow_collections_still_round_trip(self):
        self.assertEqual(yamlcompat.load("a: {}\nb: []\n"), {"a": {}, "b": []})

    def test_round_trip_through_dump(self):
        original = {"name": "x", "stages": [{"skill": "coding", "retry": {"max_attempts": 3}}]}
        self.assertEqual(yamlcompat.load(yamlcompat.dump(original)), original)


class WorkflowDefinitionTests(OrchestratorTestCase):
    def test_shipped_workflows_all_parse(self):
        # Guards the real files in .claude/orchestrator/workflows/, not fixtures.
        from ai_loom.config import Paths

        real = Paths.resolve(self.tmp.parents[0] if False else None)
        for name in ("default", "hotfix", "plan-only", "full-review"):
            with self.subTest(workflow=name):
                definition = load_workflow(real, name)
                self.assertTrue(definition.stages)

    def test_shorthand_string_stage(self):
        definition = WorkflowDefinition.from_dict({"name": "x", "workflow": ["coding", "reviewer"]})
        self.assertEqual([s.skill for s in definition.stages], ["coding", "reviewer"])
        self.assertEqual(definition.stages[0].retry.max_attempts, 2)

    def test_skills_includes_remediation_targets(self):
        definition = load_workflow(self.paths, "default")
        self.assertIn("fixer", definition.skills)

    def test_duplicate_stage_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            WorkflowDefinition.from_dict({"name": "x", "stages": ["coding", "coding"]})
        self.assertIn("duplicate stage", str(ctx.exception))

    def test_empty_stage_list_is_rejected(self):
        with self.assertRaises(ConfigError):
            WorkflowDefinition.from_dict({"name": "x", "stages": []})

    def test_missing_stages_key_is_rejected(self):
        with self.assertRaises(ConfigError):
            WorkflowDefinition.from_dict({"name": "x"})

    def test_remediation_without_skill_is_rejected(self):
        with self.assertRaises(ConfigError):
            WorkflowDefinition.from_dict(
                {"name": "x", "stages": [{"skill": "reviewer", "remediation": {"max_cycles": 2}}]}
            )

    def test_unknown_workflow_lists_the_alternatives(self):
        with self.assertRaises(ConfigError) as ctx:
            load_workflow(self.paths, "nope")
        self.assertIn("Available: default", str(ctx.exception))


class SkillDiscoveryTests(OrchestratorTestCase):
    def test_discovers_invokable_skills(self):
        found = self.runner.discover()
        self.assertTrue(found["coding"].invokable)
        self.assertEqual(found["coding"].description, "Test double for the coding skill.")

    def test_directory_without_skill_md_is_inert_not_hidden(self):
        found = self.runner.discover()
        self.assertIn("security", found)
        self.assertFalse(found["security"].invokable)

    def test_shared_is_not_a_skill(self):
        self.assertNotIn("shared", self.runner.discover())

    def test_invoking_an_inert_skill_explains_why(self):
        with self.assertRaises(SkillNotFoundError) as ctx:
            self.runner.get("security")
        self.assertIn("no SKILL.md", str(ctx.exception))

    def test_missing_skill_lists_available_ones(self):
        with self.assertRaises(SkillNotFoundError) as ctx:
            self.runner.get("nonexistent")
        self.assertIn("coding", str(ctx.exception))

    def test_validate_workflow_reports_every_problem(self):
        problems = self.runner.validate_workflow(("coding", "security", "ghost"))
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("inert" in p for p in problems))
        self.assertTrue(any("no directory" in p for p in problems))

    def test_clean_workflow_validates(self):
        definition = load_workflow(self.paths, "default")
        self.assertEqual(self.runner.validate_workflow(definition.skills), [])


class EnvelopeTests(OrchestratorTestCase):
    def test_envelope_has_all_four_blocks(self):
        engine = self.make_engine()
        stage = engine.state.require_stage("feature-planner")
        request = self.runner.build_request(
            engine.state, engine.definition_for("feature-planner"), stage, "no new dependencies"
        )
        rendered = request.render()
        for block in ("## Objective", "## Context", "## Constraints", "## Previous Outputs"):
            self.assertIn(block, rendered)
        self.assertIn("no new dependencies", rendered)
        self.assertIn("AB#273", rendered)

    def test_first_stage_has_no_previous_outputs(self):
        engine = self.make_engine()
        stage = engine.state.require_stage("feature-planner")
        request = self.runner.build_request(engine.state, engine.definition_for("feature-planner"), stage, "")
        self.assertIn("None (first skill in chain)", request.previous_outputs)

    def test_downstream_stage_receives_full_upstream_report(self):
        engine = self.make_engine()
        self.run_stage(engine, "feature-planner", report(summary="The plan, in full."))
        stage = engine.state.require_stage("coding")
        request = self.runner.build_request(engine.state, engine.definition_for("coding"), stage, "")
        # Full text, not a summary — contract §1.
        self.assertIn("The plan, in full.", request.previous_outputs)
        self.assertIn("# Findings", request.previous_outputs)
        self.assertIn("feature-planner", request.previous_outputs)

    def test_remediation_envelope_states_its_narrow_remit(self):
        engine = self.make_engine()
        for key in ("feature-planner", "coding", "testing"):
            self.run_stage(engine, key, report())
        self.run_stage(engine, "reviewer", report(next_skill="fixer"))
        stage = engine.state.require_stage("fixer@reviewer")
        request = self.runner.build_request(engine.state, engine.definition_for("fixer@reviewer"), stage, "")
        self.assertIn("remediation run", request.context)
        self.assertIn("reviewer", request.context)

    def test_remediation_inherits_the_origin_retry_budget(self):
        engine = self.make_engine()
        definition = engine.definition_for("fixer@reviewer")
        self.assertEqual(definition.skill, "fixer")
        self.assertEqual(definition.retry.max_attempts, 2)

    def test_envelope_is_written_for_reproducibility(self):
        engine = self.make_engine()
        stage = engine.state.require_stage("feature-planner")
        request = self.runner.build_request(engine.state, engine.definition_for("feature-planner"), stage, "c")
        path = self.runner.write_envelope(engine.state, request)
        self.assertTrue(path.is_file())
        self.assertIn("## Objective", path.read_text(encoding="utf-8"))


class RetryPolicyTests(unittest.TestCase):
    def test_retries_failures_within_budget(self):
        policy = RetryPolicy(max_attempts=3)
        self.assertTrue(policy.should_retry(Verdict.FAILED, attempts_used=1))
        self.assertTrue(policy.should_retry(Verdict.FAILED, attempts_used=2))
        self.assertFalse(policy.should_retry(Verdict.FAILED, attempts_used=3))

    def test_does_not_retry_unrecoverable_failures(self):
        policy = RetryPolicy(max_attempts=3)
        self.assertFalse(policy.should_retry(Verdict.FAILED, attempts_used=1, recoverable=False))

    def test_does_not_retry_non_failures(self):
        policy = RetryPolicy(max_attempts=3)
        for verdict in (Verdict.SUCCESS, Verdict.CHANGES_REQUESTED, Verdict.ESCALATE):
            with self.subTest(verdict=verdict):
                self.assertFalse(policy.should_retry(verdict, attempts_used=1))

    def test_blocked_is_not_retried_by_default(self):
        self.assertFalse(RetryPolicy(max_attempts=3).should_retry(Verdict.BLOCKED, 1))
        self.assertTrue(
            RetryPolicy(max_attempts=3, retry_on_blocked=True).should_retry(Verdict.BLOCKED, 1)
        )

    def test_zero_attempts_is_rejected(self):
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_attempts_remaining_never_negative(self):
        self.assertEqual(RetryPolicy(max_attempts=2).attempts_remaining(5), 0)


if __name__ == "__main__":
    unittest.main()
