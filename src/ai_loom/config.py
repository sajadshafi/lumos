"""Configuration: filesystem layout and workflow definitions.

A workflow is data, not code. Adding `security-review` to a pipeline is a
four-line YAML edit, and the engine that executes it never changes. That is the
extensibility requirement, enforced structurally: nothing in this package
contains a hardcoded skill name or a hardcoded ordering.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlcompat
from .errors import ConfigError
from .retry import DEFAULT_MAX_REMEDIATION_CYCLES, RetryPolicy

# Global ceiling on stage executions per run. A misconfigured remediation loop
# should surface as a clear abort, not as an unbounded token spend.
DEFAULT_MAX_TOTAL_STAGES = 40
WORKER_TYPES = frozenset({"skill", "agent"})


@dataclass(frozen=True)
class Remediation:
    """How a stage routes findings to a fixing skill and back.

    `skill` runs when the stage reports changes requested; control then returns
    to the stage that raised them, so the party that objected verifies the fix —
    shared/workflow-contract.md §5.
    """

    skill: str
    kind: str = "skill"
    max_cycles: int = DEFAULT_MAX_REMEDIATION_CYCLES

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Remediation | None:
        if not data:
            return None
        kind, skill = _parse_worker(data, context="remediation block")
        cycles = int(data.get("max_cycles", DEFAULT_MAX_REMEDIATION_CYCLES))
        if cycles < 1:
            raise ConfigError("remediation.max_cycles must be at least 1")
        return cls(skill=skill, kind=kind, max_cycles=cycles)

    @property
    def worker(self) -> str:
        return self.skill


@dataclass(frozen=True)
class StageDefinition:
    """One stage of a workflow definition."""

    skill: str
    kind: str = "skill"
    id: str = ""
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    remediation: Remediation | None = None
    requires_approval: bool = False
    optional: bool = False
    description: str = ""

    @property
    def key(self) -> str:
        return self.id or self.skill

    @property
    def worker(self) -> str:
        return self.skill

    @classmethod
    def from_dict(cls, data: Any) -> StageDefinition:
        # `- coding` is shorthand for `- skill: coding` with defaults.
        if isinstance(data, str):
            return cls(skill=data)
        if not isinstance(data, dict):
            raise ConfigError(f"stage entry must be a string or mapping, got {type(data).__name__}")
        kind, skill = _parse_worker(data, context="stage entry")
        return cls(
            skill=skill,
            kind=kind,
            id=str(data.get("id", "") or ""),
            retry=RetryPolicy.from_dict(data.get("retry")),
            remediation=Remediation.from_dict(data.get("remediation")),
            requires_approval=bool(data.get("requires_approval", False)),
            optional=bool(data.get("optional", False)),
            description=str(data.get("description", "") or ""),
        )


@dataclass(frozen=True)
class WorkflowDefinition:
    """A named, ordered pipeline of stages."""

    name: str
    stages: tuple[StageDefinition, ...]
    version: int = 1
    description: str = ""
    max_total_stages: int = DEFAULT_MAX_TOTAL_STAGES

    def stage(self, key: str) -> StageDefinition | None:
        for stage in self.stages:
            if stage.key == key:
                return stage
        return None

    @property
    def skills(self) -> tuple[str, ...]:
        """Every skill the workflow can invoke (legacy discovery API)."""
        names: list[str] = []
        for stage in self.stages:
            if stage.kind == "skill":
                names.append(stage.skill)
            if stage.remediation and stage.remediation.kind == "skill":
                names.append(stage.remediation.skill)
        return tuple(dict.fromkeys(names))

    @property
    def workers(self) -> tuple[tuple[str, str], ...]:
        """Every (type, name) worker referenced by the workflow."""
        workers: list[tuple[str, str]] = []
        for stage in self.stages:
            workers.append((stage.kind, stage.worker))
            if stage.remediation:
                workers.append((stage.remediation.kind, stage.remediation.worker))
        return tuple(dict.fromkeys(workers))

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_name: str = "") -> WorkflowDefinition:
        if not isinstance(data, dict):
            raise ConfigError("workflow file must contain a mapping at the top level")

        # Accept both `stages:` and the flatter `workflow:` form from the design doc.
        raw_stages = data.get("stages")
        if raw_stages is None:
            raw_stages = data.get("workflow")
        if raw_stages is None:
            raise ConfigError("workflow file must define 'stages' (or 'workflow')")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise ConfigError("'stages' must be a non-empty list")

        stages = tuple(StageDefinition.from_dict(entry) for entry in raw_stages)

        seen: set[str] = set()
        for stage in stages:
            if stage.key in seen:
                raise ConfigError(
                    f"duplicate stage {stage.key!r}: stage ids must be unique in state; "
                    "set an explicit 'id' when reusing a worker"
                )
            seen.add(stage.key)

        name = str(data.get("name") or fallback_name or "unnamed")
        max_total = int(data.get("max_total_stages", DEFAULT_MAX_TOTAL_STAGES))
        if max_total < len(stages):
            raise ConfigError("max_total_stages cannot be smaller than the number of stages")

        return cls(
            name=name,
            stages=stages,
            version=int(data.get("version", 1)),
            description=str(data.get("description", "") or ""),
            max_total_stages=max_total,
        )


@dataclass(frozen=True)
class Paths:
    """Filesystem layout, resolved once and injected everywhere.

    Nothing in the package calls `Path.cwd()` or reads globals; tests construct a
    `Paths` over a temp directory and the whole system relocates.
    """

    root: Path
    skills_dir: Path
    agents_dir: Path
    workflows_dir: Path
    state_dir: Path
    logs_dir: Path
    runs_dir: Path

    @classmethod
    def resolve(
        cls,
        project_dir: str | os.PathLike[str] | None = None,
        *,
        skills_dir: str | os.PathLike[str] | None = None,
        agents_dir: str | os.PathLike[str] | None = None,
    ) -> Paths:
        """Resolve the flat, standalone project layout.

        ``workflows/``, ``skills/``, ``state/``, ``logs/`` and ``runs/`` live
        directly under the project root. The skills directory is the one piece
        an integration commonly relocates (a runtime may keep skills elsewhere),
        so it is independently overridable — by argument, then the
        ``LOOM_SKILLS_DIR`` environment variable, then a sensible default.
        """
        base = Path(project_dir) if project_dir else _discover_project_dir()
        skills = cls._resolve_skills_dir(base, skills_dir)
        agents = cls._resolve_agents_dir(base, agents_dir)
        return cls(
            root=base,
            skills_dir=skills,
            agents_dir=agents,
            workflows_dir=base / "workflows",
            state_dir=base / "state",
            logs_dir=base / "logs",
            runs_dir=base / "runs",
        )

    @staticmethod
    def _resolve_skills_dir(base: Path, skills_dir: str | os.PathLike[str] | None) -> Path:
        if skills_dir:
            return Path(skills_dir)
        env = os.environ.get("LUMOS_SKILLS_DIR") or os.environ.get("LOOM_SKILLS_DIR")
        if env:
            return Path(env)
        # A repo may vendor its own `skills/`; the shipped examples otherwise
        # provide a runnable default so a fresh clone works with no config.
        local = base / "skills"
        if local.is_dir():
            return local
        bundled = base / "examples" / "skills"
        if bundled.is_dir():
            return bundled
        return local

    @staticmethod
    def _resolve_agents_dir(base: Path, agents_dir: str | os.PathLike[str] | None) -> Path:
        if agents_dir:
            return Path(agents_dir)
        env = os.environ.get("LUMOS_AGENTS_DIR")
        if env:
            return Path(env)
        local = base / "agents"
        if local.exists():
            return local
        bundled = base / "examples" / "agents"
        return bundled if bundled.exists() else local

    def ensure(self) -> None:
        for directory in (self.state_dir, self.logs_dir, self.runs_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def state_file(self, run_id: str) -> Path:
        return self.state_dir / f"{run_id}.state.json"

    def log_file(self, run_id: str) -> Path:
        return self.logs_dir / f"{run_id}.jsonl"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id


def _discover_project_dir() -> Path:
    """Locate the project root.

    ``LOOM_PROJECT_DIR`` wins when set; ``CLAUDE_PROJECT_DIR`` is honoured next so
    the tool still works dropped inside a Claude Code project. Otherwise walk up
    looking for a marker that identifies a project root.
    """
    for var in ("LUMOS_PROJECT_DIR", "LOOM_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        env = os.environ.get(var)
        if env:
            return Path(env)
    current = Path.cwd().resolve()
    markers = ("workflows", ".git", "pyproject.toml", ".claude")
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return current


@dataclass(frozen=True)
class TrackerConfig:
    """Non-secret project configuration for one tracker adapter."""

    provider: str = "local"
    transport: str = "mcp"
    options: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LumosConfig:
    """Project-level defaults shared by every runtime driver."""

    ticket_prefix: str = "TC"
    default_workflow: str = "default"
    execution_mode: str = "continuous"
    tracker: TrackerConfig = field(default_factory=TrackerConfig)


def load_project_config(paths: Paths) -> LumosConfig:
    """Load ``lumos.yaml`` when present, otherwise return portable defaults."""
    path = paths.root / "lumos.yaml"
    if not path.is_file():
        return LumosConfig()
    try:
        data = yamlcompat.load(path.read_text(encoding="utf-8")) or {}
    except yamlcompat.YamlError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    ticket = data.get("ticket", {}) or {}
    execution = data.get("execution", {}) or {}
    tracker = data.get("tracker", {}) or {}
    if not isinstance(tracker, dict):
        raise ConfigError("tracker must be a mapping")
    raw_options = tracker.get("options", {}) or {}
    if not isinstance(raw_options, dict):
        raise ConfigError("tracker.options must be a mapping")
    options = {str(key): str(value) for key, value in raw_options.items()}
    _reject_secret_options(options)
    prefix = str(ticket.get("prefix", "TC") or "TC").strip().upper().removesuffix("#")
    if not prefix or not prefix.isalnum():
        raise ConfigError("ticket.prefix must contain only letters and digits")
    mode = str(execution.get("mode", "continuous") or "continuous").lower()
    if mode not in {"continuous", "step"}:
        raise ConfigError("execution.mode must be 'continuous' or 'step'")
    return LumosConfig(
        ticket_prefix=prefix,
        default_workflow=str(data.get("default_workflow", "default") or "default"),
        execution_mode=mode,
        tracker=TrackerConfig(
            provider=str(tracker.get("provider", "local") or "local").strip().lower(),
            transport=str(tracker.get("transport", "mcp") or "mcp").strip().lower(),
            options=options,
        ),
    )


def resolve_tracker_config(
    config: LumosConfig,
    *,
    provider: str | None = None,
    transport: str | None = None,
    options: list[str] | None = None,
) -> TrackerConfig:
    """Apply CLI > environment > project > local tracker precedence."""
    env_provider = os.environ.get("LUMOS_TRACKER")
    env_transport = os.environ.get("LUMOS_TRACKER_TRANSPORT")
    merged = dict(config.tracker.options)
    env_prefix = "LUMOS_TRACKER_OPTION_"
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            merged[key[len(env_prefix) :].lower()] = value
    for pair in options or []:
        key, sep, value = str(pair).partition("=")
        if not sep or not key.strip():
            raise ConfigError(f"--tracker-option expects KEY=VALUE, got {pair!r}")
        merged[key.strip()] = value.strip()
    _reject_secret_options(merged)
    return TrackerConfig(
        provider=str(provider or env_provider or config.tracker.provider or "local").strip().lower(),
        transport=str(transport or env_transport or config.tracker.transport or "mcp").strip().lower(),
        options=merged,
    )


def _reject_secret_options(options: dict[str, str]) -> None:
    forbidden = ("token", "password", "secret", "credential", "api_key", "apikey", "authorization")
    bad = sorted(key for key in options if any(word in key.casefold() for word in forbidden))
    if bad:
        raise ConfigError(
            "tracker secrets must come from the runtime connection or environment, not lumos.yaml/options: "
            + ", ".join(bad)
        )


def normalize_work_item(reference: str, prefix: str = "TC") -> str:
    """Return the canonical ``PREFIX#NUMBER`` form used by slash invocations."""
    token = str(reference).strip().upper()
    if token.isdigit():
        return f"{prefix.upper()}#{token}"
    if token.startswith("#") and token[1:].isdigit():
        return f"{prefix.upper()}{token}"
    if "#" in token:
        head, sep, number = token.partition("#")
        if head.isalnum() and number.isdigit() and sep:
            return f"{head}#{number}"
    # Preserve legacy tracker ids such as TASK-17; adapters may normalise them.
    return token


def _parse_worker(data: dict[str, Any], *, context: str) -> tuple[str, str]:
    present = [key for key in ("skill", "agent", "worker") if data.get(key)]
    if len(present) != 1:
        raise ConfigError(f"{context} requires exactly one of 'skill', 'agent', or 'worker'")
    key = present[0]
    if key == "worker":
        raw = data[key]
        if isinstance(raw, dict):
            kind = str(raw.get("type", "") or "").lower()
            name = str(raw.get("name", "") or "")
        else:
            kind = str(data.get("type", "skill") or "skill").lower()
            name = str(raw)
    else:
        kind, name = key, str(data[key])
    if kind not in WORKER_TYPES:
        raise ConfigError(f"{context} worker type must be 'skill' or 'agent'")
    if not name.strip():
        raise ConfigError(f"{context} worker name cannot be empty")
    return kind, name.strip()


def load_workflow(paths: Paths, name: str) -> WorkflowDefinition:
    """Load a workflow by name from the workflows directory."""
    candidates = [
        paths.workflows_dir / f"{name}.yaml",
        paths.workflows_dir / f"{name}.yml",
        Path(name),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                data = yamlcompat.load(candidate.read_text(encoding="utf-8"))
            except yamlcompat.YamlError as exc:
                raise ConfigError(f"{candidate}: {exc}") from exc
            return WorkflowDefinition.from_dict(data or {}, fallback_name=candidate.stem)

    available = sorted(p.stem for p in paths.workflows_dir.glob("*.y*ml")) if paths.workflows_dir.is_dir() else []
    raise ConfigError(
        f"workflow {name!r} not found in {paths.workflows_dir}. "
        f"Available: {', '.join(available) if available else 'none'}"
    )


def list_workflows(paths: Paths) -> list[str]:
    if not paths.workflows_dir.is_dir():
        return []
    return sorted({p.stem for p in paths.workflows_dir.glob("*.y*ml")})
