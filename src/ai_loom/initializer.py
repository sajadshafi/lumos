"""Safe, repeatable project scaffolding for ``lumos init``."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_PREFIX = re.compile(r"^[A-Za-z0-9]+#?$")
_TRACKER = re.compile(r"^[a-z0-9-]+$")


@dataclass(frozen=True)
class InitResult:
    """Files affected by a project initialization attempt."""

    root: Path
    created: tuple[str, ...]
    overwritten: tuple[str, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[str, ...]
    dry_run: bool

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "dry_run": self.dry_run,
            "created": list(self.created),
            "overwritten": list(self.overwritten),
            "unchanged": list(self.unchanged),
            "conflicts": list(self.conflicts),
        }


def initialize_project(
    destination: str | Path,
    *,
    project_name: str = "",
    ticket_prefix: str = "TC",
    tracker: str = "local",
    force: bool = False,
    dry_run: bool = False,
) -> InitResult:
    """Create a valid mixed skill/agent starter project without silent overwrites."""
    root = Path(destination).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ConfigError(f"initialization target is not a directory: {root}")

    prefix = ticket_prefix.strip().upper().removesuffix("#")
    if not prefix or not _PREFIX.fullmatch(prefix):
        raise ConfigError("--ticket-prefix must contain only letters and digits")
    name = project_name.strip() or root.name or "lumos-project"
    if any(character in name for character in "\r\n"):
        raise ConfigError("--name cannot contain line breaks")
    tracker = tracker.strip().lower()
    if not _TRACKER.fullmatch(tracker):
        raise ConfigError("--tracker must contain only lowercase letters, digits, and hyphens")

    scaffold = _scaffold(name=name, ticket_prefix=prefix, tracker=tracker)
    created: list[str] = []
    overwritten: list[str] = []
    unchanged: list[str] = []
    conflicts: list[str] = []

    for relative, content in scaffold.items():
        target = _safe_target(root, relative)
        if not target.exists():
            created.append(relative)
        elif target.is_file() and target.read_text(encoding="utf-8") == content:
            unchanged.append(relative)
        elif target.is_dir():
            conflicts.append(relative)
        elif force:
            overwritten.append(relative)
        else:
            conflicts.append(relative)

    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        for relative in (*created, *overwritten):
            target = _safe_target(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, scaffold[relative])

    return InitResult(
        root=root,
        created=tuple(created),
        overwritten=tuple(overwritten),
        unchanged=tuple(unchanged),
        conflicts=tuple(conflicts),
        dry_run=dry_run,
    )


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ConfigError(f"scaffold path escapes project root: {relative}") from exc
    return target


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _scaffold(*, name: str, ticket_prefix: str, tracker: str) -> dict[str, str]:
    workflow_description = json.dumps(f"Deliver changes for {name} from planning through review.", ensure_ascii=False)
    config = f"""version: 1
default_workflow: default

ticket:
  prefix: {ticket_prefix}

tracker:
  provider: {tracker}
  transport: mcp
  options: {{}}

execution:
  mode: continuous
"""
    workflow = f"""version: 1
name: default
description: {workflow_description}
max_total_stages: 30

stages:
  - agent: planner
    retry:
      max_attempts: 2

  - skill: coding
    retry:
      max_attempts: 3

  - skill: testing
    retry:
      max_attempts: 2

  - agent: reviewer
    retry:
      max_attempts: 2
    remediation:
      skill: fixer
      max_cycles: 2
"""
    return {
        "lumos.yaml": config,
        "workflows/default.yaml": workflow,
        "agents/planner/AGENT.md": _agent(
            "planner",
            "Analyze the ticket and repository, then produce an implementation-ready plan.",
            "Inspect requirements and relevant code. Define scope, acceptance checks, risks, and an ordered "
            "implementation plan. Do not modify production code.",
        ),
        "agents/reviewer/AGENT.md": _agent(
            "reviewer",
            "Review implemented work against the ticket, plan, tests, and repository conventions.",
            "Inspect the complete diff and verification evidence. Report concrete defects with paths and impact. "
            "Route actionable findings to fixer; otherwise recommend completion.",
        ),
        "skills/coding/SKILL.md": _skill(
            "coding",
            "Implement the approved plan with focused production changes and proportionate tests.",
            "Read the planner output, inspect the affected code, implement the requested behavior, and run focused "
            "checks. Modify source and tests only within the ticket scope.",
        ),
        "skills/testing/SKILL.md": _skill(
            "testing",
            "Verify the implementation with automated tests, linting, formatting, and focused regression checks.",
            "Run the repository's relevant validation commands. Add or improve tests only when coverage is missing. "
            "Report exact commands and outcomes; do not conceal failures.",
        ),
        "skills/fixer/SKILL.md": _skill(
            "fixer",
            "Resolve only the concrete findings raised by a review stage.",
            "Use the review findings as a bounded checklist. Fix their root causes, add regression coverage where "
            "appropriate, and rerun affected checks without expanding scope.",
        ),
        "constraints/default.md": _CONSTRAINTS,
        "state/.gitignore": "*\n!.gitignore\n",
        "logs/.gitignore": "*\n!.gitignore\n",
        "runs/.gitignore": "*\n!.gitignore\n",
    }


def _skill(name: str, description: str, responsibility: str) -> str:
    return f"""---
name: {name}
description: {json.dumps(description)}
---

# {name}

{responsibility}

Use the supplied `Objective`, `Context`, `Constraints`, and `Previous Outputs` as authoritative input.

Return exactly these top-level sections, in order:

# Summary
# Findings
# Decisions
# Deliverables
# Risks
# Next Skill
"""


def _agent(name: str, description: str, responsibility: str) -> str:
    return f"""---
name: {name}
description: {json.dumps(description)}
---

# {name} agent

You are a delegated Lumos worker. {responsibility}

Work independently from the supplied `Objective`, `Context`, `Constraints`, and
`Previous Outputs`. Respect repository instructions and the declared scope.

Return exactly these top-level sections, in order:

# Summary
# Findings
# Decisions
# Deliverables
# Risks
# Next Skill
"""


_CONSTRAINTS = """# Project constraints

- Follow repository-local instructions and established conventions.
- Keep changes within the ticket scope; report unrelated work instead of silently expanding scope.
- Never place credentials or secrets in source, configuration, logs, or reports.
- Add proportionate tests for behavioral changes and report the exact verification commands run.
- Preserve user-authored changes and avoid destructive version-control operations.
- Return the six-section Lumos report contract required by each worker definition.
"""
