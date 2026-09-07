"""Skill Runner — the only component that knows how a skill is addressed.

## What "running" a skill means here

In this hybrid design the *executor* is Claude Code itself, via the Skill tool. A
Python process cannot invoke `/coding` with the repository context, the tool
permissions, and the model reasoning the skill requires — and shelling out to a
fresh `claude -p` per stage would throw that context away and re-derive it at
significant cost.

So the runner owns everything around execution:

    locate -> load metadata -> build the input envelope -> (agent executes)
           -> validate the report -> normalise a verdict -> record deliverables

This is honest about the boundary rather than pretending to a subprocess API it
does not have. The orchestrator still never touches skills directly; it goes
through this component, which is what the "never execute skills directly"
requirement is actually protecting — uniform envelopes, uniform validation,
uniform logging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Paths, StageDefinition
from .errors import SkillNotFoundError
from .models import Stage, Verdict, WorkflowState
from .report import SkillReport, derive_verdict, parse

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillMetadata:
    """What the runner knows about an installed skill or agent."""

    name: str
    description: str
    path: Path
    invokable: bool
    worker_type: str = "skill"

    @property
    def command(self) -> str:
        return f"/{self.name}"


@dataclass
class InvocationRequest:
    """Everything a skill needs, assembled into the four-block input envelope
    defined in shared/workflow-contract.md §1."""

    skill: str
    worker_type: str
    stage_key: str
    attempt: int
    max_attempts: int
    objective: str
    context: str
    constraints: str
    previous_outputs: str
    envelope_path: Path | None = None

    def render(self) -> str:
        return (
            f"## Objective\n\n{self.objective.strip()}\n\n"
            f"## Context\n\n{self.context.strip()}\n\n"
            f"## Constraints\n\n{self.constraints.strip()}\n\n"
            f"## Previous Outputs\n\n{self.previous_outputs.strip()}\n"
        )


@dataclass
class InvocationResult:
    """Normalised outcome of one skill invocation."""

    skill: str
    stage_key: str
    attempt: int
    verdict: Verdict
    report: SkillReport | None = None
    report_path: str | None = None
    error: str | None = None
    violations: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.verdict in (Verdict.SUCCESS, Verdict.CHANGES_REQUESTED)

    @property
    def summary(self) -> str:
        return self.report.summary if self.report else (self.error or "")


class SkillRunner:
    """Discovery, envelope construction, and validation for skills and agents.

    The historical class name remains public for compatibility; Lumos treats both
    resource types as workers and exposes their type in every directive.
    """

    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        self._cache: dict[str, SkillMetadata] = {}
        self._agent_cache: dict[str, SkillMetadata] = {}

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #

    def discover(self) -> dict[str, SkillMetadata]:
        """Enumerate every skill directory, invokable or not.

        A directory without a SKILL.md is inert by the repository's own
        convention (see .claude/skills/README.md) — it is reported with
        `invokable=False` rather than hidden, so a workflow referencing a
        stub fails with an explanatory message instead of a bare KeyError.
        """
        found: dict[str, SkillMetadata] = {}
        if not self._paths.skills_dir.is_dir():
            return found

        for directory in sorted(self._paths.skills_dir.iterdir()):
            if not directory.is_dir() or directory.name in {"shared", "__pycache__"}:
                continue
            skill_file = directory / "SKILL.md"
            if not skill_file.is_file():
                found[directory.name] = SkillMetadata(
                    name=directory.name, description="", path=directory, invokable=False
                )
                continue
            meta = _read_frontmatter(skill_file)
            found[directory.name] = SkillMetadata(
                name=meta.get("name", directory.name),
                description=meta.get("description", ""),
                path=skill_file,
                invokable=True,
            )
        self._cache = found
        return found

    def discover_agents(self) -> dict[str, SkillMetadata]:
        """Discover ``agents/<name>/AGENT.md`` and flat ``agents/<name>.md`` files."""
        found: dict[str, SkillMetadata] = {}
        root = self._paths.agents_dir
        if not root.is_dir():
            return found
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir():
                agent_file = entry / "AGENT.md"
                name = entry.name
            elif entry.suffix.lower() == ".md":
                agent_file = entry
                name = entry.stem
            else:
                continue
            invokable = agent_file.is_file()
            meta = _read_frontmatter(agent_file) if invokable else {}
            found[name] = SkillMetadata(
                name=str(meta.get("name", name)),
                description=str(meta.get("description", "")),
                path=agent_file if invokable else entry,
                invokable=invokable,
                worker_type="agent",
            )
        self._agent_cache = found
        return found

    def get(self, skill: str, worker_type: str = "skill") -> SkillMetadata:
        if worker_type == "agent":
            if not self._agent_cache:
                self.discover_agents()
            meta = self._agent_cache.get(skill)
            root = self._paths.agents_dir
            label = "agent"
            cache = self._agent_cache
        else:
            if not self._cache:
                self.discover()
            meta = self._cache.get(skill)
            root = self._paths.skills_dir
            label = "skill"
            cache = self._cache
        if meta is None:
            available = ", ".join(sorted(n for n, m in cache.items() if m.invokable)) or "none"
            raise SkillNotFoundError(
                f"{label} {skill!r} not found in {root}. Invokable {label}s: {available}"
            )
        if not meta.invokable:
            raise SkillNotFoundError(
                f"{label} {skill!r} exists at {meta.path} but has no "
                f"{'AGENT.md' if worker_type == 'agent' else 'SKILL.md'}, so it is inert."
            )
        return meta

    def validate_workflow(self, skill_names: tuple[str, ...]) -> list[str]:
        """Pre-flight check: report every skill a workflow needs but cannot run.

        Called before the first stage executes, so a typo in the workflow costs a
        second rather than surfacing three stages deep.
        """
        self.discover()
        problems: list[str] = []
        for name in skill_names:
            meta = self._cache.get(name)
            if meta is None:
                problems.append(f"{name}: no directory under {self._paths.skills_dir}")
            elif not meta.invokable:
                problems.append(f"{name}: directory exists but has no SKILL.md (inert)")
        return problems

    def validate_workers(self, workers: tuple[tuple[str, str], ...]) -> list[str]:
        """Pre-flight every typed worker referenced by a workflow."""
        self.discover()
        self.discover_agents()
        problems: list[str] = []
        for worker_type, name in workers:
            try:
                self.get(name, worker_type)
            except SkillNotFoundError as exc:
                problems.append(str(exc))
        return problems

    # ------------------------------------------------------------------ #
    # Envelope construction
    # ------------------------------------------------------------------ #

    def build_request(
        self,
        state: WorkflowState,
        definition: StageDefinition,
        stage: Stage,
        constraints: str,
        objective_override: str = "",
    ) -> InvocationRequest:
        """Assemble the four-block envelope for a stage.

        `Previous Outputs` carries full upstream reports, never summaries — §1 of
        the contract is explicit that a skill given a paraphrase re-derives the
        repository state and drifts from the plan it is meant to implement.
        """
        self.get(definition.worker, definition.kind)  # fail fast if the worker is missing or inert

        item = state.work_item
        objective = objective_override or (
            item.description.strip() or item.title.strip() or f"Deliver work item {item.id}."
        )

        context_lines = [
            f"- Work item: {item.id}" + (f" — {item.title}" if item.title else ""),
            f"- Work item type: {item.type or 'unspecified'}",
            f"- Branch: {state.branch or 'not yet created'}",
            f"- Repository: {state.repository or self._paths.root.name}",
            f"- Workflow: {state.workflow_name}",
            f"- Stage: {stage.key} (attempt {stage.attempt_count + 1} of {definition.retry.max_attempts})",
            f"- Contract version: {state.contract_version}",
        ]
        if item.url:
            context_lines.append(f"- Work item URL: {item.url}")
        # Tracker-specific fields (area path, epic link, labels…) arrive as
        # free-form metadata from the tracker adapter; surface each one as a line.
        for key, value in (item.metadata or {}).items():
            if str(value).strip():
                label = str(key).replace("_", " ").strip().capitalize()
                context_lines.append(f"- {label}: {value}")
        if item.acceptance_criteria.strip():
            context_lines.append("")
            context_lines.append("Acceptance criteria:")
            context_lines.append(item.acceptance_criteria.strip())

        if stage.returns_to:
            context_lines.append("")
            context_lines.append(
                f"This is a remediation run. Address only the findings raised by "
                f"`{stage.returns_to}`, then control returns there for verification."
            )

        retry_note = self._retry_note(stage)
        if retry_note:
            context_lines.append("")
            context_lines.append(retry_note)

        request = InvocationRequest(
            skill=definition.skill,
            worker_type=definition.kind,
            stage_key=stage.key,
            attempt=stage.attempt_count + 1,
            max_attempts=definition.retry.max_attempts,
            objective=objective,
            context="\n".join(context_lines),
            constraints=constraints,
            previous_outputs=self._previous_outputs(state, stage),
        )
        return request

    def write_envelope(self, state: WorkflowState, request: InvocationRequest) -> Path:
        """Persist the envelope so a resumed run reproduces the exact input."""
        run_dir = self._paths.run_dir(state.run_id) / request.stage_key
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"attempt-{request.attempt}.input.md"
        path.write_text(request.render(), encoding="utf-8")
        request.envelope_path = path
        return path

    def report_path(self, state: WorkflowState, stage_key: str, attempt: int) -> Path:
        run_dir = self._paths.run_dir(state.run_id) / stage_key
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"attempt-{attempt}.report.md"

    # ------------------------------------------------------------------ #
    # Result collection
    # ------------------------------------------------------------------ #

    def collect(
        self,
        stage_key: str,
        skill: str,
        attempt: int,
        report_text: str,
        remediation_skill: str | None = None,
        report_path: str | None = None,
    ) -> InvocationResult:
        """Validate a report and reduce it to a verdict."""
        report = parse(report_text)
        if not report.is_conformant:
            return InvocationResult(
                skill=skill,
                stage_key=stage_key,
                attempt=attempt,
                verdict=Verdict.FAILED,
                report=report,
                report_path=report_path,
                violations=list(report.violations),
                error="report does not conform to the output contract: "
                + "; ".join(report.violations),
            )
        return InvocationResult(
            skill=skill,
            stage_key=stage_key,
            attempt=attempt,
            verdict=derive_verdict(report, remediation_skill),
            report=report,
            report_path=report_path,
        )

    def apply(self, stage: Stage, result: InvocationResult) -> None:
        """Fold a validated report into stage state."""
        if result.report is None:
            return
        stage.summary = result.report.summary
        stage.deliverables = result.report.bullets("Deliverables")
        stage.decisions = result.report.bullets("Decisions")
        stage.risks = result.report.bullets("Risks")
        stage.next_skill = result.report.next_skill

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _previous_outputs(self, state: WorkflowState, stage: Stage) -> str:
        """Concatenate upstream reports, oldest first."""
        chunks: list[str] = []
        for key in state.order:
            if key == stage.key:
                continue
            upstream = state.stages.get(key)
            if upstream is None or not upstream.attempts:
                continue
            last = upstream.attempts[-1]
            if not last.report_path:
                continue
            path = Path(last.report_path)
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8").strip()
            chunks.append(f"### Report from `{upstream.skill}` (stage `{key}`)\n\n{body}")
        if not chunks:
            return "None (first skill in chain)"
        return "\n\n---\n\n".join(chunks)

    @staticmethod
    def _retry_note(stage: Stage) -> str:
        """Tell a retried skill why its last attempt was rejected.

        Re-invoking with no explanation usually reproduces the same failure; the
        prior error is the single most useful thing to pass forward.
        """
        failed = [a for a in stage.attempts if a.verdict in (Verdict.FAILED.value, None) and a.error]
        if not failed:
            return ""
        last = failed[-1]
        return (
            f"The previous attempt (#{last.number}) was rejected: {last.error}\n"
            "Correct that specific problem. Do not restart the work from scratch."
        )


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter without a YAML dependency.

    Frontmatter here is a flat `key: value` map, so a line scan is sufficient and
    avoids pulling the fallback parser into skill discovery.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    data: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key.strip()] = value
    return data


# Public name for new integrations. Keep SkillRunner for the 0.1 API.
WorkerRunner = SkillRunner
