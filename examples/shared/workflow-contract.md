# Workflow Contract

How skills receive work and hand it on. This is the interface between skills;
`output-format.md` specifies the document a skill emits. Both are versioned
contracts — changing either is a breaking change for every skill in the chain.

**Contract version:** 1.0.0

---

## 1. The input envelope

Every skill invocation supplies four blocks. Any skill may refuse to run if a
required block is missing or unusable, and must say so rather than inventing the
missing content.

### Objective

One or two sentences stating the outcome wanted, in terms of the change to the
system — not the activity.

- Good: *"Users can page through their notes without loading the whole list."*
- Bad: *"Work on pagination."* (no outcome) — *"Add a `limit` query param."* (a
  solution, not an objective; it forecloses the plan)

If the objective embeds a solution, the skill records that as a constraint and
notes in `Open Questions` that the design was pre-decided upstream.

### Context

Everything the skill would otherwise have to guess. Cheap to supply, expensive to
omit.

- Work-unit reference, branch name
- Which module(s) or service(s) are in play
- Prior art: a similar existing slice worth copying
- Product decisions already made, and by whom
- Tracker-specific metadata passed via `--metadata` (area, labels, epic)

### Constraints

Hard boundaries. Anything not listed here is a preference, and a skill may
reasonably trade it away.

- The project's non-negotiables (see `constraints/default.md`)
- Situational limits: no breaking API changes, no new dependencies, ship this
  sprint
- Out-of-scope declarations — as load-bearing as in-scope ones

### Previous Outputs

The full, unedited reports of upstream skills, most recent last. Summaries are
not acceptable substitutes: a skill that receives a paraphrase will re-derive the
repository state and drift from the plan it is supposed to implement.

Empty for the first skill in a chain.

### Envelope skeleton

```markdown
## Objective
<outcome, 1–2 sentences>

## Context
<work unit, branch, modules, prior art, decisions already made>

## Constraints
<hard boundaries and explicit non-goals>

## Previous Outputs
<full upstream reports, oldest first — or "None (first skill in chain)">
```

---

## 2. The output envelope

Every skill emits the same six top-level sections, in this order, with these
exact headings. Full field-level specification in `output-format.md`.

| Section | Contains |
|---|---|
| `# Summary` | 3–6 sentences: what was done, what the reader should conclude. Standalone. |
| `# Findings` | Observed facts with evidence — file paths, line refs, command output. No recommendations. |
| `# Decisions` | Choices made, alternatives rejected, reason. One line each. |
| `# Deliverables` | Concrete artefacts produced: documents, files, diffs, reports. |
| `# Risks` | What could go wrong, with likelihood, impact, and mitigation. |
| `# Next Skill` | The recommended successor and why — or `None`, with the reason. |

Skills may add skill-specific `##` subsections **inside** these, never new `#`
sections. The `feature-planner`, for example, nests its full implementation plan
under `# Deliverables`.

---

## 3. Hand-off rules

1. **The report is the only channel.** No implicit state, no scratch files, no
   "as discussed earlier". If the next skill needs it, it is in the report.
2. **Findings are evidence-bearing.** Every factual claim cites a path, a symbol,
   a command, or an upstream report section. An unsourced claim is an assumption
   and belongs in `Risks` or `Open Questions`.
3. **Decisions are binding downstream.** A downstream skill that disagrees records
   the objection in `Risks` and routes back via `Next Skill`. It does not
   silently implement something else.
4. **Blockers halt the chain.** A genuine blocker means: emit the report with
   `Next Skill: None — blocked`, state precisely what is needed and from whom, and
   stop. Guessing past a blocker is the most expensive available failure.
5. **Scope is not expanded silently.** Work discovered mid-run that is outside the
   objective goes into `Findings` and `Open Questions`.
6. **Read-only means read-only.** Only `coding` and `fixer` modify production
   source. Every other skill treats the working tree as immutable.

---

## 4. Standard chain

```
feature-planner → coding → testing → reviewer → post-feature-implementation
                    ↑                    │
                    └──────── fixer ←─────┘
```

| Skill | Consumes | Produces | Writes source? |
|---|---|---|---|
| `feature-planner` | requirement | implementation plan | no |
| `coding` | plan | implementation | **yes** |
| `testing` | plan + implementation | test suites, coverage report | tests only |
| `reviewer` | plan + diff | review findings, severity-ranked | no |
| `post-feature-implementation` | full chain | docs update, PR description | no |
| `fixer` | findings from any reviewer | targeted remediation | **yes** |

Edges are recommendations, not dispatch. A human may enter the chain anywhere,
skip stages, or stop after `feature-planner` because the plan revealed the work
is not worth doing. That is a successful outcome, not a failed run.

---

## 5. Loops

Review skills route to `fixer`, and `fixer` routes back to the skill that raised
the findings, so the fix is verified by the party that objected.

Loop discipline:

- `fixer` addresses **only** the enumerated findings. Anything else it notices
  goes in its `Findings`, untouched.
- The re-review states, per finding, one of `fixed` / `skipped` / `no change
  needed`, with a reason for anything not fixed.
- Two full loops without convergence is an escalation. Emit `Next Skill: None —
  escalate` and name the disagreement plainly; a third automated attempt on a
  contested point wastes budget and buries the decision a human needs to make.

---

## 6. Conformance

A skill is conformant when it:

- accepts the four-block input envelope and names any block it requires;
- emits all six output sections, in order, with the exact headings;
- keeps every factual claim in `Findings` sourced;
- respects its declared write boundary without exception;
- terminates with an explicit `Next Skill`, including the `None` cases;
- ships an `examples/input.md` + `examples/output.md` pair that demonstrates all
  of the above.

Non-conformant output is a defect in the skill, not in the run. Fix the
`SKILL.md` and re-run — do not hand-patch the report.
