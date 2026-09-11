"""Lumos spec-driven orchestration engine.

A lightweight, deterministic workflow engine for coordinating AI-authored workers
through an engineering pipeline — plan, implement, test, review, remediate, ship
— independent of any particular agent runtime.

The orchestrator coordinates. It never implements: no module here writes
production source, and the only workers permitted to do so are named in the
workflow definition, not in this package.

Entry point: `python3 -m lumos --help` (or the installed `lumos` command).
"""

from __future__ import annotations

__version__ = "0.5.0"
CONTRACT_VERSION = "1.0.0"

from .config import (
    LumosConfig,
    Paths,
    StageDefinition,
    TrackerConfig,
    WorkflowDefinition,
    load_project_config,
    load_workflow,
)
from .engine import Engine
from .errors import (
    ConfigError,
    ContractViolation,
    OrchestratorError,
    SkillNotFoundError,
    StateError,
    TrackerAuthenticationError,
    TrackerError,
    TrackerNotFoundError,
    TrackerPermissionError,
    TrackerThrottledError,
    TrackerUnavailableError,
    UnsupportedCapabilityError,
)
from .models import (
    Action,
    Directive,
    StageStatus,
    Verdict,
    WorkflowState,
    WorkflowStatus,
    WorkItem,
    WorkUnit,
)
from .retry import RetryPolicy
from .skill_runner import SkillRunner, WorkerRunner
from .state_manager import StateManager

__all__ = [
    "__version__",
    "CONTRACT_VERSION",
    "Action",
    "ConfigError",
    "ContractViolation",
    "Directive",
    "Engine",
    "OrchestratorError",
    "Paths",
    "LumosConfig",
    "TrackerConfig",
    "RetryPolicy",
    "SkillNotFoundError",
    "SkillRunner",
    "WorkerRunner",
    "StageDefinition",
    "StageStatus",
    "StateError",
    "StateManager",
    "TrackerAuthenticationError",
    "TrackerError",
    "TrackerNotFoundError",
    "TrackerPermissionError",
    "TrackerThrottledError",
    "TrackerUnavailableError",
    "UnsupportedCapabilityError",
    "Verdict",
    "WorkItem",
    "WorkUnit",
    "WorkflowDefinition",
    "WorkflowState",
    "WorkflowStatus",
    "load_workflow",
    "load_project_config",
]
