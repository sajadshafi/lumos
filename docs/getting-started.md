# Getting started

## 1. Install Lumos and its runtime skill

```bash
pipx install git+https://github.com/sajadshafi/lumos.git
lumos install codex
```

Use `lumos install claude` for Claude Code. Restart the runtime so it discovers
the `/lumos` skill.

## 2. Initialize a project

Run the initializer at your repository root:

```bash
cd your-project
lumos init
lumos workers
lumos validate default
```

The generated project contains an editable mixed workflow, two agents, three
skills, default constraints, and ignored state directories. Existing scaffold
files are preserved. See [Project initialization](initialization.md) to select a
ticket prefix or tracker, preview changes, and handle conflicts.

## 3. Run a ticket

```text
/lumos TC#123
```

In continuous mode that single request runs the configured pipeline to a
terminal result. Planning, coding, testing, review, fixer loops, documentation,
and PR creation do not need separate “continue” prompts. Lumos pauses only for a
declared approval gate or information a worker genuinely needs from you.

Bare numbers use the configured prefix:

```text
/lumos 123                 # TC#123 by default
/lumos C3#123              # explicit prefixes pass through
/lumos 123 --workflow hotfix
```

## 4. Inspect or resume

```text
/lumos status TC#123
/lumos resume TC#123
```

The engine writes durable state under `state/`, logs under `logs/`, and exact
worker envelopes/reports under `runs/`. A resumed run continues at the open
stage without incrementing its attempt merely for being inspected.

Next: [configuration](configuration.md), [worker authoring](worker-authoring.md),
and [workflow design](workflow-design.md).
