"""Error taxonomy.

The split that matters is recoverable vs unrecoverable: a `RecoverableError` is
something a retry could plausibly fix (a malformed report, a transient skill
failure), while an `UnrecoverableError` means retrying burns budget for no reason
(the workflow config is invalid, the state file is corrupt, the skill is missing).
The retry policy branches on exactly this distinction.
"""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base for everything this package raises."""

    recoverable = False


class RecoverableError(OrchestratorError):
    recoverable = True


class UnrecoverableError(OrchestratorError):
    recoverable = False


class ConfigError(UnrecoverableError):
    """Workflow definition or orchestrator config is invalid."""


class StateError(UnrecoverableError):
    """State file is missing, corrupt, or from an incompatible schema."""


class SkillNotFoundError(UnrecoverableError):
    """A workflow names a skill with no discoverable SKILL.md."""


class ContractViolation(RecoverableError):
    """A skill report does not conform to shared/output-format.md.

    Recoverable because re-invoking the skill with the violation quoted back is a
    reasonable and frequently successful remedy.
    """

    def __init__(self, message: str, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class WorkflowAborted(UnrecoverableError):
    """The run cannot continue and no retry will help."""
