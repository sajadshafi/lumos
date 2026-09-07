"""Tests for the tracker-adapter seam and the neutral WorkUnit model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_loom.adapters import (  # noqa: E402
    GitHubTracker,
    GitLabTracker,
    JiraTracker,
    LocalTracker,
    TrackerAdapter,
    create_adapter,
    get_adapter,
    register_adapter,
)
from ai_loom.adapters.azure_devops import AzureDevOpsTracker  # noqa: E402
from ai_loom.adapters.content import adf_to_text, html_to_text  # noqa: E402
from ai_loom.models import WorkItem, WorkUnit  # noqa: E402


class FakeTransport:
    name = "fake"

    def __init__(self, response=None):
        self.response = response or {}
        self.calls = []

    def connected(self, provider=None):
        return True

    def call(self, provider, operation, params):
        self.calls.append((provider, operation, params))
        return self.response


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

    def test_all_first_party_adapters_are_registered(self):
        for name in ("github", "jira", "gitlab", "azure-devops"):
            with self.subTest(name=name):
                self.assertEqual(create_adapter(name, transport_instance=FakeTransport()).name, name)


class AzureDevOpsTests(unittest.TestCase):
    def test_normalise_id_imposes_the_ab_scheme(self):
        adapter = AzureDevOpsTracker()
        self.assertEqual(adapter.normalise_id("273"), "AB#273")
        self.assertEqual(adapter.normalise_id("AB#273"), "AB#273")
        self.assertEqual(adapter.normalise_id("AB-273"), "AB#273")
        self.assertEqual(AzureDevOpsTracker(options={"prefix": "C3"}).normalise_id("C3#273"), "C3#273")

    def test_fetch_maps_fields_and_html(self):
        transport = FakeTransport(
            {
                "id": 273,
                "rev": 4,
                "fields": {
                    "System.Title": "Ship it",
                    "System.State": "Active",
                    "System.Description": "<p>Hello <strong>world</strong></p>",
                    "System.AreaPath": "Web",
                    "Microsoft.VSTS.Common.AcceptanceCriteria": "<ul><li>Works</li></ul>",
                },
            }
        )
        unit = AzureDevOpsTracker(transport=transport).fetch("AB#273")
        self.assertEqual(unit.id, "AB#273")
        self.assertEqual(unit.description, "Hello world")
        self.assertIn("Works", unit.acceptance_criteria)
        self.assertEqual(unit.metadata["area_path"], "Web")


class GitHubTests(unittest.TestCase):
    def test_url_sets_repository_and_maps_metadata(self):
        transport = FakeTransport(
            {
                "issue": {
                    "issue_number": 2,
                    "title": "Epic",
                    "body": "Text\n- [ ] Done",
                    "state": "open",
                    "display_url": "https://github.com/o/r/issues/2",
                    "labels": [{"name": "epic"}],
                    "assignees": [{"login": "sam"}],
                }
            }
        )
        adapter = GitHubTracker(transport=transport)
        unit = adapter.fetch("https://github.com/o/r/issues/2")
        self.assertEqual(unit.id, "GH#2")
        self.assertEqual(unit.acceptance_criteria, "- [ ] Done")
        self.assertEqual(unit.metadata["repository"], "o/r")
        self.assertEqual(unit.metadata["labels"], "epic")


class JiraTests(unittest.TestCase):
    def test_adf_and_custom_acceptance_field_are_mapped(self):
        adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}]}
        transport = FakeTransport(
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Story",
                    "description": adf,
                    "issuetype": {"name": "Story"},
                    "status": {"name": "Open"},
                    "customfield_1": adf,
                },
            }
        )
        unit = JiraTracker(
            options={"site": "https://x.atlassian.net", "acceptance_criteria_field": "customfield_1"},
            transport=transport,
        ).fetch("PROJ-1")
        self.assertEqual(unit.description, "Hello")
        self.assertEqual(unit.acceptance_criteria, "Hello")


class GitLabTests(unittest.TestCase):
    def test_self_managed_url_is_project_scoped(self):
        transport = FakeTransport(
            {
                "iid": 9,
                "title": "Bug",
                "description": "- [x] Reproduced",
                "state": "opened",
                "web_url": "https://git.example/acme/app/-/issues/9",
            }
        )
        adapter = GitLabTracker(transport=transport)
        unit = adapter.fetch("https://git.example/acme/app/-/issues/9")
        self.assertEqual(unit.id, "GL#9")
        self.assertEqual(adapter.options["host"], "https://git.example")
        self.assertEqual(unit.metadata["project"], "acme/app")


class ConformanceTests(unittest.TestCase):
    def test_remote_write_operations_use_capabilities_and_idempotency_keys(self):
        for adapter_cls in (GitHubTracker, JiraTracker, GitLabTracker, AzureDevOpsTracker):
            with self.subTest(adapter=adapter_cls.name):
                transport = FakeTransport()
                adapter = adapter_cls(transport=transport)
                self.assertTrue(all(adapter.capabilities.to_dict().values()))
                adapter.comment("1", "summary")
                adapter.link_pull_request("1", "https://example/pr/1")
                adapter.transition("1", "Done")
                self.assertEqual([call[1] for call in transport.calls], ["comment", "link_pull_request", "transition"])
                self.assertTrue(all(call[2]["idempotency_key"] for call in transport.calls))

    def test_rich_text_normalizers_preserve_structure(self):
        self.assertIn("- item", html_to_text("<ul><li>item</li></ul>"))
        self.assertIn("```", adf_to_text({"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]}))


if __name__ == "__main__":
    unittest.main()
