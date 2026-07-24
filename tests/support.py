"""Shared fixtures for the orchestrator test suite.

Builds a throwaway project tree — skills, workflows, state, logs — so tests
exercise real discovery and real file persistence rather than mocks. The whole
package is injected with a `Paths`, which is what makes this cheap.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_loom.config import Paths, load_workflow  # noqa: E402
from ai_loom.engine import Engine  # noqa: E402
from ai_loom.logging_ import RunLogger  # noqa: E402
from ai_loom.models import WorkItem  # noqa: E402
from ai_loom.skill_runner import SkillRunner  # noqa: E402
from ai_loom.state_manager import StateManager  # noqa: E402

SKILL_TEMPLATE = """---
name: {name}
description: "Test double for the {name} skill."
---

# /{name}
"""

DEFAULT_WORKFLOW = """
version: 1
name: default
max_total_stages: 40
stages:
  - skill: feature-planner
    retry:
      max_attempts: 2
  - skill: coding
    retry:
      max_attempts: 3
  - skill: testing
    retry:
      max_attempts: 2
  - skill: reviewer
    retry:
      max_attempts: 2
    remediation:
      skill: fixer
      max_cycles: 3
  - skill: post-feature-implementation
    retry:
      max_attempts: 2
"""


def report(
    summary: str = "Did the work.",
    next_skill: str = "None — chain complete",
    deliverables: str = "- a file",
    findings: str = "- an observed fact (`src/x.cs:1`)",
    decisions: str = "- chose A over B",
    risks: str = "- low: nothing notable",
) -> str:
    """A conformant six-section report."""
    return (
        f"# Summary\n\n{summary}\n\n"
        f"# Findings\n\n{findings}\n\n"
        f"# Decisions\n\n{decisions}\n\n"
        f"# Deliverables\n\n{deliverables}\n\n"
        f"# Risks\n\n{risks}\n\n"
        f"# Next Skill\n\n{next_skill}\n"
    )


class OrchestratorTestCase(unittest.TestCase):
    """Base case providing a populated temporary project."""

    skills = (
        "feature-planner",
        "coding",
        "testing",
        "reviewer",
        "fixer",
        "post-feature-implementation",
    )
    inert_skills = ("security", "performance")
    workflow_text = DEFAULT_WORKFLOW

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="orchestrator-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.paths = Paths.resolve(self.tmp)
        self.paths.ensure()
        self.paths.skills_dir.mkdir(parents=True, exist_ok=True)
        self.paths.workflows_dir.mkdir(parents=True, exist_ok=True)

        for name in self.skills:
            directory = self.paths.skills_dir / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "SKILL.md").write_text(SKILL_TEMPLATE.format(name=name), encoding="utf-8")

        for name in self.inert_skills:
            directory = self.paths.skills_dir / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "README.md").write_text(f"# {name}\n", encoding="utf-8")

        (self.paths.skills_dir / "shared").mkdir(parents=True, exist_ok=True)
        (self.paths.workflows_dir / "default.yaml").write_text(self.workflow_text, encoding="utf-8")

        self.manager = StateManager(self.paths)
        self.runner = SkillRunner(self.paths)

    # -- helpers ----------------------------------------------------------- #

    def make_engine(self, workflow: str = "default", work_item_id: str = "AB#273") -> Engine:
        definition = load_workflow(self.paths, workflow)
        state = self.manager.create(
            WorkItem(id=work_item_id, title="Test feature", type="Feature"),
            definition,
            branch="feat/273-test",
        )
        return Engine(
            definition=definition,
            state=state,
            paths=self.paths,
            state_manager=self.manager,
            runner=self.runner,
            logger=RunLogger(self.paths.log_file(state.run_id), state.run_id),
        )

    def run_stage(self, engine: Engine, stage_key: str, report_text: str):
        """Simulate one full skill invocation: begin, write report, record."""
        stage = engine.state.require_stage(stage_key)
        self.manager.begin_attempt(engine.state, stage_key)
        path = self.runner.report_path(engine.state, stage_key, stage.attempt_count)
        path.write_text(report_text, encoding="utf-8")

        origin = engine.definition.stage(stage_key)
        remediation = origin.remediation.skill if origin and origin.remediation else None
        result = engine.runner.collect(
            stage_key=stage_key,
            skill=stage.skill,
            attempt=stage.attempt_count,
            report_text=report_text,
            remediation_skill=remediation,
            report_path=str(path),
        )
        from ai_loom.models import StageStatus, Verdict

        status_map = {
            Verdict.SUCCESS: StageStatus.COMPLETED,
            Verdict.CHANGES_REQUESTED: StageStatus.COMPLETED,
            Verdict.FAILED: StageStatus.FAILED,
            Verdict.BLOCKED: StageStatus.BLOCKED,
            Verdict.ESCALATE: StageStatus.ESCALATED,
        }
        self.manager.complete_attempt(
            engine.state,
            stage_key,
            verdict=result.verdict.value,
            status=status_map[result.verdict],
            summary=result.summary,
            report_path=str(path),
            error=result.error,
        )
        return engine.record(result)
