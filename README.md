# ai-loom

**A deterministic engine for sequencing AI skills into reliable engineering
workflows.**

> ⚠️ `ai-loom` is a working title. The engine, contract, and CLI are stable; the
> name is not yet final.

You have skills — focused prompts that plan, implement, test, or review. Chaining
them by hand is where reliability goes to die: context gets dropped between steps,
a bad output slips downstream, a review loop runs forever, and a crash loses the
thread. `ai-loom` is the part that makes a chain *dependable*. It owns the state,
the retries, the loop ceilings, and the hand-off contract, so your skills only
have to do their one job.

It is **runtime-neutral**: the engine never calls a model. It hands an agent a
markdown envelope, the agent runs the skill and writes a report, and the engine
validates it. Anything that can run a CLI and read and write a file can drive it —
Claude Code, GitHub Copilot, a script, or a person.

---

## How it differs from a prompt runner

A prompt runner sends prompts and hopes. `ai-loom` splits the work along the one
line that matters — **determinism vs. judgment** — and refuses to let either side
do the other's job:

| Concern | Owned by | Why |
|---|---|---|
| State, attempt counts, retry budgets, loop ceilings, resume | **the Python engine** | These must be exact. An agent that counts its own retries will miscount. |
| Reading the task, invoking a skill, judging output | **the agent** | These need judgment. Code cannot tell a real plan from a plausible one. |
| The workflow: which skill runs, in what order | **a YAML file** | So adding a stage is a config edit, not a code change. |

The engine cannot invoke a skill; the agent cannot fudge a counter it never sees.
That boundary is the whole design.

---

## Install

```bash
pip install -e .        # from a checkout; PyPI release to follow
loom --version
```

Python 3.9+. No required dependencies — the standard library is enough. (PyYAML is
used if present; otherwise a bundled parser handles the workflow files.)

You can also run straight from a checkout with no install: `bin/orchestrator …`.

## Quickstart

The two-step `hello-world` chain shows the whole loop in miniature:

```bash
HELLO=examples/hello-world

loom --project-dir $HELLO start GREETING-1 --workflow hello --title "Say hello"
loom --project-dir $HELLO next  GREETING-1     # → directive + input envelope
#   read the envelope, act as the named skill, write a six-section report
loom --project-dir $HELLO record GREETING-1 --stage draft --report <path>
#   … repeat for the next stage …
loom --project-dir $HELLO summary GREETING-1
```

Full walkthrough: [`examples/hello-world/README.md`](examples/hello-world/README.md).

## The loop

Every run is the same six-verb cycle. The agent drives it; the engine decides.

```
start ──► next ──► (agent invokes the skill, writes a report) ──► record ──┐
            ▲                                                               │
            └───────────────────────────────────────────────────────────  ┘
                              until complete / blocked / escalated
                                        │
                                        └──► summary
```

`next` returns a directive **and** a fully assembled four-block input envelope
(objective, context, constraints, every upstream report). `record` validates the
returned report against the six-section contract and computes the verdict —
success, changes-requested, blocked, or escalate — then tells the agent what comes
next. Retries and remediation loops are the engine's business; the agent just
invokes what it is told.

---

## Two models you author

**Workflows** are data. A stage names a skill, a retry budget, and an optional
remediation loop:

```yaml
version: 1
name: default
max_total_stages: 40
stages:
  - skill: feature-planner
    retry: { max_attempts: 2 }
  - skill: coding
    retry: { max_attempts: 3 }
  - skill: reviewer
    retry: { max_attempts: 2 }
    remediation:            # reviewer → fixer → reviewer, capped
      skill: fixer
      max_cycles: 3
```

Nothing in the engine hardcodes a skill name or an order. Adding `security-review`
is a YAML edit. See [`docs/workflow-design.md`](docs/workflow-design.md).

**Skills** are directories with a `SKILL.md`. Each accepts the four-block envelope
and emits the same six sections — `Summary`, `Findings`, `Decisions`,
`Deliverables`, `Risks`, `Next Skill` — so any skill's output is any other skill's
input. See [`docs/skill-authoring.md`](docs/skill-authoring.md) and the worked
set under [`examples/skills/`](examples/skills/).

---

## Works with your agent runtime

The engine is a CLI boundary; a **driver** binds that loop to a specific runtime.
Drivers live under [`adapters/`](adapters/):

- **[`adapters/DRIVER-SPEC.md`](adapters/DRIVER-SPEC.md)** — the runtime-neutral
  contract. Implement it for any agent (or a human).
- **[`adapters/claude-code/`](adapters/claude-code/)** — a Claude Code skill that
  drives the loop with the Skill tool.
- **[`adapters/copilot/`](adapters/copilot/)** — a GitHub Copilot instructions
  file that drives the same loop with shell + file I/O.

Issue trackers are pluggable too: a `TrackerAdapter`
([`src/ai_loom/adapters/`](src/ai_loom/adapters/)) connects the engine to Azure
DevOps, GitHub, Jira — or **nothing at all**. The default is `local`: the work
unit is supplied on the command line and no external system is touched.

---

## Layout

```
ai-loom/
├── src/ai_loom/          # the engine (standard library only)
│   └── adapters/         # tracker adapters: local (default), azure-devops stub
├── adapters/             # runtime drivers: DRIVER-SPEC, claude-code, copilot
├── workflows/            # default · hotfix · plan-only · full-review
├── constraints/          # default constraints injected into every envelope
├── examples/
│   ├── skills/           # a full worked skill set
│   ├── shared/           # the workflow + output contracts
│   └── hello-world/      # the minimal runnable chain
├── docs/                 # architecture, state model, authoring guides
└── tests/                # 129 tests, stdlib unittest
```

## Boundaries

The orchestrator will not: write production source (only skills a workflow
authorises do that), execute a skill outside the runner, decide the workflow
itself, approve its own gates, or fabricate a report when a skill fails to produce
one. `blocked` and `escalated` are legitimate terminal outcomes — reporting one
honestly beats forcing a green run.

## Docs

| Document | Covers |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | Install, first run, the mental model |
| [`docs/skill-authoring.md`](docs/skill-authoring.md) | Writing a conformant skill |
| [`docs/workflow-design.md`](docs/workflow-design.md) | The workflow YAML schema |
| [`docs/architecture.md`](docs/architecture.md) | Components, dependency rules, lifecycle |
| [`docs/state-model.md`](docs/state-model.md) · [`docs/retry-and-errors.md`](docs/retry-and-errors.md) | State, resume, retries, escalation |
| [`docs/faq.md`](docs/faq.md) | Common questions |

## Contributing

Skills, workflows, tracker adapters, and runtime drivers are all welcome. See
[`CONTRIBUTING.md`](CONTRIBUTING.md). Licensed under [Apache-2.0](LICENSE).
