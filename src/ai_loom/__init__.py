"""AI skill orchestration layer.

A lightweight, deterministic workflow engine for coordinating AI-authored skills
through an engineering pipeline — plan, implement, test, review, remediate, ship
— independent of any particular agent runtime.

The orchestrator coordinates. It never implements: no module here writes
production source, and the only skills permitted to do so are named in the
workflow definition, not in this package.

Entry point: `python3 -m ai_loom --help` (or the installed `loom` command).
"""

from __future__ import annotations

__version__ = "0.1.0"
CONTRACT_VERSION = "1.0.0"

from .config import Paths, StageDefinition, WorkflowDefinition, load_workflow
from .engine import Engine
from .errors import (
    ConfigError,
    ContractViolation,
    OrchestratorError,
    SkillNotFoundError,
    StateError,
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
from .skill_runner import SkillRunner
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
    "RetryPolicy",
    "SkillNotFoundError",
    "SkillRunner",
    "StageDefinition",
    "StageStatus",
    "StateError",
    "StateManager",
    "Verdict",
    "WorkItem",
    "WorkUnit",
    "WorkflowDefinition",
    "WorkflowState",
    "WorkflowStatus",
    "load_workflow",
]
