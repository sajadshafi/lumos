"""Project scaffolding behavior for ``lumos init``."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from ai_loom.config import Paths, load_project_config, load_workflow
from ai_loom.errors import ConfigError
from ai_loom.initializer import initialize_project
from ai_loom.skill_runner import SkillRunner


class InitializerTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="lumos-init-test-"))
        self.addCleanup(shutil.rmtree, self.parent, ignore_errors=True)
        self.target = self.parent / "new-project"

    def test_generated_project_is_immediately_valid(self):
        result = initialize_project(self.target, project_name="Sample API", ticket_prefix="C3#")
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 11)

        paths = Paths.resolve(self.target)
        config = load_project_config(paths)
        workflow = load_workflow(paths, config.default_workflow)
        self.assertEqual(config.ticket_prefix, "C3")
        self.assertEqual(config.execution_mode, "continuous")
        self.assertEqual(
            workflow.workers,
            (
                ("agent", "planner"),
                ("skill", "coding"),
                ("skill", "testing"),
                ("agent", "reviewer"),
                ("skill", "fixer"),
            ),
        )
        self.assertEqual(SkillRunner(paths).validate_workers(workflow.workers), [])

    def test_second_run_is_idempotent(self):
        initialize_project(self.target)
        second = initialize_project(self.target)
        self.assertTrue(second.ok)
        self.assertFalse(second.created)
        self.assertFalse(second.overwritten)
        self.assertEqual(len(second.unchanged), 11)

    def test_conflicting_files_are_preserved_without_force(self):
        self.target.mkdir()
        config = self.target / "lumos.yaml"
        config.write_text("user-authored\n", encoding="utf-8")

        result = initialize_project(self.target)
        self.assertFalse(result.ok)
        self.assertIn("lumos.yaml", result.conflicts)
        self.assertEqual(config.read_text(encoding="utf-8"), "user-authored\n")
        self.assertTrue((self.target / "workflows" / "default.yaml").is_file())

    def test_force_replaces_only_known_scaffold_files(self):
        self.target.mkdir()
        config = self.target / "lumos.yaml"
        unrelated = self.target / "README.md"
        config.write_text("old\n", encoding="utf-8")
        unrelated.write_text("keep\n", encoding="utf-8")

        result = initialize_project(self.target, force=True)
        self.assertTrue(result.ok)
        self.assertIn("lumos.yaml", result.overwritten)
        self.assertIn("default_workflow: default", config.read_text(encoding="utf-8"))
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep\n")

    def test_dry_run_does_not_create_the_target(self):
        result = initialize_project(self.target, dry_run=True)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 11)
        self.assertFalse(self.target.exists())

    def test_invalid_prefix_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "letters and digits"):
            initialize_project(self.target, ticket_prefix="not-valid!")

    def test_invalid_tracker_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "lowercase letters"):
            initialize_project(self.target, tracker="github\nunsafe: value")

    def test_file_target_is_rejected(self):
        self.target.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "not a directory"):
            initialize_project(self.target)


if __name__ == "__main__":
    unittest.main()
