# Skill Runner Specification

`orchestrator/skill_runner.py` — the only component that knows how a skill is
addressed, what it must be given, and whether what came back is acceptable.

---

## 1. What "running" a skill means here

The Skill Runner does **not** spawn a process. In this hybrid architecture the
executor is Claude Code itself, via the Skill tool, because a skill needs
repository context, tool permissions, and model judgment that a Python subprocess
cannot supply. Shelling out to `claude -p` per stage would discard that context
and re-derive it at significant cost.

So the runner owns everything *around* execution:

```
locate → load metadata → build the input envelope
                                ↓
                    ( the agent invokes the skill )
                                ↓
       validate the report → normalise a verdict → fold into state
```

This boundary is stated plainly rather than hidden behind a fake subprocess API.
The requirement it actually protects — "the orchestrator never executes skills
directly" — is fully met: every invocation goes through one component, with one
envelope format, one validator, and one logging path.

---

## 2. Discovery

```python
runner.discover() -> dict[str, SkillMetadata]
```

Scans `examples/skills/*/`, excluding `shared/`.

| Directory contains | Result |
| --- | --- |
| `SKILL.md` with frontmatter | `invokable=True`, name and description read from frontmatter |
| No `SKILL.md` | `invokable=False` — reported, not hidden |

Inert directories are surfaced rather than skipped, so a workflow naming a stub
skill fails with an explanation instead of a bare `KeyError`:

```
skill 'security' exists at examples/skills/security but has no SKILL.md, so it is
inert. Write its SKILL.md or remove it from the workflow definition.
```

Frontmatter is read with a line scan, not a YAML parser — it is a flat key/value
map, and keeping the parser out of discovery avoids a dependency in the hot path.

### Pre-flight validation

```python
runner.validate_workflow(definition.skills) -> list[str]
```

Called at `start`, before any tokens are spent. Returns every problem at once —
a typo in the workflow costs a second, not three stages of progress.

---

## 3. Envelope construction

The runner builds the four-block input envelope from
`shared/workflow-contract.md` §1:

```markdown
## Objective

Users can page through their notes without loading the whole list.

## Context

- Work item: TASK-17 — Paginate the notes list
- Work item type: Feature
- Branch: feat/task-17-paginate-notes
- Repository: notes-api
- Workflow: default
- Stage: coding (attempt 2 of 3)
- Contract version: 1.0.0

Acceptance criteria:
…

The previous attempt (#1) was rejected: report does not conform to the output
contract: missing required section(s): # Risks
Correct that specific problem. Do not restart the work from scratch.

## Constraints

- The project's non-negotiable rules apply in full (see constraints/default.md)…

## Previous Outputs

### Report from `feature-planner` (stage `feature-planner`)

<the planner's complete, unedited report>
```

### Three rules the construction enforces

**Full upstream reports, never summaries.** Contract §1 is explicit: a skill
given a paraphrase re-derives the repository state and drifts from the plan it is
meant to implement. The runner reads report files from disk and concatenates
them oldest-first.

**Retries carry their reason.** A retried skill is told exactly why the last
attempt was rejected. Re-invoking with no explanation usually reproduces the same
failure — the prior error is the single most useful thing to pass forward.

**Remediation runs state their narrow remit.** A `fixer@reviewer` envelope says
so explicitly, and names the stage that will verify the work. This is what keeps
the fixer from expanding scope.

### Persistence

Every envelope is written before invocation:

```
runs/TASK-17/coding/attempt-2.input.md
runs/TASK-17/coding/attempt-2.report.md
```

A resumed run therefore reproduces the exact input a skill was given, which is
what makes a failed stage debuggable after the fact.

---

## 4. Report validation

```python
runner.collect(stage_key, skill, attempt, report_text, remediation_skill) -> InvocationResult
```

Delegates to `report.parse`, which enforces contract 1.0.0:

| Check | Failure mode caught |
| --- | --- |
| All six `#` sections present | A skill that dropped `# Risks` |
| Sections in contract order | A skill that reorganised the report |
| `# Summary` non-empty | A stage that did nothing but said it did |
| `# Next Skill` non-empty | A chain with no declared terminus |

Tolerant of cosmetic variation (heading case, trailing punctuation, `##`
subsections nested inside a section) and strict about structure. Per contract §6,
non-conformant output is a defect in the skill — so it is detected loudly rather
than silently accepted.

Validation **never raises**. A malformed report is data the caller must decide
about, and the retry policy needs the violation list to quote back to the skill.

---

## 5. Verdict derivation

The verdict is derived from the report, not asserted by the agent. If the agent
could declare success, contract validation would be advisory.

```python
derive_verdict(report, remediation_skill) -> Verdict
```

| Report state | Verdict |
| --- | --- |
| Non-conformant | `FAILED` |
| `Next Skill` mentions escalation | `ESCALATE` |
| `Next Skill: None` + a blocking marker | `BLOCKED` |
| `Next Skill` names the stage's remediation skill | `CHANGES_REQUESTED` |
| Anything else | `SUCCESS` |

### Precedence is deliberate

`ESCALATE` beats `BLOCKED` beats `CHANGES_REQUESTED`. A report saying
*"fixer — escalate, we disagree"* must not be read as "loop again" — that is
precisely the failure the escalation rule exists to prevent.

### `Next Skill` extraction

Handles the forms skills actually emit:

```
coding                                    → coding
`post-feature-implementation`             → post-feature-implementation
fixer — three findings above severity 2   → fixer
- reviewer                                → reviewer
None — blocked, need the fee schedule     → None
Whatever the team decides                 → None  (not a skill identifier)
```

The token must match `[a-z][a-z0-9-]*`, matching the kebab-case naming rule in
`examples/skills/README.md`. Prose that names no skill resolves to `None` rather
than to a bogus stage name.

---

## 6. Folding into state

```python
runner.apply(stage, result)
```

Extracts bullets from `# Deliverables`, `# Decisions`, and `# Risks` into the
stage record, plus the summary and the recommended next skill. These feed the
final execution summary, so a run's decisions and outstanding risks are collected
without anyone re-reading six reports.

---

## 7. What the runner does not do

- **Decide what happens next.** It normalises a verdict; the engine acts on it.
- **Judge report quality.** Structure is checkable; whether a plan is *good* is
  the reviewer's job, and the runner does not pretend otherwise.
- **Modify any repository file.** Only skills write source, and only `coding` and
  `fixer` among them.
