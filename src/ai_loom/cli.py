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

    lumos start TASK-17 --workflow default
    lumos next  TASK-17               -> directive JSON + input envelope
    <runtime invokes the named worker, writes its report to the given path>
    lumos record TASK-17 --stage coding --report <path>   -> next directive
    ... repeat ...
    lumos summary TASK-17
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import create_adapter, list_adapters
from .config import (
    Paths,
    list_workflows,
    load_project_config,
    load_workflow,
    normalize_work_item,
    resolve_tracker_config,
)
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
- Obey the write boundary declared in your SKILL.md or AGENT.md: only workers a
  workflow authorises may modify source, tests, or docs.
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
        prog="lumos",
        description="Run AI skills and agents through deterministic spec-driven workflows.",
    )
    parser.add_argument("--version", action="version", version=f"lumos {__version__}")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="project root (defaults to $LUMOS_PROJECT_DIR, legacy $LOOM_PROJECT_DIR, then discovery)",
    )
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="directory of skills (defaults to $LUMOS_SKILLS_DIR, then ./skills, then examples/skills)",
    )
    parser.add_argument(
        "--agents-dir",
        default=None,
        help="directory of agents (defaults to $LUMOS_AGENTS_DIR, then ./agents, then examples/agents)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create or resume a run for a work item")
    start.add_argument("work_item")
    start.add_argument("--workflow", default=None, help="workflow name (defaults to lumos.yaml)")
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
    start.add_argument("--tracker", default=None, help="tracker provider (local, github, jira, gitlab, azure-devops)")
    start.add_argument("--tracker-transport", default=None, help="tracker transport (mcp or rest)")
    start.add_argument(
        "--tracker-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="non-secret provider option; repeatable and overrides lumos.yaml",
    )
    start.add_argument("--force", action="store_true", help="discard any existing run and start clean")

    nxt = sub.add_parser("next", help="get the next directive and write its input envelope")
    nxt.add_argument("run")
    nxt.add_argument("--objective", default="", help="override the objective block")
    nxt.add_argument("--constraints-file", default=None)

    record = sub.add_parser("record", help="record a completed worker invocation")
    record.add_argument("run")
    record.add_argument("--stage", required=True)
    record.add_argument("--report", default=None, help="path to the worker's six-section report")
    record.add_argument("--failed", action="store_true", help="the worker could not run at all")
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
    sub.add_parser("agents", help="list discovered agents")
    sub.add_parser("workers", help="list all discovered skills and agents")
    sub.add_parser("trackers", help="show tracker providers, capabilities, and selected connection")

    publish = sub.add_parser("publish", help="publish a run summary and optional PR/status to its tracker")
    publish.add_argument("run")
    publish.add_argument("--pr-url", default="")
    publish.add_argument("--transition", default="")
    publish.add_argument("--tracker", default=None)
    publish.add_argument("--tracker-transport", default=None)
    publish.add_argument("--tracker-option", action="append", default=[], metavar="KEY=VALUE")

    workflows = sub.add_parser("workflows", help="list workflow definitions")
    workflows.add_argument("--validate", action="store_true", help="check every workflow against installed workers")

    validate = sub.add_parser("validate", help="validate one workflow definition")
    validate.add_argument("workflow")

    install = sub.add_parser("install", help="install the /lumos skill into an AI runtime")
    install.add_argument("runtime", choices=("codex", "claude"))
    install.add_argument("--destination", default=None, help="override the runtime skill directory")
    install.add_argument("--force", action="store_true", help="replace an existing Lumos skill")

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


def _run_id(paths: Paths, reference: str) -> str:
    config = load_project_config(paths)
    tracker = resolve_tracker_config(config)
    adapter = create_adapter(tracker.provider, transport=tracker.transport, options=tracker.options)
    normalized = (
        normalize_work_item(reference, config.ticket_prefix)
        if tracker.provider == "local"
        else adapter.normalise_id(reference) or reference
    )
    return StateManager.run_id_for(normalized)


def _emit_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _infer_github_repository(root: Path) -> str:
    """Resolve ``owner/repository`` from the current Git origin when possible."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    remote = result.stdout.strip().removesuffix(".git")
    match = re.search(r"(?:[:/])([^/:]+/[^/]+)$", remote)
    return match.group(1) if result.returncode == 0 and match else ""


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
    config = load_project_config(paths)
    definition = load_workflow(paths, args.workflow or config.default_workflow)

    runner = SkillRunner(paths)
    problems = runner.validate_workers(definition.workers)
    if problems:
        _emit_json(
            {
                "ok": False,
                "error": "workflow references workers that cannot be invoked",
                "problems": problems,
            }
        )
        return 1

    tracker_config = resolve_tracker_config(
        config, provider=args.tracker, transport=args.tracker_transport, options=args.tracker_option
    )
    if tracker_config.provider == "github" and not tracker_config.options.get("repository"):
        inferred = _infer_github_repository(paths.root)
        if inferred:
            tracker_config = replace(tracker_config, options={**tracker_config.options, "repository": inferred})
    adapter = create_adapter(
        tracker_config.provider, transport=tracker_config.transport, options=tracker_config.options
    )
    raw_reference = args.work_item
    work_item = (
        normalize_work_item(raw_reference, config.ticket_prefix)
        if tracker_config.provider == "local"
        else adapter.normalise_id(raw_reference) or raw_reference
    )
    manager = StateManager(paths)
    run_id = manager.run_id_for(work_item)

    metadata: dict[str, str] = {}
    for pair in args.metadata:
        key, sep, value = str(pair).partition("=")
        if not sep or not key.strip():
            raise OrchestratorError(f"--metadata expects KEY=VALUE, got {pair!r}")
        metadata[key.strip()] = value.strip()

    if tracker_config.provider == "local":
        item = WorkItem(id=work_item)
    else:
        item = adapter.fetch(raw_reference)
    # Explicit CLI fields are intentional overrides of provider data. Empty
    # values preserve the fetched fields.
    item.title = args.title or item.title
    item.type = args.item_type or item.type
    item.state = args.item_state or item.state
    item.description = args.description or item.description
    item.acceptance_criteria = args.acceptance_criteria or item.acceptance_criteria
    item.url = args.url or item.url
    item.metadata.update(metadata)
    item.metadata.setdefault("provider", tracker_config.provider)
    item.metadata["tracker_transport"] = tracker_config.transport
    item.metadata["tracker_options"] = json.dumps(tracker_config.options, sort_keys=True)
    if args.force:
        manager.delete(run_id)
    state, resumed = manager.load_or_create(item, definition, branch=args.branch, repository=args.repository)
    logger = RunLogger(paths.log_file(state.run_id), state.run_id)
    logger.emit(
        "workflow_resumed" if resumed else "workflow_started",
        status=state.status,
        detail={
            "workflow": definition.name,
            "stages": [f"{s.kind}:{s.worker}" for s in definition.stages],
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
            "execution_mode": config.execution_mode,
            "tracker": {
                "provider": tracker_config.provider,
                "transport": adapter.transport_name,
                "capabilities": adapter.capabilities.to_dict(),
            },
            "state_file": str(paths.state_file(state.run_id)),
            "log_file": str(paths.log_file(state.run_id)),
        }
    )
    return 0


def cmd_next(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, _run_id(paths, args.run))
    directive = engine.next_directive()
    payload = directive.to_dict()
    payload["execution_mode"] = load_project_config(paths).execution_mode

    if directive.action in (Action.INVOKE_SKILL.value, Action.INVOKE_AGENT.value) and directive.stage_key:
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
                "worker": stage_def.worker,
                "worker_type": stage_def.kind,
                "skill_command": f"/{stage_def.skill}" if stage_def.kind == "skill" else None,
                "agent_path": str(engine.runner.get(stage_def.worker, "agent").path)
                if stage_def.kind == "agent"
                else None,
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
    run_id = _run_id(paths, args.run)
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
            error=args.error or "worker invocation failed",
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
    state = StateManager(paths).load(_run_id(paths, args.run))
    print(render_status(state))
    return _terminal_exit_code(state)


def cmd_state(args: argparse.Namespace, paths: Paths) -> int:
    state = StateManager(paths).load(_run_id(paths, args.run))
    print(render_state_yaml(state), end="")
    return 0


def cmd_summary(args: argparse.Namespace, paths: Paths) -> int:
    run_id = _run_id(paths, args.run)
    state = StateManager(paths).load(run_id)
    events = list(iter_events(paths.log_file(run_id)))
    print(render_final_summary(state, events), end="")
    return _terminal_exit_code(state)


def cmd_timeline(args: argparse.Namespace, paths: Paths) -> int:
    run_id = _run_id(paths, args.run)
    print(render_timeline(list(iter_events(paths.log_file(run_id)))))
    return 0


def cmd_approve(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, _run_id(paths, args.run))
    directive = engine.approve(args.stage)
    _emit_json({"ok": True, "directive": directive.to_dict()})
    return 0


def cmd_skip(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, _run_id(paths, args.run))
    directive = engine.skip(args.stage, args.reason)
    _emit_json({"ok": True, "directive": directive.to_dict()})
    return 0


def cmd_cancel(args: argparse.Namespace, paths: Paths) -> int:
    engine = _engine(paths, _run_id(paths, args.run))
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


def cmd_agents(args: argparse.Namespace, paths: Paths) -> int:
    discovered = SkillRunner(paths).discover_agents()
    _emit_json(
        {
            "ok": True,
            "agents_dir": str(paths.agents_dir),
            "agents": [
                {"name": m.name, "invokable": m.invokable, "description": m.description, "path": str(m.path)}
                for m in discovered.values()
            ],
        }
    )
    return 0


def cmd_workers(args: argparse.Namespace, paths: Paths) -> int:
    runner = SkillRunner(paths)
    skills = runner.discover()
    agents = runner.discover_agents()
    _emit_json(
        {
            "ok": True,
            "workers": [
                {
                    "type": kind,
                    "name": m.name,
                    "invokable": m.invokable,
                    "description": m.description,
                    "path": str(m.path),
                }
                for kind, group in (("skill", skills), ("agent", agents))
                for m in group.values()
            ],
        }
    )
    return 0


def cmd_trackers(args: argparse.Namespace, paths: Paths) -> int:
    config = load_project_config(paths)
    selected = resolve_tracker_config(config)
    rows = []
    for name, adapter_cls in sorted(list_adapters().items()):
        adapter = create_adapter(name, transport=selected.transport, options=selected.options)
        rows.append(
            {
                "provider": name,
                "selected": name == selected.provider,
                "transport": adapter.transport_name,
                "connected": True if name == "local" else adapter.connected,
                "capabilities": adapter_cls.capabilities.to_dict(),
            }
        )
    _emit_json({"ok": True, "selected": selected.provider, "trackers": rows})
    return 0


def cmd_publish(args: argparse.Namespace, paths: Paths) -> int:
    config = load_project_config(paths)
    state = StateManager(paths).load(_run_id(paths, args.run))
    provider = args.tracker or state.work_item.metadata.get("provider") or None
    saved_transport = state.work_item.metadata.get("tracker_transport") or None
    tracker_config = resolve_tracker_config(
        config,
        provider=provider,
        transport=args.tracker_transport or saved_transport,
        options=args.tracker_option,
    )
    # Repository/project context resolved from a ticket URL must survive into a
    # later publish process. Provider metadata contains only non-secret values.
    options = dict(tracker_config.options)
    try:
        options.update(json.loads(state.work_item.metadata.get("tracker_options", "{}")))
    except (TypeError, json.JSONDecodeError):
        pass
    for key in ("repository", "project"):
        if state.work_item.metadata.get(key):
            options.setdefault(key, state.work_item.metadata[key])
    adapter = create_adapter(tracker_config.provider, transport=tracker_config.transport, options=options)
    if tracker_config.provider == "local":
        _emit_json({"ok": True, "provider": "local", "operations": [], "message": "local tracker has no remote writes"})
        return 0
    operations = []
    skipped = []
    if adapter.capabilities.comment:
        events = list(iter_events(paths.log_file(state.run_id)))
        adapter.comment(state.work_item.id, render_final_summary(state, events))
        operations.append("comment")
    else:
        skipped.append("comment")
    if args.pr_url and adapter.capabilities.link_pull_request:
        adapter.link_pull_request(state.work_item.id, args.pr_url)
        operations.append("link_pull_request")
    elif args.pr_url:
        skipped.append("link_pull_request")
    if args.transition and adapter.capabilities.transition:
        adapter.transition(state.work_item.id, args.transition)
        operations.append("transition")
    elif args.transition:
        skipped.append("transition")
    _emit_json({"ok": True, "provider": tracker_config.provider, "operations": operations, "skipped": skipped})
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
        problems = runner.validate_workers(definition.workers)
        ok = ok and not problems
        results.append(
            {
                "workflow": name,
                "valid": not problems,
                "stages": [{"id": s.key, "type": s.kind, "worker": s.worker} for s in definition.stages],
                "problems": problems,
            }
        )
    _emit_json({"ok": ok, "workflows": results})
    return 0 if ok else 1


def cmd_validate(args: argparse.Namespace, paths: Paths) -> int:
    definition = load_workflow(paths, args.workflow)
    problems = SkillRunner(paths).validate_workers(definition.workers)
    _emit_json(
        {
            "ok": not problems,
            "workflow": definition.name,
            "version": definition.version,
            "max_total_stages": definition.max_total_stages,
            "stages": [
                {
                    "skill": s.skill,
                    "worker": s.worker,
                    "type": s.kind,
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


def cmd_install(args: argparse.Namespace, paths: Paths) -> int:
    if args.destination:
        destination = Path(args.destination).expanduser()
    elif args.runtime == "codex":
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        destination = codex_home / "skills" / "lumos"
    else:
        destination = Path.home() / ".claude" / "skills" / "lumos"

    skill_file = destination / "SKILL.md"
    if skill_file.exists() and not args.force:
        _emit_json(
            {
                "ok": False,
                "error": f"Lumos is already installed at {destination}; use --force to update it",
            }
        )
        return 1

    source = resources.files("ai_loom").joinpath("resources", "lumos")
    destination.joinpath("agents").mkdir(parents=True, exist_ok=True)
    skill_file.write_text(source.joinpath("SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    destination.joinpath("agents", "openai.yaml").write_text(
        source.joinpath("agents", "openai.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _emit_json({"ok": True, "runtime": args.runtime, "installed": str(destination)})
    return 0


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
    "agents": cmd_agents,
    "workers": cmd_workers,
    "trackers": cmd_trackers,
    "publish": cmd_publish,
    "workflows": cmd_workflows,
    "validate": cmd_validate,
    "install": cmd_install,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths.resolve(args.project_dir, skills_dir=args.skills_dir, agents_dir=args.agents_dir)
    try:
        return COMMANDS[args.command](args, paths)
    except OrchestratorError as exc:
        _emit_json({"ok": False, "error": str(exc), "error_type": type(exc).__name__, "recoverable": exc.recoverable})
        return 1


def main_cli() -> None:
    """Console-script entry point: run and translate the exit code into exit()."""
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    main_cli()
