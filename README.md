# Lumos

Lumos is an open-source, spec-driven workflow engine for AI coding tools. Define
an ordered pipeline in YAML, mix reusable **skills** with delegated **agents**,
and run a ticket from planning through implementation, testing, review,
remediation, and pull request creation without manually prompting each step.

The Python engine owns deterministic state, retries, loop ceilings, resume, and
report validation. Your AI runtime owns judgment and tool use. This split makes
the same workflow portable across Codex, Claude Code, Copilot, and other hosts.

## Install

Recommended installation from PyPI:

```bash
pipx install lumos
lumos install             # auto-detect Codex and Claude Code
lumos doctor
```

Until the first PyPI release, install the same CLI directly from GitHub:

```bash
pipx install git+https://github.com/sajadshafi/lumos.git
lumos install
lumos --version
```

For development:

```bash
git clone https://github.com/sajadshafi/lumos.git
cd lumos
python -m pip install -e .
lumos install codex --force
```

Install a single integration explicitly with `lumos install codex` or
`lumos install claude`. Use `lumos install --dry-run` to preview automatic
detection and [the installation guide](docs/installation.md) for update,
diagnostic, and safe-uninstall commands.

Restart or reload each configured AI runtime after installation. You can then run:

```text
/lumos TC#123
/lumos 123 --workflow hotfix
/lumos status TC#123
```

`loom` remains an alias for existing installations.

## Configure a project

Add `lumos.yaml` at the repository root:

```yaml
version: 1
default_workflow: default
ticket:
  prefix: TC
tracker:
  provider: local
  transport: mcp
  options: {}
execution:
  mode: continuous
```

`/lumos 123` and `/lumos #123` become `TC#123`. An explicit reference such as
`C3#123` is preserved. Change `ticket.prefix` to another alphanumeric prefix;
both `C3` and `C3#` are accepted in configuration.

`continuous` carries the loop through every stage in one turn and stops only on
completion, failure, a blocker, escalation, or a declared approval gate. `step`
executes one worker at a time for debugging.

## Mix skills and agents

```yaml
version: 1
name: delivery
max_total_stages: 30
stages:
  - agent: planner
    retry:
      max_attempts: 2
  - skill: coding
    retry:
      max_attempts: 3
  - agent: reviewer
    remediation:
      skill: fixer
      max_cycles: 2
  - skill: post-feature-implementation
```

- Skills live at `skills/<name>/SKILL.md` (included examples are the fallback).
- Agents live at `agents/<name>/AGENT.md` or `agents/<name>.md`.
- A stage may set `id:` when the same worker is used more than once.
- Remediation can target either type and returns to the worker that raised it.

Check configuration before spending model time:

```bash
lumos workers
lumos validate default
lumos workflows --validate
lumos trackers
```

## Continuous execution

The installed `/lumos` skill drives this machine-readable loop:

```text
start → next → invoke_skill/invoke_agent → record ─┐
          ▲                                        │
          └────────────────────────────────────────┘
                         │
                         └→ complete / abort / await_approval
```

Every worker receives the same four-block envelope (`Objective`, `Context`,
`Constraints`, `Previous Outputs`) and returns the same six-section report
(`Summary`, `Findings`, `Decisions`, `Deliverables`, `Risks`, `Next Skill`). Full
reports flow downstream and are validated before the workflow advances.

## Templates and documentation

- [`templates/skill/SKILL.md`](templates/skill/SKILL.md) — skill starter
- [`templates/agent/AGENT.md`](templates/agent/AGENT.md) — agent starter
- [`templates/workflow.yaml`](templates/workflow.yaml) — mixed workflow starter
- [Getting started](docs/getting-started.md)
- [Installation and runtime management](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Worker authoring](docs/worker-authoring.md)
- [Workflow design](docs/workflow-design.md)
- [Tracker integrations](docs/trackers.md)
- [Upcoming features and implementation roadmap](docs/upcoming-features.md)
- [Runtime driver contract](adapters/DRIVER-SPEC.md)
- [Contributing](CONTRIBUTING.md)

Lumos is licensed under [Apache-2.0](LICENSE).
