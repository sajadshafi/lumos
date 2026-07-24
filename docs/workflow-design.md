# Workflow design

A workflow is a pipeline expressed as data. It names the skills to run, in order,
with their retry budgets and any remediation loops or approval gates. Nothing in
the engine hardcodes a skill name or an order — adding a stage is a YAML edit.

This is the practical guide. For the exhaustive field reference and validation
rules, see [`workflows.md`](workflows.md).

## The shape

```yaml
version: 1                    # schema version of this file
name: default                 # identity; defaults to the filename
description: A one-line summary.
max_total_stages: 40          # runaway guard: total stage executions per run

stages:
  - skill: feature-planner    # required — must match a skills/<name>/ with a SKILL.md
    description: What this stage is for (shown in the directive).
    retry:
      max_attempts: 2         # per-stage attempt budget (default 2)

  - skill: reviewer
    retry:
      max_attempts: 2
    remediation:              # a review loop
      skill: fixer            #   reviewer → fixer → reviewer …
      max_cycles: 3           #   … capped at 3 before escalation
```

A bare string is shorthand for a stage with defaults: `- coding` ==
`- skill: coding`.

## The four things a stage can do

| Field | Effect |
|---|---|
| `retry.max_attempts` | How many times a stage may run before it fails. Budgets are deliberately non-uniform — a plan that failed twice is under-specified, but testing earns more tries because each run yields new information. |
| `remediation` | Turns a stage into a loop: on *changes requested*, the engine runs the `remediation.skill` (e.g. `fixer`), then re-runs the stage to verify. `max_cycles` caps it — the contract's rule is that two loops without convergence is a human decision. |
| `requires_approval: true` | The engine pauses **before** the stage and returns `await_approval`. It resumes only after `loom approve <run> --stage <key>`. |
| `optional: true` | An optional stage that exhausts its retries is recorded failed, but the run continues instead of failing. |

## Two counters, kept separate

`retry.max_attempts` and `remediation.max_cycles` count different things and never
share a budget:

- **Retries** handle a stage that *failed to produce acceptable output* (a
  malformed report, a blocker). The same stage runs again with the reason quoted
  in.
- **Remediation cycles** handle a stage that *worked but requested changes*. A
  different skill runs, then control returns. Two contested cycles is the ceiling;
  a third automated attempt buries the decision a human needs to make.

## Shipped workflows

| Workflow | Stages | Runnable | For |
|---|---|---|---|
| `default` | planner → coding → testing → reviewer ⇄ fixer → post-impl | yes | Normal feature delivery |
| `hotfix` | coding → testing → reviewer ⇄ fixer → post-impl | yes | A defect with a known cause |
| `plan-only` | planner | yes | Scoping and estimation |
| `full-review` | + security, performance, approval gate | **no** | The template for a fuller pipeline |

`full-review` intentionally fails `loom workflows --validate`: its `security` and
`performance` skills ship as directories with a README but no `SKILL.md`. That is
the proof that turning them on is skill-authoring, not an engine change.

## Author and validate

```bash
# workflows/docs-only.yaml
loom validate docs-only          # check this one workflow against installed skills
loom workflows --validate        # check them all; lists what is runnable
```

Every skill a workflow names — including remediation skills — must be invokable,
or `start` refuses to run it. Validation reports every problem at once, before any
tokens are spent.
