# Getting started

This walks you from an empty checkout to a completed run, and explains the mental
model as you go. Fifteen minutes.

## 1. Install

```bash
pip install -e .        # from the repo root
loom --version
```

Python 3.9+. No required dependencies. If `pip` is not your thing, run the bundled
launcher instead: `bin/orchestrator …` behaves exactly like `loom …`.

## 2. The mental model

Three parties, and the whole design is about keeping them apart:

- **The engine** (Python) owns everything that must be exact: run state, attempt
  counts, retry budgets, loop ceilings, resume. It never calls a model.
- **The agent** (or you) owns judgment: reading the task, invoking a skill,
  deciding whether the output is real.
- **The workflow** (a YAML file) owns the plan: which skill runs, in what order.

The engine can't invoke a skill; the agent can't fudge a counter it never sees.
That boundary is what makes a long chain reliable instead of hopeful.

## 3. Run the hello-world chain

`examples/hello-world/` is a self-contained mini-project — a two-step
`draft → review` chain. Point `loom` at it:

```bash
HELLO=examples/hello-world

loom --project-dir $HELLO start GREETING-1 --workflow hello --title "Say hello"
```

That prints the run id and the stage list. Now ask what's next:

```bash
loom --project-dir $HELLO next GREETING-1
```

You get JSON: an `action` (`invoke_skill`), the `skill` to run (`draft`), an
`envelope_path` (the fully assembled input), and a `report_path` (where the
report must go). Read the envelope, do the skill's job, and write a six-section
report to `report_path`. For a first run you can hand-write a trivial one:

```markdown
# Summary
Drafted a greeting.
# Findings
- The objective asks for a hello.
# Decisions
- Kept it short.
# Deliverables
- "Hello, and welcome."
# Risks
None.
# Next Skill
review — the draft is ready to check.
```

Record it, and the engine advances:

```bash
loom --project-dir $HELLO record GREETING-1 --stage draft --report <report_path>
```

Repeat `next`/`record` for the `review` stage, then:

```bash
loom --project-dir $HELLO summary GREETING-1
```

## 4. What just happened

- You never told the engine that `review` follows `draft`. `hello.yaml` did.
- Each report was **validated** against the six-section contract before the run
  advanced. A malformed report re-queues the same stage — it never corrupts the
  next one.
- `state/`, `logs/`, and `runs/` appeared under the project dir. That is the
  durable record; if the process had died, `loom next GREETING-1` would have
  picked up exactly where it left off.

## 5. Next steps

- **Drive it with an agent** instead of by hand — see the drivers under
  [`adapters/`](../adapters/) (Claude Code, Copilot) and the neutral
  [`DRIVER-SPEC.md`](../adapters/DRIVER-SPEC.md).
- **Run the real pipeline.** The top-level `default` workflow chains
  `feature-planner → coding → testing → reviewer → post-feature-implementation`
  over the skills in [`examples/skills/`](../examples/skills/).
- **Author your own** — [skill authoring](skill-authoring.md) and
  [workflow design](workflow-design.md).
