"""End-to-end CLI behaviour — the surface the orchestrator skill actually calls."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ai_loom.cli import main
from support import OrchestratorTestCase, report  # noqa: E402


class CliTestCase(OrchestratorTestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--project-dir", str(self.tmp), *argv])
        return code, buffer.getvalue()

    def run_json(self, *argv: str) -> tuple[int, dict]:
        code, out = self.run_cli(*argv)
        return code, json.loads(out)


class LifecycleTests(CliTestCase):
    def test_start_fetches_selected_tracker_before_creating_state(self):
        from ai_loom.adapters import TrackerAdapter, register_adapter
        from ai_loom.models import WorkUnit

        class FakeTracker(TrackerAdapter):
            name = "fake"

            def normalise_id(self, work_id):
                return f"FAKE#{str(work_id).lstrip('#')}"

            def fetch(self, work_id):
                return WorkUnit(
                    id=self.normalise_id(work_id),
                    title="Fetched ticket",
                    description="Remote description",
                    metadata={"labels": "ready"},
                )

        register_adapter("fake", FakeTracker)
        (self.tmp / "lumos.yaml").write_text("tracker:\n  provider: fake\n", encoding="utf-8")
        code, payload = self.run_json("start", "42")
        self.assertEqual(code, 0)
        self.assertEqual(payload["run_id"], "FAKE-42")
        self.assertEqual(payload["tracker"]["provider"], "fake")
        state = self.manager.load("FAKE-42")
        self.assertEqual(state.work_item.title, "Fetched ticket")
        self.assertEqual(state.work_item.metadata["labels"], "ready")
        self.assertEqual(state.work_item.metadata["tracker_transport"], "mcp")

    def test_bare_ticket_number_uses_default_tc_prefix(self):
        _, payload = self.run_json("start", "273")
        self.assertEqual(payload["run_id"], "TC-273")
        code, out = self.run_cli("status", "273")
        self.assertEqual(code, 0)
        self.assertIn("TC-273", out)

    def test_agent_stage_returns_an_agent_directive(self):
        agent_dir = self.paths.agents_dir / "planner"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text("---\nname: planner\n---\n", encoding="utf-8")
        (self.paths.workflows_dir / "agent-first.yaml").write_text(
            "name: agent-first\nstages:\n  - agent: planner\n", encoding="utf-8"
        )
        self.run_json("start", "TC#1", "--workflow", "agent-first")
        code, payload = self.run_json("next", "TC-1")
        self.assertEqual(code, 0)
        self.assertEqual(payload["action"], "invoke_agent")
        self.assertEqual(payload["worker_type"], "agent")
        self.assertEqual(payload["worker"], "planner")
        self.assertTrue(payload["agent_path"].endswith("AGENT.md"))

    def test_agent_remediation_dispatches_an_agent_fixer(self):
        for name in ("reviewer-agent", "fixer-agent"):
            agent_dir = self.paths.agents_dir / name
            agent_dir.mkdir(parents=True)
            (agent_dir / "AGENT.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
        (self.paths.workflows_dir / "agent-remediation.yaml").write_text(
            "name: agent-remediation\nstages:\n"
            "  - agent: reviewer-agent\n"
            "    remediation:\n"
            "      agent: fixer-agent\n"
            "      max_cycles: 2\n",
            encoding="utf-8",
        )
        self.run_json("start", "TC#2", "--workflow", "agent-remediation")
        directive = self.run_json("next", "TC-2")[1]
        with open(directive["report_path"], "w", encoding="utf-8") as handle:
            handle.write(report(next_skill="fixer-agent — changes requested"))
        _, payload = self.run_json("record", "TC-2", "--stage", "reviewer-agent", "--report", directive["report_path"])
        self.assertEqual(payload["directive"]["action"], "invoke_agent")
        self.assertEqual(payload["directive"]["worker"], "fixer-agent")

    def test_start_creates_a_run(self):
        code, payload = self.run_json("start", "AB#273", "--title", "Attendance", "--branch", "feat/273")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["run_id"], "AB-273")
        self.assertFalse(payload["resumed"])
        self.assertTrue(self.paths.state_file("AB-273").is_file())

    def test_start_twice_resumes_rather_than_restarting(self):
        self.run_json("start", "AB#273")
        _, payload = self.run_json("start", "AB#273")
        self.assertTrue(payload["resumed"])

    def test_force_restarts_clean(self):
        self.run_json("start", "AB#273")
        _, payload = self.run_json("start", "AB#273", "--force")
        self.assertFalse(payload["resumed"])

    def test_next_returns_an_invoke_directive_with_an_envelope(self):
        self.run_json("start", "AB#273", "--title", "Attendance")
        code, payload = self.run_json("next", "AB-273")
        self.assertEqual(code, 0)
        self.assertEqual(payload["action"], "invoke_skill")
        self.assertEqual(payload["skill"], "feature-planner")
        self.assertEqual(payload["skill_command"], "/feature-planner")
        self.assertIn("## Objective", payload["envelope"])
        self.assertTrue(
            self.paths.root.joinpath(payload["envelope_path"]).is_file()
            or payload["envelope_path"].startswith(str(self.tmp))
        )

    def test_next_is_idempotent(self):
        # Inspecting the run must not inflate the attempt count.
        self.run_json("start", "AB#273")
        first = self.run_json("next", "AB-273")[1]
        second = self.run_json("next", "AB-273")[1]
        self.assertEqual(first["attempt"], second["attempt"], "repeated `next` opened a second attempt")

    def test_record_advances_to_the_next_stage(self):
        self.run_json("start", "AB#273")
        directive = self.run_json("next", "AB-273")[1]
        report_path = directive["report_path"]
        self.paths.root.joinpath(report_path) if False else None
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(report(next_skill="coding"))

        code, payload = self.run_json("record", "AB-273", "--stage", "feature-planner", "--report", report_path)
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "success")
        self.assertEqual(payload["directive"]["skill"], "coding")

    def test_full_run_to_completion(self):
        self.run_json("start", "AB#273", "--title", "Attendance")
        for _ in range(10):
            directive = self.run_json("next", "AB-273")[1]
            if directive["action"] != "invoke_skill":
                break
            with open(directive["report_path"], "w", encoding="utf-8") as handle:
                handle.write(report(next_skill="None — done"))
            self.run_json("record", "AB-273", "--stage", directive["stage_key"], "--report", directive["report_path"])
        self.assertEqual(directive["action"], "complete")

    def test_record_of_a_malformed_report_returns_violations(self):
        self.run_json("start", "AB#273")
        directive = self.run_json("next", "AB-273")[1]
        with open(directive["report_path"], "w", encoding="utf-8") as handle:
            handle.write("nope")
        _, payload = self.run_json(
            "record", "AB-273", "--stage", "feature-planner", "--report", directive["report_path"]
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["verdict"], "failed")
        self.assertTrue(payload["violations"])
        self.assertEqual(payload["directive"]["skill"], "feature-planner")

    def test_failed_flag_records_an_invocation_that_never_ran(self):
        self.run_json("start", "AB#273")
        self.run_json("next", "AB-273")
        _, payload = self.run_json(
            "record", "AB-273", "--stage", "feature-planner", "--failed", "--error", "skill timed out"
        )
        self.assertEqual(payload["verdict"], "failed")

    def test_record_without_report_is_a_usage_error(self):
        self.run_json("start", "AB#273")
        code, payload = self.run_json("record", "AB-273", "--stage", "feature-planner")
        self.assertEqual(code, 1)
        self.assertIn("--report is required", payload["error"])

    def test_unknown_stage_is_rejected_with_the_valid_list(self):
        self.run_json("start", "AB#273")
        code, payload = self.run_json("record", "AB-273", "--stage", "nope", "--report", "x")
        self.assertEqual(code, 1)
        self.assertIn("coding", payload["stages"])


class ExitCodeTests(CliTestCase):
    def test_blocked_run_exits_two(self):
        self.run_json("start", "AB#273")
        directive = self.run_json("next", "AB-273")[1]
        with open(directive["report_path"], "w", encoding="utf-8") as handle:
            handle.write(report(next_skill="None — blocked, need the fee schedule"))
        code, _ = self.run_json("record", "AB-273", "--stage", "feature-planner", "--report", directive["report_path"])
        self.assertEqual(code, 2)

    def test_status_of_a_blocked_run_exits_two(self):
        self.test_blocked_run_exits_two()
        code, _ = self.run_cli("status", "AB-273")
        self.assertEqual(code, 2)

    def test_missing_run_exits_one_with_json(self):
        code, payload = self.run_json("status", "AB-999")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "StateError")


class InspectionTests(CliTestCase):
    def test_init_creates_a_valid_project_with_json_output(self):
        target = self.tmp / "initialized"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["init", str(target), "--ticket-prefix", "C3#", "--json"])
        payload = json.loads(buffer.getvalue())

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["root"], str(target.resolve()))
        self.assertTrue((target / "lumos.yaml").is_file())
        with redirect_stdout(io.StringIO()) as validation_output:
            validation_code = main(["--project-dir", str(target), "validate", "default"])
        self.assertEqual(validation_code, 0, validation_output.getvalue())

    def test_init_reports_conflicts_and_preserves_existing_files(self):
        target = self.tmp / "conflicting-init"
        target.mkdir()
        config = target / "lumos.yaml"
        config.write_text("keep: me\n", encoding="utf-8")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["init", str(target), "--json"])
        payload = json.loads(buffer.getvalue())

        self.assertEqual(code, 1)
        self.assertIn("lumos.yaml", payload["conflicts"])
        self.assertEqual(config.read_text(encoding="utf-8"), "keep: me\n")

    def test_init_without_directory_uses_the_current_directory(self):
        target = self.tmp / "current-directory-init"
        buffer = io.StringIO()
        with patch("ai_loom.cli.Path.cwd", return_value=target), redirect_stdout(buffer):
            code = main(["init", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["root"], str(target.resolve()))
        self.assertTrue((target / "lumos.yaml").is_file())

    def test_trackers_lists_first_party_providers_and_local_default(self):
        code, payload = self.run_json("trackers")
        self.assertEqual(code, 0)
        self.assertEqual(payload["selected"], "local")
        providers = {row["provider"] for row in payload["trackers"]}
        self.assertTrue({"local", "github", "jira", "gitlab", "azure-devops"}.issubset(providers))

    def test_install_copies_the_lumos_runtime_skill(self):
        destination = self.tmp / "installed-lumos"
        code, payload = self.run_json("install", "codex", "--destination", str(destination))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue((destination / "SKILL.md").is_file())
        self.assertTrue((destination / "agents" / "openai.yaml").is_file())
        self.assertTrue((destination / ".lumos-install.json").is_file())

    def test_install_without_runtime_detects_all_configured_homes(self):
        codex_home = self.tmp / "codex"
        claude_home = self.tmp / "claude"
        codex_home.mkdir()
        claude_home.mkdir()
        with patch.dict("os.environ", {"CODEX_HOME": str(codex_home), "CLAUDE_HOME": str(claude_home)}, clear=False):
            code, payload = self.run_json("install", "--json")
        self.assertEqual(code, 0)
        self.assertEqual({item["runtime"] for item in payload["results"]}, {"codex", "claude"})
        self.assertTrue((codex_home / "skills" / "lumos" / "SKILL.md").is_file())
        self.assertTrue((claude_home / "skills" / "lumos" / "SKILL.md").is_file())

    def test_install_dry_run_does_not_write(self):
        codex_home = self.tmp / "dry-codex"
        with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
            code, payload = self.run_json("install", "codex", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(codex_home.exists())

    def test_install_dry_run_has_human_readable_output(self):
        codex_home = self.tmp / "human-codex"
        codex_home.mkdir()
        with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
            code, output = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Installation plan", output)
        self.assertIn("~ codex: install", output)
        self.assertIn("codex: install", output)
        self.assertFalse((codex_home / "skills" / "lumos").exists())

    def test_runtime_install_failure_does_not_hide_other_results(self):
        import ai_loom.runtime_installers as installers

        class BrokenInstaller(installers.RuntimeInstaller):
            name = "broken"
            default_home = ".broken"

            def detect(self):
                raise OSError("detection failed")

        codex_home = self.tmp / "isolated-codex"
        with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
            with patch.dict(
                installers._INSTALLERS,
                {"codex": installers.CodexInstaller, "broken": BrokenInstaller},
                clear=True,
            ):
                code, payload = self.run_json("install", "--all", "--json")
        self.assertEqual(code, 1)
        by_runtime = {item["runtime"]: item for item in payload["results"]}
        self.assertEqual(by_runtime["broken"]["action"], "failed")
        self.assertEqual(by_runtime["codex"]["action"], "installed")

    def test_uninstall_removes_managed_installation(self):
        codex_home = self.tmp / "uninstall-codex"
        with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
            self.run_json("install", "codex")
            code, payload = self.run_json("uninstall", "codex", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(payload["results"][0]["applied"])
        self.assertFalse((codex_home / "skills" / "lumos").exists())

    def test_doctor_json_is_structured_and_does_not_expose_secrets(self):
        with patch.dict(
            "os.environ",
            {"GITHUB_TOKEN": "super-secret-value", "LUMOS_MCP_COMMAND": "bridge --token hidden"},
            clear=False,
        ):
            code, payload = self.run_json("doctor", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], 1)
        rendered = json.dumps(payload)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("bridge --token hidden", rendered)

    def test_skills_lists_invokable_and_inert(self):
        _, payload = self.run_json("skills")
        by_name = {s["name"]: s for s in payload["skills"]}
        self.assertTrue(by_name["coding"]["invokable"])
        self.assertFalse(by_name["security"]["invokable"])

    def test_validate_a_good_workflow(self):
        code, payload = self.run_json("validate", "default")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stages"][3]["remediation"], "fixer")

    def test_validate_fails_when_a_skill_is_inert(self):
        (self.paths.workflows_dir / "risky.yaml").write_text(
            "name: risky\nstages:\n  - skill: coding\n  - skill: security\n", encoding="utf-8"
        )
        code, payload = self.run_json("validate", "risky")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("security", payload["problems"][0])

    def test_start_refuses_a_workflow_with_inert_skills(self):
        (self.paths.workflows_dir / "risky.yaml").write_text(
            "name: risky\nstages:\n  - skill: security\n", encoding="utf-8"
        )
        code, payload = self.run_json("start", "AB#900", "--workflow", "risky")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_status_renders_a_board(self):
        self.run_json("start", "AB#273", "--title", "Attendance")
        _, out = self.run_cli("status", "AB-273")
        self.assertIn("AB-273", out)
        self.assertIn("feature-planner", out)

    def test_state_renders_the_yaml_model(self):
        self.run_json("start", "AB#273", "--title", "Attendance")
        _, out = self.run_cli("state", "AB-273")
        for key in ("feature:", "status:", "current_step:", "next_step:", "errors:"):
            self.assertIn(key, out)

    def test_summary_is_markdown_with_a_timeline(self):
        self.run_json("start", "AB#273", "--title", "Attendance")
        directive = self.run_json("next", "AB-273")[1]
        with open(directive["report_path"], "w", encoding="utf-8") as handle:
            handle.write(report(deliverables="- the implementation plan"))
        self.run_json("record", "AB-273", "--stage", "feature-planner", "--report", directive["report_path"])

        _, out = self.run_cli("summary", "AB-273")
        self.assertIn("# Orchestration summary — AB#273", out)
        self.assertIn("the implementation plan", out)
        self.assertIn("Execution timeline", out)

    def test_runs_lists_known_runs(self):
        self.run_json("start", "AB#273")
        self.run_json("start", "AB#274")
        _, payload = self.run_json("runs")
        self.assertEqual({r["run_id"] for r in payload["runs"]}, {"AB-273", "AB-274"})

    def test_timeline_records_events(self):
        self.run_json("start", "AB#273")
        self.run_json("next", "AB-273")
        _, out = self.run_cli("timeline", "AB-273")
        self.assertIn("workflow_started", out)
        self.assertIn("stage_started", out)


class ControlCommandTests(CliTestCase):
    def test_cancel_is_terminal(self):
        self.run_json("start", "AB#273")
        _, payload = self.run_json("cancel", "AB-273", "--reason", "descoped")
        self.assertEqual(payload["directive"]["workflow_status"], "cancelled")

    def test_skip_advances(self):
        self.run_json("start", "AB#273")
        _, payload = self.run_json("skip", "AB-273", "--stage", "feature-planner", "--reason", "plan already written")
        self.assertEqual(payload["directive"]["skill"], "coding")


if __name__ == "__main__":
    unittest.main()
