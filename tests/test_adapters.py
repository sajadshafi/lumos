"""Tests for the tracker-adapter seam and the neutral WorkUnit model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_loom.adapters import LocalTracker, TrackerAdapter, get_adapter, register_adapter  # noqa: E402
from ai_loom.adapters.azure_devops import AzureDevOpsTracker  # noqa: E402
from ai_loom.models import WorkItem, WorkUnit  # noqa: E402


class WorkUnitTests(unittest.TestCase):
    def test_work_item_is_an_alias_of_work_unit(self):
        self.assertIs(WorkItem, WorkUnit)

    def test_metadata_round_trips(self):
        unit = WorkUnit(id="TASK-1", metadata={"area_path": "Web"})
        self.assertEqual(WorkUnit.from_dict(unit.to_dict()).metadata, {"area_path": "Web"})

    def test_unknown_fields_are_ignored(self):
        unit = WorkUnit.from_dict({"id": "X", "bogus": 1, "area_path": "legacy"})
        self.assertEqual(unit.id, "X")
        self.assertFalse(hasattr(unit, "area_path"))


class LocalTrackerTests(unittest.TestCase):
    def test_fetch_returns_the_id_as_the_work_unit(self):
        unit = LocalTracker().fetch("TASK-9")
        self.assertEqual(unit.id, "TASK-9")

    def test_base_hooks_are_safe_no_ops(self):
        adapter = TrackerAdapter()
        self.assertIsNone(adapter.comment("X", "hi"))
        self.assertIsNone(adapter.link_pull_request("X", "http://pr"))
        self.assertIsNone(adapter.normalise_id("X"))


class RegistryTests(unittest.TestCase):
    def test_local_is_registered(self):
        self.assertIs(get_adapter("local"), LocalTracker)

    def test_unknown_adapter_raises(self):
        with self.assertRaises(KeyError):
            get_adapter("does-not-exist")

    def test_register_and_lookup(self):
        register_adapter("azure-devops", AzureDevOpsTracker)
        self.assertIs(get_adapter("azure-devops"), AzureDevOpsTracker)


class AzureDevOpsStubTests(unittest.TestCase):
    def test_normalise_id_imposes_the_ab_scheme(self):
        adapter = AzureDevOpsTracker()
        self.assertEqual(adapter.normalise_id("273"), "AB-273")
        self.assertEqual(adapter.normalise_id("AB#273"), "AB-273")
        self.assertEqual(adapter.normalise_id("AB-273"), "AB-273")

    def test_fetch_is_an_unwired_stub(self):
        with self.assertRaises(NotImplementedError):
            AzureDevOpsTracker().fetch("273")


if __name__ == "__main__":
    unittest.main()
