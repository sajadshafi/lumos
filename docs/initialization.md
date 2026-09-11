# Project initialization

`lumos init` turns an empty or existing repository into a runnable Lumos
project. The generated files are deliberately small and editable: they provide
a sound workflow contract without prescribing a framework or programming
language.

## Quick start

From a project directory:

```bash
lumos init
lumos validate default
```

Or create a new directory:

```bash
lumos init my-project --name "My Project"
cd my-project
lumos validate default
```

The same operation can be requested inside a supported AI runtime:

```text
/lumos init
$lumos init my-project --ticket-prefix APP
```

The installed Lumos skill recognizes initialization as a setup action rather
than a ticket reference. It runs the CLI scaffolder and validates the resulting
default workflow.

## Generated structure

```text
lumos.yaml
workflows/
  default.yaml
agents/
  planner/AGENT.md
  reviewer/AGENT.md
skills/
  coding/SKILL.md
  testing/SKILL.md
  fixer/SKILL.md
constraints/
  default.md
state/.gitignore
logs/.gitignore
runs/.gitignore
```

The default workflow runs a planner agent, coding skill, testing skill, and
reviewer agent. Review findings route through the fixer skill and then return to
the reviewer. Execution mode is `continuous`, so ordinary stages do not require
separate continuation prompts.

Every generated worker follows Lumos's four-block input envelope and six-section
report contract. Replace their starter responsibilities with project-specific
instructions, tools, validation commands, and write boundaries.

## Options

```text
lumos init [directory]
  --name NAME
  --ticket-prefix PREFIX
  --tracker PROVIDER
  --dry-run
  --force
  --json
```

- `directory` defaults to the current directory. It may point to a directory
  that does not exist yet.
- `--name` changes the project description in the generated workflow.
- `--ticket-prefix` sets the prefix used for bare ticket numbers. It defaults to
  `TC`; both `APP` and `APP#` are accepted.
- `--tracker` selects a registered provider such as `local`, `github`, `jira`,
  `gitlab`, or `azure-devops`. Credentials are never written to the project.
- `--dry-run` reports every planned file without creating the target directory.
- `--json` returns a stable result containing `created`, `overwritten`,
  `unchanged`, and `conflicts` lists.
- `--force` overwrites only the known scaffold paths. Unrelated project files
  are never modified.

## Existing projects and conflicts

Initialization is idempotent. Running it again with the same options reports all
generated files as unchanged.

If a known scaffold path already contains different content, Lumos preserves
that file, creates any missing scaffold files, reports the conflict, and exits
non-zero. This makes partial adoption possible without silently destroying
project configuration. Review the existing file and generated neighbors, then
either reconcile it manually or explicitly run:

```bash
lumos init --force
```

`--force` is intentionally never implied by an AI prompt. The user must request
overwriting explicitly.

## Customizing the starter

Common first changes are:

1. Add repository-specific commands and write boundaries to each `SKILL.md` and
   `AGENT.md`.
2. Reorder or extend `workflows/default.yaml`.
3. Set the tracker provider and its non-secret options in `lumos.yaml`.
4. Add project policies to `constraints/default.md`.
5. Run `lumos workers`, `lumos validate default`, and `lumos doctor` before the
   first ticket.

See [Worker authoring](worker-authoring.md),
[Workflow design](workflow-design.md), and [Configuration](configuration.md)
for the complete contracts.
