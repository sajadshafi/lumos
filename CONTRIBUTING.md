# Contributing to ai-loom

Thanks for helping. There are four things you can contribute, in rough order of
how often they're needed.

## 1. A skill

A skill is a directory with a `SKILL.md`. It accepts the four-block input envelope
and emits the six-section report contract. The bar is in
[`docs/skill-authoring.md`](docs/skill-authoring.md); the worked set under
[`examples/skills/`](examples/skills/) is the reference.

A skill is conformant when it:

- names any input block it requires, rather than inventing missing content;
- emits all six sections, in order, with the exact headings;
- keeps every factual claim in `Findings` sourced;
- respects its declared write boundary without exception;
- terminates with an explicit `Next Skill`, including the `None` cases;
- ships an `examples/input.md` + `examples/output.md` pair.

## 2. A workflow

Workflows are YAML under `workflows/`. Schema and worked examples are in
[`docs/workflow-design.md`](docs/workflow-design.md). Every skill a workflow names
must be invokable — check with `loom workflows --validate`.

## 3. A tracker adapter

Connect the engine to an issue tracker by subclassing `TrackerAdapter`
(`src/ai_loom/adapters/base.py`). Every method has a safe no-op default; override
only what your tracker supports. See `azure_devops.py` for a documented stub.
Register it with `register_adapter("name", YourAdapter)`.

## 4. A runtime driver

Bind the loop to a new agent runtime by implementing
[`adapters/DRIVER-SPEC.md`](adapters/DRIVER-SPEC.md). Drivers are documentation +
prompts, not engine code — the engine already speaks a neutral CLI.

## Core changes

The engine is deliberately small and dependency-free. Before adding to it:

- **No third-party runtime dependencies.** The standard library is the budget.
  PyYAML is optional, behind `yamlcompat`.
- **No hardcoded skill names or ordering** in the engine. If a change needs one,
  it belongs in a workflow file, not in Python.
- **Keep the boundary.** The engine never invokes a model or a skill; drivers do.

## Testing

```bash
python -m unittest discover -s tests -t tests     # expect: OK
```

Every behavioural change ships with a test. The suite uses stdlib `unittest` (not
pytest) and runs in well under a second. The highest-value tests are the loop
tests in `tests/test_engine.py` — they are what stop a runaway from being
discovered on a real token budget.

Lint/format (optional but CI-checked):

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
```

## Commit and PR guidance

- One logical change per PR. A new skill, a new adapter, and an engine fix are
  three PRs.
- Describe the behaviour change and how you verified it. If tests fail, say so.
- Match the surrounding style; the codebase favours clear names and short
  functions over cleverness.

By contributing you agree your work is licensed under [Apache-2.0](LICENSE).
