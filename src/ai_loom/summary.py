"""Human-facing renderers: run status and final execution summary.

Kept apart from the engine so presentation can change without touching workflow
semantics, and so `status` output can be reshaped without risking a state bug.
"""

from __future__ import annotations

import time
from typing import Any

from . import yamlcompat
from .logging_ import render_timeline
from .models import StageStatus, WorkflowState, WorkflowStatus

_ICONS = {
    StageStatus.PENDING.value: "·",
    StageStatus.RUNNING.value: "▸",
    StageStatus.COMPLETED.value: "✓",
    StageStatus.FAILED.value: "✗",
    StageStatus.BLOCKED.value: "⊘",
    StageStatus.SKIPPED.value: "»",
    StageStatus.ESCALATED.value: "!",
}


def render_state_yaml(state: WorkflowState) -> str:
    """The state model in the shape the design document specifies.

    JSON is the durable record; this is the readable projection of it.
    """
    view: dict[str, Any] = {
        "feature": {
            "id": state.work_item.id,
            "title": state.work_item.title,
            "type": state.work_item.type,
            "branch": state.branch,
        },
        "workflow": state.workflow_name,
        "status": {key: stage.status for key, stage in state.stages.items()},
        "current_step": state.current_step,
        "next_step": state.next_step,
        "attempts": {key: stage.attempt_count for key, stage in state.stages.items() if stage.attempts},
        "summary": {key: stage.summary for key, stage in state.stages.items() if stage.summary},
        "artifacts": {
            key: stage.deliverables for key, stage in state.stages.items() if stage.deliverables
        },
        "errors": [
            {"stage": e["stage"], "message": e["message"], "recoverable": e["recoverable"]}
            for e in state.errors
        ],
        "workflow_status": state.status,
    }
    return yamlcompat.dump(view)


def render_status(state: WorkflowState) -> str:
    """Compact progress board for a run."""
    item = state.work_item
    header = [
        f"Run        {state.run_id}",
        f"Work item  {item.id}" + (f" — {item.title}" if item.title else ""),
        f"Workflow   {state.workflow_name}",
        f"Branch     {state.branch or '(none)'}",
        f"Status     {state.status.upper()}",
        f"Updated    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(state.updated_at))}",
        "",
        "Stages",
    ]
    rows = []
    for key in state.order:
        stage = state.stages.get(key)
        if stage is None:
            continue
        icon = _ICONS.get(stage.status, "?")
        marker = " <- current" if key == state.current_step and not WorkflowStatus(state.status).is_terminal else ""
        attempts = f"{stage.attempt_count} attempt(s)" if stage.attempts else "not run"
        cycles = f", {stage.remediation_cycles} remediation cycle(s)" if stage.remediation_cycles else ""
        rows.append(f"  {icon} {key:<32} {stage.status:<12} {attempts}{cycles}{marker}")

    footer = []
    if state.pending_queue:
        footer += ["", "Queue      " + " -> ".join(state.pending_queue)]
    if state.errors:
        footer += ["", "Errors"]
        for err in state.errors[-5:]:
            flag = "recoverable" if err["recoverable"] else "unrecoverable"
            footer.append(f"  [{flag}] {err['stage']}: {err['message']}")
    return "\n".join(header + rows + footer)


def render_final_summary(state: WorkflowState, events: list[dict[str, Any]]) -> str:
    """Markdown execution summary — the run's deliverable to a human.

    Written to be pasteable into an issue tracker comment (an Azure DevOps work
    item, a GitHub issue, a Jira ticket) or a chat message.
    """
    item = state.work_item
    status = WorkflowStatus(state.status)
    verdict = {
        WorkflowStatus.COMPLETED: "Completed successfully",
        WorkflowStatus.FAILED: "Failed",
        WorkflowStatus.BLOCKED: "Blocked — needs input",
        WorkflowStatus.ESCALATED: "Escalated — needs a human decision",
        WorkflowStatus.CANCELLED: "Cancelled",
        WorkflowStatus.AWAITING_APPROVAL: "Paused at a manual approval point",
        WorkflowStatus.RUNNING: "In progress",
        WorkflowStatus.NOT_STARTED: "Not started",
    }[status]

    total_attempts = sum(stage.attempt_count for stage in state.stages.values())
    durations = [
        a.duration_seconds
        for stage in state.stages.values()
        for a in stage.attempts
        if a.duration_seconds is not None
    ]
    wall = state.updated_at - state.created_at

    lines = [
        f"# Orchestration summary — {item.id}",
        "",
        f"**{verdict}.** Workflow `{state.workflow_name}` ran "
        f"{len([s for s in state.stages.values() if s.attempts])} of {len(state.order)} stages "
        f"across {total_attempts} skill invocation(s) in {_duration(wall)}.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run | `{state.run_id}` |",
        f"| Work item | {item.id}{' — ' + item.title if item.title else ''} |",
        f"| Branch | `{state.branch or 'none'}` |",
        f"| Contract | v{state.contract_version} |",
        f"| Skill time | {_duration(sum(durations))} |",
        "",
        "## Stage results",
        "",
        "| Stage | Skill | Status | Attempts | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]

    for key in state.order:
        stage = state.stages.get(key)
        if stage is None:
            continue
        summary = (stage.summary or "—").replace("\n", " ").replace("|", "\\|")
        if len(summary) > 160:
            summary = summary[:157] + "..."
        lines.append(
            f"| `{key}` | `{stage.skill}` | {stage.status} | {stage.attempt_count} | {summary} |"
        )

    deliverables = [(k, d) for k in state.order for d in (state.stages[k].deliverables if k in state.stages else [])]
    if deliverables:
        lines += ["", "## Deliverables", ""]
        lines += [f"- **{key}** — {d}" for key, d in deliverables]

    decisions = [(k, d) for k in state.order for d in (state.stages[k].decisions if k in state.stages else [])]
    if decisions:
        lines += ["", "## Decisions", ""]
        lines += [f"- **{key}** — {d}" for key, d in decisions]

    risks = [(k, r) for k in state.order for r in (state.stages[k].risks if k in state.stages else [])]
    if risks:
        lines += ["", "## Outstanding risks", ""]
        lines += [f"- **{key}** — {r}" for key, r in risks]

    if state.errors:
        lines += ["", "## Errors", ""]
        for err in state.errors:
            flag = "recoverable" if err["recoverable"] else "unrecoverable"
            lines.append(f"- `{err['stage']}` ({flag}) — {err['message']}")

    lines += ["", "## Execution timeline", "", "```", render_timeline(events), "```"]

    if not status.is_terminal:
        lines += ["", f"_Run is still open. Continue with_ `orchestrator next {state.run_id}`."]

    return "\n".join(lines) + "\n"


def _duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
