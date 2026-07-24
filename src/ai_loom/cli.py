"""Command-line interface — the boundary the orchestrator skill talks to.

Design rule: every command that the agent consumes emits **JSON on stdout**, and
every command a human consumes emits formatted text. Machine commands never
interleave prose into the payload, so the agent parses one shape and never has to
guess whether a line was data or commentary.

Exit codes are meaningful:

    0  success — the directive was produced
    1  usage / configuration error
    2  the run is in a terminal non-success state (failed, blocked, escalated)

The whole loop is:

    loom start TASK-17 --workflow default
    loom next  TASK-17               -> directive JSON + input envelope
    <agent invokes the named skill, writes its report to the given path>
    loom record TASK-17 --stage coding --report <path>   -> next directive
    ... repeat ...
    loom summary TASK-17
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import Paths, list_workflows, load_workflow
from .engine import Engine
from .errors import OrchestratorError
from .logging_ import RunLogger, iter_events, render_timeline
from .models import Action, StageStatus, Verdict, WorkflowState, WorkflowStatus, WorkItem
from .skill_runner import InvocationResult, SkillRunner
from .state_manager import StateManager
from .summary import render_final_summary, render_state_yaml, render_status

# Fallback constraints, injected into every skill envelope when the project ships
# no `constraints/default.md`. Kept deliberately generic and tracker-neutral:
# project-specific rules (a house style, a UI kit, an SDK) belong in that file,
# which `--constraints-file` can also override per run.
BUILTIN_CONSTRAINTS = """\
- Obey the write boundary declared in your SKILL.md without exception: only the
  skills a workflow authorises may modify source, tests, or docs.
- Emit the six-section report contract in order: Summary, Findings, Decisions,
  Deliverables, Risks, Next Skill.
- Keep every factual claim in Findings sourced to a path, symbol, command output,
  or an upstream report section.
- Do not expand scope silently. Work discovered mid-run that is outside the
  objective goes into Findings, not into the diff.
- Ship tests with any behavioural change, matching the surrounding conventions.
"""


def _load_constraints(paths: Paths, override_file: str | None) -> str:
    """Resolve the constraints block for a run.

    Precedence: an explicit ``--constraints-file`` wins; otherwise a project's
    ``constraints/default.md`` if present; otherwise the built-in generic block.
    """
    if override_file:
        return Path(override_file).read_text(encoding="utf-8")
    shipped = paths.root / "constraints" / "default.md"
    if shipped.is_file():
        return shipped.read_text(encoding="utf-8")
    return BUILTIN_CONSTRAINTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="Coordinate AI skills through a deterministic engineering workflow.",
    )
    parser.add_argument("--version", action="version", version=f"loom {__version__}")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="project root (defaults to $LOOM_PROJECT_DIR, then $CLAUDE_PROJECT_DIR, then discovery)",
    )
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="directory of skills (defaults to $LOOM_SKILLS_DIR, then ./skills, then examples/skills)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create or resume a run for a work item")
    start.add_argument("work_item")
    start.add_argument("--workflow", default="default")
    start.add_argument("--title", default="")
    start.add_argument("--type", dest="item_type", default="")
    start.add_argument("--state", dest="item_state", default="")
    start.add_argument("--description", default="")
    start.add_argument("--acceptance-criteria", default="")
    start.add_argument("--url", default="")
    start.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="tracker-specific field, repeatable (e.g. --metadata area_path=notes-api)",
    )
    start.add_argument("--branch", default="")
    start.add_argument("--repository", default="")
    start.add_argument("--force", action="store_true", help="discard any existing run and start clean")

    nxt = sub.add_parser("next", help="get the next directive and write its input envelope")
    nxt.add_argument("run")
    nxt.add_argument("--objective", default="", help="override the objective block")
    nxt.add_argument("--constraints-file", default=None)

    record = sub.add_parser("record", help="record a completed skill invocation")
    record.add_argument("run")
    record.add_argument("--stage", required=True)
    record.add_argument("--report", default=None, help="path to the skill's six-section report")
    record.add_argument("--failed", action="store_true", help="the skill could not run at all")
    record.add_argument("--error", default="", help="failure detail when --failed is used")

    for name, help_text in (
        ("status", "show run progress"),
        ("state", "print the state model as YAML"),
        ("summary", "render the final execution summary"),
        ("timeline", "print the execution timeline"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("run")

    approve = sub.add_parser("approve", help="clear a manual approval gate")
    approve.add_argument("run")
    approve.add_argument("--stage", required=True)

    skip = sub.add_parser("skip", help="skip a stage")
    skip.add_argument("run")
    skip.add_argument("--stage", required=True)
    skip.add_argument("--reason", required=True)

    cancel = sub.add_parser("cancel", help="cancel a run")
    cancel.add_argument("run")
    cancel.add_argument("--reason", default="cancelled by operator")

    sub.add_parser("runs", help="list known runs")
    sub.add_parser("skills", help="list discovered skills")

    workflows = sub.add_parser("workflows", help="list workflow definitions")
    workflows.add_argument("--validate", action="store_true", help="check every workflow against installed skills")

    validate = sub.add_parser("validate", help="validate one workflow definition")
    validate.add_argument("workflow")

    return parser


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def _engine(paths: Paths, run_id: str) -> Engine:
    manager = StateManager(paths)
    state = manager.load(run_id)
    definition = load_workflow(paths, state.workflow_name)
    return Engine(
        definition=definition,
        state=state,
        paths=paths,
        state_manager=manager,
        runner=SkillRunner(paths),
        logger=RunLogger(paths.log_file(run_id), run_id),
    )


def _emit_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _terminal_exit_code(state: WorkflowState) -> int:
    status = WorkflowStatus(state.status)
    if status in (WorkflowStatus.FAILED, WorkflowStatus.BLOCKED, WorkflowStatus.ESCALATED):
        return 2
    return 0


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_start(args: argparse.Namespace, paths: Paths) -> int:
    paths.ensure()
    definition = load_workflow(paths, args.workflow)

    runner = SkillRunner(paths)
    problems = runner.validate_workflow(definition.skills)
    if problems:
        _emit_json(
            {
                "ok": False,
                "error": "workflow references skills that cannot be invoked",
                "problems": problems,
            }
        )
        return 1

    manager = StateManager(paths)
    run_id = manager.run_id_for(args.work_item)
    if args.force:
        manager.delete(run_id)

    metadata: dict[str, str] = {}
    for pair in args.metadata:
        key, sep, value = str(pair).partition("=")
        if not sep or not key.strip():
            raise OrchestratorError(f"--metadata expects KEY=VALUE, got {pair!r}")
        metadata[key.strip()] = value.strip()

    item = WorkItem(
        id=args.work_item,
        title=args.title,
        type=args.item_type,
        state=args.item_state,
        description=args.description,
        acceptance_criteria=args.acceptance_criteria,
        url=args.url,
        metadata=metadata,
    )
    state, resumed = manager.load_or_create(
        item, definition, branch=args.branch, repository=args.repository
    )
    logger = RunLogger(paths.log_file(state.run_id), state.run_id)
    logger.emit(
        "workflow_resumed" if resumed else "workflow_started",
        status=state.status,
        detail={
            "workflow": definition.name,
            "stages": [s.skill for s in definition.stages],
            "work_item": item.id,
        },
    )
    _emit_json(
        {
            "ok": True,
            "run_id": state.run_id,
            "resumed": resumed,
            "workflow": definition.name,
            "stages": list(state.order),
            "status": state.status,
            "state_file": str(paths.state_file(state.run_id)),
            "log_file": str(paths.log_file(state.run_id)),
        }
    )
    return 0


def cmd_next(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, StateManager.run_id_for(args.run))
    directive = engine.next_directive()
    payload = directive.to_dict()

    if directive.action == Action.INVOKE_SKILL.value and directive.stage_key:
        stage = engine.state.require_stage(directive.stage_key)
        stage_def = engine.definition_for(directive.stage_key)

        # Only open a new attempt when the previous one closed, so repeatedly
        # calling `next` inspects the run rather than inflating the attempt count.
        open_attempt = stage.current_attempt
        if open_attempt is None or open_attempt.ended_at is not None:
            engine.state_manager.begin_attempt(engine.state, directive.stage_key)
            engine.logger.emit(
                "stage_started",
                stage=directive.stage_key,
                skill=directive.skill,
                status=StageStatus.RUNNING.value,
                attempt=stage.attempt_count,
            )

        constraints = _load_constraints(paths, args.constraints_file)

        request = engine.runner.build_request(
            engine.state, stage_def, stage, constraints, objective_override=args.objective
        )
        envelope = engine.runner.write_envelope(engine.state, request)
        report_path = engine.runner.report_path(engine.state, stage.key, request.attempt)

        payload.update(
            {
                "attempt": request.attempt,
                "skill_command": f"/{stage_def.skill}",
                "envelope_path": str(envelope),
                "report_path": str(report_path),
                "envelope": request.render(),
            }
        )
        engine.state_manager.save(engine.state)

    _emit_json(payload)
    if directive.action == Action.ABORT.value:
        return 2
    return 0


def cmd_record(args: argparse.Namespace, paths: Paths) -> int:
    run_id = StateManager.run_id_for(args.run)
    engine = _engine(paths, run_id)

    stage = engine.state.stage(args.stage)
    if stage is None:
        _emit_json({"ok": False, "error": f"unknown stage {args.stage!r}", "stages": list(engine.state.order)})
        return 1
    attempt_number = stage.attempt_count or 1

    if args.failed:
        result = InvocationResult(
            skill=stage.skill,
            stage_key=args.stage,
            attempt=attempt_number,
            verdict=Verdict.FAILED,
            error=args.error or "skill invocation failed",
        )
    else:
        if not args.report:
            _emit_json({"ok": False, "error": "--report is required unless --failed is given"})
            return 1
        report_file = Path(args.report)
        if not report_file.is_file():
            _emit_json({"ok": False, "error": f"report not found: {report_file}"})
            return 1
        origin_def = engine.definition.stage(args.stage)
        remediation_skill = origin_def.remediation.skill if origin_def and origin_def.remediation else None
        result = engine.runner.collect(
            stage_key=args.stage,
            skill=stage.skill,
            attempt=attempt_number,
            report_text=report_file.read_text(encoding="utf-8"),
            remediation_skill=remediation_skill,
            report_path=str(report_file),
        )

    status_map = {
        Verdict.SUCCESS: StageStatus.COMPLETED,
        Verdict.CHANGES_REQUESTED: StageStatus.COMPLETED,
        Verdict.FAILED: StageStatus.FAILED,
        Verdict.BLOCKED: StageStatus.BLOCKED,
        Verdict.ESCALATE: StageStatus.ESCALATED,
    }
    engine.state_manager.complete_attempt(
        engine.state,
        args.stage,
        verdict=result.verdict.value,
        status=status_map[result.verdict],
        summary=result.summary,
        report_path=result.report_path,
        error=result.error,
    )

    directive = engine.record(result)
    _emit_json(
        {
            "ok": result.succeeded,
            "verdict": result.verdict.value,
            "violations": result.violations,
            "recommended_next_skill": result.report.next_skill if result.report else None,
            "directive": directive.to_dict(),
        }
    )
    if directive.action == Action.ABORT.value:
        return 2
    return 0


def cmd_status(args: argparse.Namespace, paths: Paths) -> int:
    state = StateManager(paths).load(StateManager.run_id_for(args.run))
    print(render_status(state))
    return _terminal_exit_code(state)


def cmd_state(args: argparse.Namespace, paths: Paths) -> int:
    state = StateManager(paths).load(StateManager.run_id_for(args.run))
    print(render_state_yaml(state), end="")
    return 0


def cmd_summary(args: argparse.Namespace, paths: Paths) -> int:
    run_id = StateManager.run_id_for(args.run)
    state = StateManager(paths).load(run_id)
    events = list(iter_events(paths.log_file(run_id)))
    print(render_final_summary(state, events), end="")
    return _terminal_exit_code(state)


def cmd_timeline(args: argparse.Namespace, paths: Paths) -> int:
    run_id = StateManager.run_id_for(args.run)
    print(render_timeline(list(iter_events(paths.log_file(run_id)))))
    return 0


def cmd_approve(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, StateManager.run_id_for(args.run))
    directive = engine.approve(args.stage)
    _emit_json({"ok": True, "directive": directive.to_dict()})
    return 0


def cmd_skip(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, StateManager.run_id_for(args.run))
    directive = engine.skip(args.stage, args.reason)
    _emit_json({"ok": True, "directive": directive.to_dict()})
    return 0


def cmd_cancel(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, StateManager.run_id_for(args.run))
    directive = engine.cancel(args.reason)
    _emit_json({"ok": True, "directive": directive.to_dict()})
    return 0


def cmd_runs(args: argparse.Namespace, paths: Paths) -> int:
    manager = StateManager(paths)
    rows = []
    for run_id in manager.list_runs():
        try:
            state = manager.load(run_id)
        except OrchestratorError:
            rows.append({"run_id": run_id, "status": "unreadable"})
            continue
        rows.append(
            {
                "run_id": run_id,
                "work_item": state.work_item.id,
                "title": state.work_item.title,
                "workflow": state.workflow_name,
                "status": state.status,
                "current_step": state.current_step,
                "next_step": state.next_step,
            }
        )
    _emit_json({"ok": True, "runs": rows})
    return 0


def cmd_skills(args: argparse.Namespace, paths: Paths) -> int:
    discovered = SkillRunner(paths).discover()
    _emit_json(
        {
            "ok": True,
            "skills_dir": str(paths.skills_dir),
            "skills": [
                {"name": m.name, "invokable": m.invokable, "description": m.description, "path": str(m.path)}
                for m in discovered.values()
            ],
        }
    )
    return 0


def cmd_workflows(args: argparse.Namespace, paths: Paths) -> int:
    names = list_workflows(paths)
    if not args.validate:
        _emit_json({"ok": True, "workflows": names})
        return 0

    runner = SkillRunner(paths)
    results = []
    ok = True
    for name in names:
        try:
            definition = load_workflow(paths, name)
        except OrchestratorError as exc:
            ok = False
            results.append({"workflow": name, "valid": False, "problems": [str(exc)]})
            continue
        problems = runner.validate_workflow(definition.skills)
        ok = ok and not problems
        results.append(
            {
                "workflow": name,
                "valid": not problems,
                "stages": [s.skill for s in definition.stages],
                "problems": problems,
            }
        )
    _emit_json({"ok": ok, "workflows": results})
    return 0 if ok else 1


def cmd_validate(args: argparse.Namespace, paths: Paths) -> int:
    definition = load_workflow(paths, args.workflow)
    problems = SkillRunner(paths).validate_workflow(definition.skills)
    _emit_json(
        {
            "ok": not problems,
            "workflow": definition.name,
            "version": definition.version,
            "max_total_stages": definition.max_total_stages,
            "stages": [
                {
                    "skill": s.skill,
                    "max_attempts": s.retry.max_attempts,
                    "remediation": s.remediation.skill if s.remediation else None,
                    "max_cycles": s.remediation.max_cycles if s.remediation else None,
                    "requires_approval": s.requires_approval,
                    "optional": s.optional,
                }
                for s in definition.stages
            ],
            "problems": problems,
        }
    )
    return 0 if not problems else 1


COMMANDS = {
    "start": cmd_start,
    "next": cmd_next,
    "record": cmd_record,
    "status": cmd_status,
    "state": cmd_state,
    "summary": cmd_summary,
    "timeline": cmd_timeline,
    "approve": cmd_approve,
    "skip": cmd_skip,
    "cancel": cmd_cancel,
    "runs": cmd_runs,
    "skills": cmd_skills,
    "workflows": cmd_workflows,
    "validate": cmd_validate,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths.resolve(args.project_dir, skills_dir=args.skills_dir)
    try:
        return COMMANDS[args.command](args, paths)
    except OrchestratorError as exc:
        _emit_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__,
                    "recoverable": exc.recoverable})
        return 1


def main_cli() -> None:
    """Console-script entry point: run and translate the exit code into exit()."""
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    main_cli()
