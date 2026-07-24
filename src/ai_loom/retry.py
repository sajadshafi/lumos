"""Retry policy.

Retrying is a budget decision, not a reflex. Three rules govern it:

1. **Only recoverable failures are retried.** A missing SKILL.md or an invalid
   workflow will fail identically on attempt three; retrying it wastes tokens and
   buries the real error.
2. **Every stage declares its own budget.** A planner that failed twice is
   probably under-specified — more attempts will not fix the input. A testing
   stage legitimately wants more attempts, because each run produces new
   information.
3. **Remediation loops are capped separately from attempts.** `reviewer -> fixer
   -> reviewer` is not a retry; it is progress. It gets its own counter and its
   own ceiling, matching the "two full loops without convergence is an
   escalation" rule in shared/workflow-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Verdict

# Chosen to match shared/workflow-contract.md §5: two full loops without
# convergence escalates, so the third cycle is the escalation boundary.
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_MAX_REMEDIATION_CYCLES = 3


@dataclass(frozen=True)
class RetryPolicy:
    """Per-stage retry budget."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_on_contract_violation: bool = True
    retry_on_blocked: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    @classmethod
    def from_dict(cls, data: dict | None) -> RetryPolicy:
        if not data:
            return cls()
        return cls(
            max_attempts=int(data.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            retry_on_contract_violation=bool(data.get("retry_on_contract_violation", True)),
            retry_on_blocked=bool(data.get("retry_on_blocked", False)),
        )

    def should_retry(self, verdict: Verdict, attempts_used: int, recoverable: bool = True) -> bool:
        """Decide whether a stage gets another attempt.

        `attempts_used` counts attempts already completed, including the one that
        just produced `verdict`.
        """
        if attempts_used >= self.max_attempts:
            return False
        if not recoverable:
            return False
        if verdict is Verdict.FAILED:
            return True
        if verdict is Verdict.BLOCKED:
            # A blocker means the skill needs something a retry cannot supply.
            # Retrying is opt-in and off by default.
            return self.retry_on_blocked
        # SUCCESS, CHANGES_REQUESTED and ESCALATE are not failures — they advance
        # the workflow rather than repeating the stage.
        return False

    def attempts_remaining(self, attempts_used: int) -> int:
        return max(0, self.max_attempts - attempts_used)
