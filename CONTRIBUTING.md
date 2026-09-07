# Contributing to Lumos

Contributions to workers, workflows, runtime drivers, tracker adapters, the
engine, tests, and documentation are welcome.

## Development setup

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
ruff check src tests
```

The runtime engine has no required third-party dependency. Keep Python 3.9
compatibility and preserve the standard-library YAML fallback.

## Adding a worker

Copy the appropriate file from `templates/skill/` or `templates/agent/`, rename
it, define a precise write boundary, and return the standard six-section report.
Add it to a workflow and run `lumos validate <workflow>`.

Agents use `agents/<name>/AGENT.md` (or a flat `.md` file); skills use
`skills/<name>/SKILL.md`. Do not hide runtime-specific assumptions in the core
engine—put them in an adapter.

## Design invariants

- Workflow order is data; do not hardcode worker names in Python.
- The engine owns state, retries, remediation, resume, and validation.
- Runtime drivers invoke workers and must continue in `continuous` mode.
- Full reports cross stage boundaries verbatim.
- Human approval gates cannot be approved by the orchestrator.
- Existing 0.1 skill-only workflows and `loom` CLI usage remain compatible.

Add behavior-focused tests for every engine or CLI change. Keep changes scoped,
document new configuration, and explain compatibility impact in the PR.
