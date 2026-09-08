"""Runtime installer contract, safety, and idempotency tests."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_loom.errors import ConfigError
from ai_loom.runtime_installers import MANIFEST_NAME, CodexInstaller


class RuntimeInstallerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lumos-runtime-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = self.root / "codex-home"
        self.destination = self.home / "skills" / "lumos"
        self.installer = CodexInstaller(home=self.home)

    def test_detection_does_not_create_runtime_home(self):
        self.installer.executable = ""
        detected, _ = self.installer.detect()
        self.assertFalse(detected)
        self.assertFalse(self.home.exists())
        self.home.mkdir()
        self.assertTrue(self.installer.detect()[0])

    def test_dry_run_plans_without_writing(self):
        plan = self.installer.plan(selected=True)
        result = self.installer.install(plan, dry_run=True)
        self.assertEqual(plan.action, "install")
        self.assertFalse(result["applied"])
        self.assertFalse(self.destination.exists())

    def test_install_is_atomic_managed_and_idempotent(self):
        first = self.installer.install(self.installer.plan(selected=True))
        self.assertTrue(first["applied"])
        self.assertEqual(first["reason"], "integration installed")
        self.assertTrue((self.destination / "SKILL.md").is_file())
        manifest = json.loads((self.destination / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["runtime"], "codex")
        self.assertIn("SKILL.md", manifest["files"])

        second_plan = self.installer.plan(selected=True)
        second = self.installer.install(second_plan)
        self.assertEqual(second_plan.action, "unchanged")
        self.assertFalse(second["applied"])
        self.assertTrue(self.installer.verify().ok)

    def test_install_updates_an_outdated_manifest_version(self):
        self.installer.install(self.installer.plan(selected=True))
        manifest_path = self.destination / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["lumos_version"] = "0.0.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        plan = self.installer.plan(selected=True)
        self.assertEqual(plan.action, "update")
        result = self.installer.install(plan)
        self.assertEqual(result["action"], "updated")
        self.assertTrue(self.installer.verify().ok)

    def test_matching_legacy_installation_is_adopted(self):
        for relative, content in self.installer.source_files().items():
            target = self.destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        plan = self.installer.plan(selected=True)
        self.assertEqual(plan.action, "repair-manifest")
        self.installer.install(plan)
        self.assertTrue((self.destination / MANIFEST_NAME).is_file())

    def test_unmanaged_files_conflict_without_force(self):
        self.destination.mkdir(parents=True)
        (self.destination / "SKILL.md").write_text("user authored", encoding="utf-8")
        plan = self.installer.plan(selected=True)
        self.assertEqual(plan.action, "conflict")
        self.assertFalse(self.installer.install(plan)["applied"])
        self.assertEqual((self.destination / "SKILL.md").read_text(encoding="utf-8"), "user authored")

    def test_force_replaces_known_files_but_preserves_unrelated_files(self):
        self.destination.mkdir(parents=True)
        skill = self.destination / "SKILL.md"
        extra = self.destination / "notes.txt"
        skill.write_text("user authored", encoding="utf-8")
        extra.write_text("keep me", encoding="utf-8")
        plan = self.installer.plan(selected=True, force=True)
        self.installer.install(plan)
        self.assertNotEqual(skill.read_text(encoding="utf-8"), "user authored")
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep me")

    def test_modified_managed_file_requires_force(self):
        self.installer.install(self.installer.plan(selected=True))
        (self.destination / "SKILL.md").write_text("locally changed", encoding="utf-8")
        self.assertEqual(self.installer.plan(selected=True).action, "conflict")
        self.assertEqual(self.installer.verify().status, "outdated-or-modified")
        self.assertEqual(self.installer.plan(selected=True, force=True).action, "update")

    def test_uninstall_removes_only_manifest_owned_files(self):
        self.installer.install(self.installer.plan(selected=True))
        unrelated = self.destination / "keep.txt"
        unrelated.write_text("mine", encoding="utf-8")

        preview = self.installer.uninstall(dry_run=True)
        self.assertFalse(preview["applied"])
        self.assertTrue((self.destination / "SKILL.md").exists())

        result = self.installer.uninstall()
        self.assertTrue(result["applied"])
        self.assertFalse((self.destination / "SKILL.md").exists())
        self.assertFalse((self.destination / MANIFEST_NAME).exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "mine")

    def test_uninstall_refuses_manifest_path_escape(self):
        self.destination.mkdir(parents=True)
        outside = self.destination.parent / "outside.txt"
        outside.write_text("safe", encoding="utf-8")
        (self.destination / MANIFEST_NAME).write_text(
            json.dumps({"runtime": "codex", "files": {"../outside.txt": "x"}}), encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            self.installer.uninstall()
        self.assertEqual(outside.read_text(encoding="utf-8"), "safe")


if __name__ == "__main__":
    unittest.main()
