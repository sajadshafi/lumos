"""Domain model for the orchestration layer.

Pure data. No I/O, no logging, no filesystem — every other module depends on this
one, and nothing here depends on anything but the standard library. That keeps the
model trivially testable and prevents persistence concerns leaking into workflow
semantics.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class StageStatus(str, Enum):
    """Lifecycle of a single stage within one workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    ESCALATED = "escalated"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STAGE_STATUSES


_TERMINAL_STAGE_STATUSES = frozenset(
    {StageStatus.COMPLETED, StageStatus.SKIPPED, StageStatus.BLOCKED, StageStatus.ESCALATED}
)


class WorkflowStatus(str, Enum):
    """Lifecycle of the run as a whole."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_WORKFLOW_STATUSES


_TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.ESCALATED,
        WorkflowStatus.CANCELLED,
    }
)


class Action(str, Enum):
    """What the engine tells the orchestrator to do next.

    The engine never performs these; it only names them. The orchestrator skill
    reads the directive and acts.
    """

    INVOKE_SKILL = "invoke_skill"
    INVOKE_AGENT = "invoke_agent"
    AWAIT_APPROVAL = "await_approval"
    COMPLETE = "complete"
    ABORT = "abort"


class Verdict(str, Enum):
    """Normalised outcome of a skill invocation, derived from its report.

    `CHANGES_REQUESTED` is what turns a linear workflow into a loop: a review-type
    stage that routes to a remediation skill has not failed, it has found work.
    """

    SUCCESS = "success"
    CHANGES_REQUESTED = "changes_requested"
    FAILED = "failed"
    BLOCKED = "blocked"
    ESCALATE = "escalate"


@dataclass
class WorkUnit:
    """The unit of work driving a run — an issue, ticket, or task.

    The fields here are tracker-neutral: every issue tracker has an id, a title,
    a type, a state, a description and (usually) a URL. Anything specific to one
    tracker — an Azure DevOps area path, a Jira epic link, a GitHub label set —
    belongs in ``metadata``, which a ``TrackerAdapter`` populates and which skills
    may read through the input envelope. The engine never interprets it.
    """

    id: str
    title: str = ""
    type: str = ""
    state: str = ""
    description: str = ""
    url: str = ""
    acceptance_criteria: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkUnit:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# Backwards-compatible alias. The pre-open-source release named this ``WorkItem``;
# both names refer to the same class so existing callers keep working.
WorkItem = WorkUnit


@dataclass
class Attempt:
    """One invocation of one skill. Attempts are append-only — a retry never
    overwrites the record of what failed, because that history is the whole point
    of the log."""

    number: int
    started_at: float
    ended_at: float | None = None
    verdict: str | None = None
    report_path: str | None = None
    error: str | None = None
    summary: str = ""

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at is None:
            return None
        return round(self.ended_at - self.started_at, 3)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["duration_seconds"] = self.duration_seconds
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attempt:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Stage:
    """State of one skill within the run.

    `key` is the stage identity used by the engine and may differ from `skill`:
    a remediation stage that runs `fixer` on behalf of `reviewer` gets the key
    `fixer@reviewer`, so two independent fixer runs never collide in state.
    """

    key: str
    skill: str
    worker_type: str = "skill"
    status: str = StageStatus.PENDING.value
    attempts: list[Attempt] = field(default_factory=list)
    summary: str = ""
    deliverables: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_skill: str | None = None
    remediation_cycles: int = 0
    returns_to: str | None = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def current_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "skill": self.skill,
            "worker": self.skill,
            "worker_type": self.worker_type,
            "status": self.status,
            "attempts": [a.to_dict() for a in self.attempts],
            "summary": self.summary,
            "deliverables": list(self.deliverables),
            "decisions": list(self.decisions),
            "risks": list(self.risks),
            "next_skill": self.next_skill,
            "remediation_cycles": self.remediation_cycles,
            "returns_to": self.returns_to,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Stage:
        return cls(
            key=data["key"],
            skill=data["skill"],
            worker_type=data.get("worker_type", "skill"),
            status=data.get("status", StageStatus.PENDING.value),
            attempts=[Attempt.from_dict(a) for a in data.get("attempts", [])],
            summary=data.get("summary", ""),
            deliverables=list(data.get("deliverables", [])),
            decisions=list(data.get("decisions", [])),
            risks=list(data.get("risks", [])),
            next_skill=data.get("next_skill"),
            remediation_cycles=data.get("remediation_cycles", 0),
            returns_to=data.get("returns_to"),
        )


@dataclass
class WorkflowState:
    """The complete, durable record of one run.

    This is the single source of truth. If the process dies, this file is enough
    to resume — nothing lives only in the agent's context.
    """

    run_id: str
    work_item: WorkItem
    workflow_name: str
    status: str = WorkflowStatus.NOT_STARTED.value
    branch: str = ""
    repository: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stages: dict[str, Stage] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    current_step: str | None = None
    next_step: str | None = None
    pending_queue: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    contract_version: str = "1.0.0"
    schema_version: int = 1

    def stage(self, key: str) -> Stage | None:
        return self.stages.get(key)

    def require_stage(self, key: str) -> Stage:
        stage = self.stages.get(key)
        if stage is None:
            raise KeyError(f"unknown stage {key!r} in run {self.run_id}")
        return stage

    def record_error(self, stage_key: str, message: str, recoverable: bool) -> None:
        self.errors.append(
            {
                "at": time.time(),
                "stage": stage_key,
                "message": message,
                "recoverable": recoverable,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "branch": self.branch,
            "repository": self.repository,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "work_item": self.work_item.to_dict(),
            "current_step": self.current_step,
            "next_step": self.next_step,
            "order": list(self.order),
            "pending_queue": list(self.pending_queue),
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        return cls(
            run_id=data["run_id"],
            work_item=WorkItem.from_dict(data.get("work_item", {})),
            workflow_name=data["workflow_name"],
            status=data.get("status", WorkflowStatus.NOT_STARTED.value),
            branch=data.get("branch", ""),
            repository=data.get("repository", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            stages={k: Stage.from_dict(v) for k, v in data.get("stages", {}).items()},
            order=list(data.get("order", [])),
            current_step=data.get("current_step"),
            next_step=data.get("next_step"),
            pending_queue=list(data.get("pending_queue", [])),
            errors=list(data.get("errors", [])),
            contract_version=data.get("contract_version", "1.0.0"),
            schema_version=data.get("schema_version", 1),
        )


@dataclass
class Directive:
    """The engine's instruction to the orchestrator. Serialised to stdout as JSON
    so the calling agent parses one well-defined shape rather than prose."""

    action: str
    run_id: str
    stage_key: str | None = None
    skill: str | None = None
    worker: str | None = None
    worker_type: str | None = None
    attempt: int = 0
    max_attempts: int = 0
    reason: str = ""
    envelope_path: str | None = None
    workflow_status: str = WorkflowStatus.RUNNING.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
